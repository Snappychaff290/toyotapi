/* FieldRig front end: one WebSocket in, commands out, DOM updates.
   No framework -- the page is small enough that plain JS stays clear. */

"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const NOISY = new Set(["waveform_update", "audio_update", "system_update",
                       "audio_channels_update", "bluetooth_update"]);
const STATUS_ICONS = { Playing: "▶", Paused: "⏸", Stopped: "⏹" };
const PROGRESS_WIDTH = 28;

let ws = null;
let selectedMac = null;
let btDevices = [];
let pendingReload = false;

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

// Lightness of each shade; the whole palette is one hue+saturation at these.
const SHADE_L = {
  "--bright": 50, "--mid": 42, "--dim": 28, "--dimmer": 20,
  "--border": 12, "--border-hi": 25, "--raised": 6,
};
let theme = { h: 135, s: 100 };
// Waveform gradient colours, kept in sync with the theme (canvas can't read
// CSS variables, so we compute them here).
let waveLo = "hsl(135, 100%, 28%)";
let waveHi = "hsl(135, 100%, 50%)";

function applyTheme(h, s) {
  h = Math.round(Number(h));
  s = Math.round(parseFloat(s));            // accepts 100 or "100%"
  if (!Number.isFinite(h) || !Number.isFinite(s)) return;
  theme = { h, s };

  const root = document.documentElement;
  for (const v in SHADE_L)
    root.style.setProperty(v, `hsl(${h}, ${s}%, ${SHADE_L[v]}%)`);
  root.style.setProperty("--glow", `hsla(${h}, ${s}%, 55%, 0.45)`);
  waveLo = `hsl(${h}, ${s}%, 28%)`;
  waveHi = `hsl(${h}, ${s}%, 50%)`;

  // Cache for instant re-apply on the next load (e.g. post-update reload).
  try { localStorage.setItem("fr-theme", JSON.stringify(theme)); } catch (e) {}

  // Keep the controls in sync (slider drag, swatch tap, or remote update).
  if ($("#hue")) $("#hue").value = h;
  if ($("#sat")) $("#sat").value = s;
  if ($("#hue-val")) $("#hue-val").textContent = `${h}°`;
  if ($("#sat-val")) $("#sat-val").textContent = `${s}%`;
  $$("#swatches .swatch").forEach((b) =>
    b.classList.toggle("current",
      Number(b.dataset.h) === h && parseInt(b.dataset.s, 10) === s));
}

function persistTheme() {
  send("set_theme", { h: theme.h, s: `${theme.s}%` });
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
  else if (button.dataset.h !== undefined) {
    applyTheme(button.dataset.h, button.dataset.s);     // instant, local
    persistTheme();
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

  const icon = STATUS_ICONS[state.status] || "⏹";
  let bar = "┄".repeat(PROGRESS_WIDTH);
  let timing = "";
  if (Number.isFinite(state.position) && Number.isFinite(state.length)
      && state.length > 0) {
    const filled = Math.round(PROGRESS_WIDTH
      * Math.min(1, state.position / state.length));
    bar = "═".repeat(filled) + "┄".repeat(PROGRESS_WIDTH - filled);
    timing = `  ${fmtTime(state.position)} / ${fmtTime(state.length)}`;
  }
  $$(".v-np-progress").forEach((el) => {
    el.textContent = `${icon}  ╞${bar}╡${timing}`;
  });

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
    else if (event === "system_update") onSystem(data);
    else if (event === "update_status") onUpdate(data);
    else if (event === "theme_update") applyTheme(data.h, data.s);
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

// Sliders: recolor live while dragging, persist once on release.
["hue", "sat"].forEach((id) => {
  const el = $(`#${id}`);
  if (!el) return;
  el.addEventListener("input", () => applyTheme($("#hue").value, $("#sat").value));
  el.addEventListener("change", persistTheme);
});

// Apply the cached theme immediately so there's no green flash before the
// server's saved theme arrives.
try {
  const t = JSON.parse(localStorage.getItem("fr-theme") || "null");
  if (t) applyTheme(t.h, t.s);
} catch (e) {}

fetch("/api/state")
  .then((r) => r.json())
  .then((snapshot) => {
    $("#frame-sub").textContent = `v${snapshot.version} ▞▞`;
    const sv = $("#sys-version");
    if (sv) sv.textContent = `v${snapshot.version}`;
    if (snapshot.theme) applyTheme(snapshot.theme.h, snapshot.theme.s);
    onAudio(snapshot.audio);
  })
  .catch(() => {});

setInterval(() => {
  $("#clock").textContent =
    new Date().toTimeString().slice(0, 5);
}, 1000);

connect();
show("home");
