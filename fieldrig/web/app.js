/* FieldRig front end: one WebSocket in, commands out, DOM updates.
   No framework -- the page is small enough that plain JS stays clear. */

"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const NOISY = new Set(["waveform_update", "audio_update", "system_update",
                       "audio_channels_update", "bluetooth_update",
                       "obd_update", "camera_update"]);
const STATUS_ICONS = { Playing: "▶", Paused: "⏸", Stopped: "⏹" };
const PROGRESS_WIDTH = 28;

let ws = null;
let selectedMac = null;
let btDevices = [];
let pendingReload = false;
// Last known track progress; the bar is advanced locally between updates
// because MPRIS (by spec) doesn't push Position changes. See renderProgress().
let npState = { position: null, length: null, status: "Stopped", at: 0 };

/* ---------- helpers ---------- */

function meter(fraction, segments) {
  const filled = Math.round(Math.max(0, Math.min(1, fraction)) * segments);
  return "█".repeat(filled) + "░".repeat(segments - filled);
}

function fmtTime(us) {
  if (!Number.isFinite(us) || us < 0) return "--:--";
  const s = Math.floor(us / 1e6);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function send(cmd, extra = {}) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ cmd, ...extra }));
  }
}

/* ---------- theme ---------- */

/* A theme is four colour roles, each {h, s}. Every CSS shade is derived from
   one role at a fixed lightness, so presets stay compact and the custom sliders
   need only a hue + sat per role. Roles:
     accent  -- live data, default text, gauges, primary buttons, glow, wave top
     chrome  -- panel titles, progress, body text on panels, waveform base
     surface -- backgrounds, panels, borders (keep saturation low for greys)
     muted   -- secondary / tertiary text                                      */

const THEME_ROLES = ["accent", "chrome", "surface", "muted"];

// role -> [[cssVar, lightness%], ...]. --glow and the waveform are separate.
const THEME_MAP = {
  accent:  [["--bright", 52]],
  chrome:  [["--mid", 46]],
  muted:   [["--dim", 34], ["--dimmer", 22]],
  surface: [["--bg", 6], ["--raised", 10], ["--border", 18], ["--border-hi", 30]],
};

const PRESETS = [
  { name: "GREEN",  accent: {h:135,s:100}, chrome: {h:135,s:85}, surface: {h:135,s:12}, muted: {h:135,s:40} },
  { name: "AMBER",  accent: {h:40,s:100},  chrome: {h:33,s:90},  surface: {h:35,s:10},  muted: {h:38,s:45} },
  { name: "PURPLE", accent: {h:275,s:80},  chrome: {h:300,s:62}, surface: {h:270,s:10}, muted: {h:282,s:28} },
  { name: "ORANGE", accent: {h:25,s:95},   chrome: {h:42,s:88},  surface: {h:25,s:8},   muted: {h:30,s:32} },
  { name: "ICE",    accent: {h:190,s:90},  chrome: {h:205,s:72}, surface: {h:200,s:10}, muted: {h:198,s:28} },
  { name: "EMBER",  accent: {h:0,s:82},    chrome: {h:18,s:88},  surface: {h:0,s:9},    muted: {h:6,s:30} },
  { name: "SYNTH",  accent: {h:315,s:90},  chrome: {h:250,s:80}, surface: {h:260,s:14}, muted: {h:290,s:34} },
  { name: "MONO",   accent: {h:0,s:0},     chrome: {h:0,s:0},    surface: {h:0,s:0},    muted: {h:0,s:0} },
];

const DEFAULT_THEME = PRESETS[0];
let theme = JSON.parse(JSON.stringify(DEFAULT_THEME));
// Waveform gradient (canvas can't read CSS vars, so we compute them here).
let waveLo = "hsl(135, 85%, 38%)";
let waveHi = "hsl(135, 100%, 52%)";

function normTheme(t) {
  const out = {};
  for (const role of THEME_ROLES) {
    const c = (t && t[role]) || DEFAULT_THEME[role];
    out[role] = {
      h: Math.max(0, Math.min(360, Math.round(Number(c.h)))),
      s: Math.max(0, Math.min(100, Math.round(Number(String(c.s).replace("%", ""))))),
    };
  }
  return out;
}

function sameTheme(a, b) {
  return THEME_ROLES.every((r) => a[r].h === b[r].h && a[r].s === b[r].s);
}

// Apply locally only. Persistence is explicit: presets persist, custom doesn't.
function applyTheme(t) {
  theme = normTheme(t);
  const root = document.documentElement;
  for (const role of THEME_ROLES) {
    const { h, s } = theme[role];
    for (const [v, l] of THEME_MAP[role])
      root.style.setProperty(v, `hsl(${h}, ${s}%, ${l}%)`);
  }
  const a = theme.accent, c = theme.chrome;
  root.style.setProperty("--glow", `hsla(${a.h}, ${a.s}%, 58%, 0.45)`);
  waveHi = `hsl(${a.h}, ${a.s}%, 52%)`;
  waveLo = `hsl(${c.h}, ${c.s}%, 38%)`;

  // Highlight the matching preset, or CUSTOM if it's a one-off.
  const match = PRESETS.find((p) => sameTheme(normTheme(p), theme));
  $$("#theme-presets .preset[data-preset]").forEach((b) =>
    b.classList.toggle("current", !!match && b.dataset.preset === match.name));
  const customBtn = $("#theme-custom-btn");
  if (customBtn) customBtn.classList.toggle("current", !match);
  syncCustomControls();
}

// Mirror the active theme onto the custom sliders + their preview swatches.
function syncCustomControls() {
  for (const role of THEME_ROLES) {
    const { h, s } = theme[role];
    const hEl = $(`#ch-${role}`), sEl = $(`#cs-${role}`), sw = $(`#sw-${role}`);
    if (hEl) hEl.value = h;
    if (sEl) sEl.value = s;
    if (sw) sw.style.background = `hsl(${h}, ${s}%, 50%)`;
  }
}

// Save the current theme (presets only — custom edits never call this).
function persistTheme() {
  try { localStorage.setItem("fr-theme", JSON.stringify(theme)); } catch (e) {}
  send("set_theme", { theme });
}

// Build a theme from the custom sliders and apply it live, never persisted.
function applyCustomFromSliders() {
  const t = {};
  for (const role of THEME_ROLES)
    t[role] = { h: Number($(`#ch-${role}`).value), s: Number($(`#cs-${role}`).value) };
  applyTheme(t);
}

// Build the preset buttons from PRESETS, each previewing its own colours.
function buildPresets() {
  const wrap = $("#theme-presets");
  const customBtn = $("#theme-custom-btn");
  if (!wrap) return;
  PRESETS.forEach((p) => {
    const b = document.createElement("button");
    b.className = "preset";
    b.dataset.preset = p.name;
    b.textContent = p.name;
    b.style.color = `hsl(${p.accent.h}, ${p.accent.s}%, 58%)`;
    b.style.borderColor = `hsl(${p.chrome.h}, ${p.chrome.s}%, 46%)`;
    b.style.background = `hsl(${p.surface.h}, ${p.surface.s}%, 9%)`;
    wrap.insertBefore(b, customBtn);   // keep CUSTOM last
  });
}

/* ---------- screen rotation ---------- */

// CSS rotates #viewport (see style.css); the browser keeps touch correct.
let rotation = 0;
const ROT_STEPS = [0, 90, 180, 270];

function applyRotation(deg) {
  deg = ((Math.round(Number(deg) / 90) * 90) % 360 + 360) % 360;
  if (!Number.isFinite(deg)) return;
  rotation = deg;

  const body = document.body;
  ROT_STEPS.forEach((d) => body.classList.toggle(`rot-${d}`, d === deg));

  // Cache for instant re-apply on the next load (e.g. post-update reload), so
  // the UI doesn't flash in the old orientation before the server's value lands.
  try { localStorage.setItem("fr-rotation", String(deg)); } catch (e) {}

  $$("#orient .rotbtn").forEach((b) =>
    b.classList.toggle("current", Number(b.dataset.rot) === deg));
}

function persistRotation() {
  send("set_rotation", { deg: rotation });
}

/* ---------- screen switching ---------- */

function show(name) {
  $$(".screen").forEach((s) => s.classList.remove("active"));
  const target = $(`#screen-${name}`);
  if (target) target.classList.add("active");
  $("#screen-name").textContent =
    { home: "HOME", audio: "AUDIO", bluetooth: "BLUETOOTH", nav: "NAVIGATION",
      obd: "TELEMETRY", radio: "RADIO", mesh: "MESH NETWORK",
      camera: "CAMERA", system: "SYSTEM" }[name] || name.toUpperCase();
  const navKey = name === "bluetooth" ? "audio" : name;
  $$("#navbar button").forEach((b) =>
    b.classList.toggle("current", b.dataset.screen === navKey));
}

document.addEventListener("click", (e) => {
  const button = e.target.closest("button");
  if (!button) return;
  if (button.dataset.screen) show(button.dataset.screen);
  else if (button.dataset.preset !== undefined) {
    const p = PRESETS.find((x) => x.name === button.dataset.preset);
    if (p) { applyTheme(p); persistTheme(); }           // instant + saved
    $("#custom-theme").classList.add("hidden");
  }
  else if (button.dataset.themeCustom !== undefined) {
    // Reveal the live sliders seeded from the current colours (not saved).
    $("#custom-theme").classList.remove("hidden");
    syncCustomControls();
    $$("#theme-presets .preset[data-preset]").forEach((b) =>
      b.classList.remove("current"));
    button.classList.add("current");
  }
  else if (button.dataset.rot !== undefined) {
    applyRotation(button.dataset.rot);                  // instant, local
    persistRotation();
  }
  else if (button.dataset.rotStep !== undefined) {
    applyRotation(rotation + Number(button.dataset.rotStep));
    persistRotation();
  }
  else if (button.dataset.cmd) send(button.dataset.cmd);
  else if (button.dataset.bt) {
    if (selectedMac === null) {
      $("#bt-status").textContent = "SELECT A DEVICE FIRST";
    } else {
      $("#bt-status").textContent =
        `${button.dataset.bt.replace("bt_", "").toUpperCase()} ${selectedMac}...`;
      send(button.dataset.bt, { mac: selectedMac });
    }
  }
});

/* ---------- event handlers ---------- */

// Draw the now-playing bar from npState, interpolating position locally while
// playing so it advances smoothly between the server's (event-driven) updates.
function renderProgress() {
  const { position, length, status, at } = npState;
  const icon = STATUS_ICONS[status] || "⏹";
  let bar = "┄".repeat(PROGRESS_WIDTH);
  let timing = "";
  if (Number.isFinite(position) && Number.isFinite(length) && length > 0) {
    let pos = position;
    if (status === "Playing") pos += (performance.now() - at) * 1000;  // ms→µs
    pos = Math.max(0, Math.min(length, pos));
    const filled = Math.round(PROGRESS_WIDTH * (pos / length));
    bar = "═".repeat(filled) + "┄".repeat(PROGRESS_WIDTH - filled);
    timing = `  ${fmtTime(pos)} / ${fmtTime(length)}`;
  }
  $$(".v-np-progress").forEach((el) => {
    el.textContent = `${icon}  ╞${bar}╡${timing}`;
  });
}

function onAudio(state) {
  if (!state) return;
  const hasTitle = Boolean(state.title);
  $$(".v-np-title").forEach((el) => {
    el.textContent = hasTitle ? state.title : "NO MEDIA";
    el.classList.toggle("dim", !hasTitle);
  });
  $$(".v-np-artist").forEach((el) => {
    if (hasTitle) {
      el.textContent = (state.artist || "UNKNOWN ARTIST")
        + (state.album ? `  ·  ${state.album}` : "");
    } else {
      el.textContent = "pair a phone or start a player";
    }
  });

  // Re-anchor the progress bar; renderProgress() advances it from here.
  npState = {
    position: Number.isFinite(state.position) ? state.position : null,
    length: Number.isFinite(state.length) ? state.length : null,
    status: state.status || "Stopped",
    at: performance.now(),
  };
  renderProgress();

  const volume = state.volume ?? 0;
  $$(".v-source").forEach((el) => { el.textContent = state.source || "--"; });
  $$(".v-btline").forEach((el) => {
    el.textContent = state.bt_connected
      ? `⛉ ${state.bt_device || "PHONE"} LINKED`
      : "⛉ NO PHONE LINKED";
  });
  $$(".v-volmeter").forEach((el) => {
    el.textContent = `${meter(volume, 20)} ${String(Math.round(volume * 100)).padStart(3)}%`;
  });
  $$(".v-volstate").forEach((el) => {
    el.textContent = state.muted ? "◼ MUTED" : "◻ LIVE";
    el.style.color = state.muted ? "#ff4141" : "";
  });

  $("#np-sub").textContent =
    `SOURCE ${state.source || "--"} · VOL ${Math.round(volume * 100)}%`;
  $("#chip-bt").classList.toggle("on", Boolean(state.bt_connected));
  $("#src-ind").textContent =
    state.source === "BLUETOOTH" ? "♪ BT" : "♪ AUX";
}

function onWaveform(levels) {
  $$("canvas.waveform").forEach((canvas) => {
    const ctx = canvas.getContext("2d");
    const { width: w, height: h } = canvas;
    ctx.clearRect(0, 0, w, h);
    const slot = w / levels.length;
    const gradient = ctx.createLinearGradient(0, h, 0, 0);
    gradient.addColorStop(0, waveLo);
    gradient.addColorStop(1, waveHi);
    ctx.fillStyle = gradient;
    levels.forEach((level, i) => {
      const barH = Math.max(2, level * h);
      ctx.fillRect(i * slot + slot * 0.18, h - barH, slot * 0.64, barH);
    });
  });
}

function onBluetooth(data) {
  btDevices = data.devices || [];
  if (data.message) $("#bt-status").textContent = data.message;
  const list = $("#bt-list");
  list.innerHTML = "";
  btDevices.forEach((device, i) => {
    const li = document.createElement("li");
    li.textContent = `${device.connected ? "◉" : "○"} `
      + `${device.name.padEnd(28)} ${device.mac}   [${device.flags}]`;
    li.classList.toggle("connected", device.connected);
    li.classList.toggle("selected", device.mac === selectedMac);
    li.addEventListener("click", () => {
      selectedMac = device.mac;
      $$("#bt-list li").forEach((el, j) =>
        el.classList.toggle("selected", j === i));
    });
    list.appendChild(li);
  });
}

/* ---------- OBD-II telemetry ---------- */

// Set a value on the home gauge and the OBD-screen gauge that share a metric.
function setGauge(homeId, obdId, text) {
  const a = $(homeId); if (a) a.textContent = text;
  const b = $(obdId); if (b) b.textContent = text;
}

function onObd(state) {
  if (!state) return;
  const live = !!state.connected;
  const fmt = (v, fn) => (Number.isFinite(v) ? fn(v) : "---");

  setGauge("#g-speed", "#o-speed", fmt(state.speed_mph, (v) => String(Math.round(v))));
  setGauge("#g-rpm", "#o-rpm", fmt(state.rpm, (v) => (v / 1000).toFixed(1)));
  setGauge("#g-fuel", "#o-fuel", fmt(state.fuel_pct, (v) => String(Math.round(v))));
  setGauge("#g-temp", "#o-temp", fmt(state.coolant_f, (v) => String(Math.round(v))));
  const ov = $("#o-volt");
  if (ov) ov.textContent = fmt(state.voltage, (v) => v.toFixed(1));

  $("#volt").textContent = Number.isFinite(state.voltage)
    ? `⚡ ${state.voltage.toFixed(1)}V` : "⚡ --.-V";
  $("#chip-obd").classList.toggle("on", live);
  const link = $("#obd-link");
  if (link) link.textContent = live ? "▣ CONNECTED — LIVE TELEMETRY"
                                    : "SCANNING FOR ADAPTER…";
}

function onDtc(data) {
  const list = $("#dtc-list");
  const status = $("#dtc-status");
  if (status) status.textContent = data.message || "—";
  if (!list) return;
  list.innerHTML = "";
  (data.codes || []).forEach((c) => {
    const li = document.createElement("li");
    li.innerHTML = `<span class="dtc-code">${c.code}</span> ${c.desc || ""}`;
    list.appendChild(li);
  });
}

/* ---------- camera ---------- */

function onCamera(state) {
  const section = $("#screen-camera");
  const live = $("#cam-live");
  const offline = $("#cam-offline");
  const img = $("#cam-img");
  if (!section || !live || !offline || !img) return;
  if (state && state.connected) {
    section.classList.remove("placeholder");
    offline.classList.add("hidden");
    live.classList.remove("hidden");
    // Cache-bust so a reconnected card restarts the stream cleanly.
    if (!img.src || !img.src.includes("/camera.mjpg"))
      img.src = `/camera.mjpg?t=${Date.now()}`;
  } else {
    section.classList.add("placeholder");
    live.classList.add("hidden");
    offline.classList.remove("hidden");
    img.removeAttribute("src");   // stop the in-flight MJPEG request
  }
}

function onSystem(info) {
  const lines = [`CPU  ${meter(info.cpu ?? 0, 10)}  ${String(Math.round((info.cpu ?? 0) * 100)).padStart(3)}%`];
  if (info.ram_total) {
    lines.push(`RAM  ${meter(info.ram_used / info.ram_total, 10)}  `
      + `${info.ram_used.toFixed(1)} / ${info.ram_total.toFixed(1)}G`);
  } else {
    lines.push("RAM  unavailable");
  }
  lines.push(info.temp != null
    ? `TMP  ${meter(info.temp / 85, 10)}  ${Math.round(info.temp)}°C`
    : "TMP  no sensor");
  $("#sysstats").textContent = lines.join("\n");
}

function onUpdate(info) {
  const el = $("#update-status");
  if (el) el.textContent = info.message || info.stage || "";
  // The server is about to restart; reload once we reconnect to the new one
  // so refreshed HTML/CSS/JS are actually fetched (a stale chromium wouldn't).
  if (info.stage === "applying") pendingReload = true;
}

function feed(event, data) {
  const stamp = new Date().toTimeString().slice(0, 8);
  let detail = "";
  if (data && typeof data === "object") {
    detail = data.name || data.model || data.mac || "";
    if (detail) detail = ` ${detail}`;
  }
  const el = $("#eventfeed");
  const line = document.createElement("div");
  line.innerHTML = `<span class="t">${stamp}</span> ${event}${detail}`;
  el.appendChild(line);
  while (el.children.length > 4) el.removeChild(el.firstChild);
}

/* ---------- websocket ---------- */

function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onmessage = (msg) => {
    const { event, data } = JSON.parse(msg.data);
    if (event === "audio_update") onAudio(data);
    else if (event === "waveform_update") onWaveform(data);
    else if (event === "bluetooth_update") onBluetooth(data);
    else if (event === "obd_update") onObd(data);
    else if (event === "obd_dtc_update") onDtc(data);
    else if (event === "camera_update") onCamera(data);
    else if (event === "system_update") onSystem(data);
    else if (event === "update_status") onUpdate(data);
    else if (event === "theme_update") applyTheme(data);
    else if (event === "rotation_update") applyRotation(data.deg);
    if (!NOISY.has(event)) feed(event, data);
  };
  ws.onopen = () => {
    // Reconnected to a server that just restarted from an update -> reload
    // the page so the new front-end assets load.
    if (pendingReload) { location.reload(); return; }
    feed("ui_connected", null);
    send("bt_refresh");
  };
  ws.onclose = () => setTimeout(connect, 1000);
}

/* ---------- boot ---------- */

buildPresets();

// Custom sliders recolour live while dragging; they are never persisted.
THEME_ROLES.forEach((role) => {
  [`ch-${role}`, `cs-${role}`].forEach((id) => {
    const el = $(`#${id}`);
    if (el) el.addEventListener("input", applyCustomFromSliders);
  });
});

// Apply the cached theme immediately so there's no colour flash before the
// server's saved theme arrives. (Cache only ever holds a saved preset.)
try {
  const t = JSON.parse(localStorage.getItem("fr-theme") || "null");
  if (t) applyTheme(t);
} catch (e) {}

// Same for the saved orientation.
try {
  const r = localStorage.getItem("fr-rotation");
  if (r !== null) applyRotation(r);
} catch (e) {}

fetch("/api/state")
  .then((r) => r.json())
  .then((snapshot) => {
    $("#frame-sub").textContent = `v${snapshot.version} ▞▞`;
    const sv = $("#sys-version");
    if (sv) sv.textContent = `v${snapshot.version}`;
    if (snapshot.theme) applyTheme(snapshot.theme);
    if (snapshot.rotation != null) applyRotation(snapshot.rotation);
    onAudio(snapshot.audio);
    if (snapshot.obd) {
      onObd(snapshot.obd);
      onDtc({ codes: snapshot.obd.dtcs || [],
              message: snapshot.obd.connected ? undefined : "OFFLINE" });
    }
    onCamera(snapshot.camera);
  })
  .catch(() => {});

setInterval(() => {
  $("#clock").textContent =
    new Date().toTimeString().slice(0, 5);
}, 1000);

// Advance the progress bar locally between server updates (see renderProgress).
setInterval(renderProgress, 250);

connect();
show("home");
