# FieldRig Vehicle Terminal

DIY vehicle-mounted computer terminal for a 2018 Toyota Corolla.
Raspberry Pi 5 replaces the factory head unit; 10.1" touchscreen on a
RAM mount; ZK-TB21 amp driving the factory speakers. Cyberdeck
aesthetic, functional daily driver, built in phases so it's always
usable mid-development.

```
 GPS  MESH  BT  SDR  OBD                        ♪ AUX  ⚡ --.-V  16:55
╭─ ▞▞ FIELDRIG ▸ HOME ────────────────────────────────────────────────╮
│ ╭─ ♪ NOW PLAYING ─────────────────────────────────────────────────╮ │
│ │                      Artist — Song Title                        │ │
│ │              ▶  ╞══════════════┄┄┄┄┄┄┄╡  2:11 / 3:45            │ │
│ │                 ▁▂▄▅▆▇█▇▆▅▄▂▁▂▄▅▆▇█▇▆▅▄                         │ │
│ ╰─────────────────────────────────── SOURCE BLUETOOTH · VOL 80% ──╯ │
│ ╭─ SPEED ──╮ ╭─ RPM ────╮ ╭─ FUEL ───────╮ ╭─ COOLANT ─╮           │
│ │   ---    │ │   ---    │ │     ---      │ │    ---    │           │
│ │   MPH    │ │  × 1000  │ │ % REMAINING  │ │    °F     │           │
│ ╰──────────╯ ╰──────────╯ ╰──────────────╯ ╰───────────╯           │
│ ╭─ ⚙ SYSTEM ──────────────────╮ ╭─ ◍ EVENT FEED ────────────────╮  │
│ │ CPU  █░░░░░░░░░   8%        │ │ 16:55:54 module_started audio │  │
│ │ RAM  ███░░░░░░░  1.2/4.0G   │ │ 16:55:58 bluetooth_connected  │  │
│ │ TMP  █████░░░░░  52°C       │ │                               │  │
│ ╰─────────────────────────────╯ ╰────────────────────────── BUS ╯  │
╰──────────────────────────────────────────────────────── v0.3.0 ▞▞ ─╯
  [⌂] [♪ AUDIO] [◈ NAV] [▣ OBD] [≋ RADIO] [✉ MESH] [◉ CAM] [⚙ SYS]
```

## Status

| Phase | Scope | Status |
|---|---|---|
| 1 | Core foundation: OS, touch, autologin, auto-boot | ✅ `setup/` scripts |
| 2 | Core app: Textual skeleton, dashboard, nav, event bus, module API | ✅ |
| 3 | Audio: PipeWire, Bluetooth screen, waveform, media controls, channel manager | ✅ |
| 4 | Vehicle data: OBD-II live gauges + trouble-code reader, auto-connect on plug-in | ✅ |
| 5 | Navigation (GPSD + MBTiles) | planned |
| 6 | Radio (RTL-SDR) | planned |
| 7 | Mesh (Meshtastic) | planned |
| 8 | Camera: USB UVC capture -> live MJPEG feed, auto-detect on plug-in | ✅ |
| 9 | Polish | planned |

## Architecture: looks like a TUI, isn't one

The UI is a fullscreen **Chromium kiosk** rendering a phosphor-console
page; a local **FastAPI server** owns the hardware modules and bridges
the event bus to the page over a WebSocket. That split is what makes
the later phases real: the backup camera is an MJPEG stream in an
`<img>` tag (Phase 8), maps are MapLibre GL JS over local MBTiles
(Phase 5), the SDR waterfall is a 60fps canvas (Phase 6) — none of
which a real terminal can render.

```
Phone ─(A2DP/AVRCP)─► Pi: FastAPI server (core engine + modules)
                          │ WebSocket events / commands
                          ▼
                      Chromium --kiosk → localhost:8000
```

## Layout

```
fieldrig/
├── core/            engine: event bus, Module API, module manager,
│                    pyudev hotplug watcher, ignition power monitor,
│                    /proc-based system stats
├── modules/audio/   PipeWire (wpctl), BlueZ pairing agent + device
│                    management (bluetoothctl), MPRIS media control
│                    (busctl), waveform analyzer (PyAudio w/ simulation
│                    fallback), channel manager with auto-ducking
├── modules/obd/     ELM327 OBD-II reader (python-OBD): live speed/RPM/fuel/
│                    coolant/voltage PIDs + diagnostic trouble codes, auto-
│                    connecting when the USB dongle is plugged in
├── modules/camera/  USB UVC capture (OpenCV) in a background thread, restreamed
│                    as MJPEG; auto-detects the capture card on hotplug
├── server/          FastAPI: websocket event bridge, command dispatch,
│                    /api/state snapshot, /camera.mjpg live MJPEG stream
├── web/             the kiosk page: HTML/CSS/JS phosphor console
└── ui/              Textual debug console (same core, run over SSH)
setup/               Phase 1 install scripts for the Pi (see setup/README.md)
```

## Running on the Pi

Flash Raspberry Pi OS Lite 64-bit, clone the repo, and run the one-shot
installer:

```bash
git clone <repo> ~/fieldrig
cd ~/fieldrig
./install.sh
sudo reboot
```

Ignition on → tty1 autologin → server starts as a user service → cage +
Chromium kiosk fullscreen in ~15-20 seconds. See `setup/README.md` for the
per-step breakdown and verification.

Once the kiosk works, seal the card read-only so the car's hard power-off
can't corrupt it: `sudo fieldrig-seal`. Runtime writes then go to tmpfs, and
the in-app UPDATE button briefly remounts read-write to pull updates. Full
details in `setup/README.md`.

## Running on a dev machine

No car required — hardware pieces degrade gracefully (waveform
simulates, Bluetooth/PipeWire report unavailable):

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m fieldrig                # server → open localhost:8000
.venv/bin/python -m fieldrig --tui          # Textual debug console
.venv/bin/python -m fieldrig --check        # headless module check
.venv/bin/python scripts/smoke_test_web.py  # server + websocket test
.venv/bin/python scripts/smoke_test.py      # TUI test
```

## Architecture notes

- **Event bus** (`core/events.py`): modules emit (`audio_update`,
  `waveform_update`, `bluetooth_update`, ...); the server fans every
  event out to the page over `/ws`, and commands come back the same
  way. No UI polling.
- **Module API** (`core/module.py`): every hardware module implements
  `start / stop / status / ui_data`, all async, all safe without the
  hardware attached.
- **Audio channels** (`modules/audio/channels.py`): named channels
  with priorities; music auto-ducks under navigation voice and alerts
  (alerts win over everything) and recovers when they finish.
- **Bluetooth direction**: the Pi is the head unit — phones pair *to*
  it. A persistent NoInputNoOutput agent auto-accepts pairing while
  PAIR MODE has the Pi discoverable as "FieldRig"; paired phones are
  auto-trusted so they reconnect every drive. PipeWire receives the
  A2DP stream and routes it out the aux jack to the amp, and
  `mpris-proxy` exposes the phone as an MPRIS player so the audio
  screen shows track info and prev/play/next actually drive the phone.
- **System tools over pip deps**: PipeWire via `wpctl`, BlueZ via
  `bluetoothctl`, MPRIS via `busctl` — nothing to compile.
- **Hotplug auto-activation**: the OBD and camera modules start at boot and
  sit idle without their hardware. The pyudev watcher's `hardware_added`
  event wakes their reconnect loops, so plugging in the ELM327 dongle or the
  USB capture card brings the gauges / live feed up within a couple of
  seconds — no restart, nothing to write to the sealed read-only card. Both
  query/stream only (the one ECU write, CLEAR CODES, never touches the disk).
- **Power**: GPIO 17 watches switched 12V; on ignition cut, modules get
  `power_loss` to save state, then a graceful shutdown (only when
  `FIELDRIG_ENABLE_SHUTDOWN=1`, which the in-car launcher sets).
- **Logs**: `/var/log/fieldrig/` (`boot.log`, `errors.log`, per-module
  files), falling back to `~/.local/state/fieldrig/logs` off the Pi.
"# toyotapi" 
