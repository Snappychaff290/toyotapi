# FieldRig Phase 1: Core Foundation

Takes a fresh **Raspberry Pi OS Lite 64-bit** install on a Pi 5 to a
touch-configured kiosk that boots straight into the FieldRig app.

## Step 0 — Flash Raspberry Pi OS Lite (manual, once)

1. Download Raspberry Pi OS Lite 64-bit from https://www.raspberrypi.com/software/
2. Flash with Raspberry Pi Imager — set username, wifi, SSH, and hostname in
   the Imager's advanced settings before flashing.
3. Boot, SSH in, clone this repo:
   ```bash
   git clone <repo> ~/fieldrig
   ```

## One-shot install (recommended)

From the repo root, run the whole thing with a single command:

```bash
cd ~/fieldrig
./install.sh           # runs steps 01-05 in order
sudo reboot
```

`./install.sh --reboot` reboots automatically when it finishes. Run it as
your normal user (not root) — it installs per-user systemd services.

## Or run the steps individually

```bash
cd ~/fieldrig/setup
./01-system.sh       # apt packages, groups, bluetooth, PipeWire, log dir
./02-display.sh      # fonts for the kiosk
./03-autologin.sh    # console autologin on tty1 (no display manager)
./04-python-env.sh   # venv + FieldRig install with Pi extras
./05-autostart.sh    # server user service + cage kiosk launcher on login
reboot
```

After reboot: Pi autologins on tty1 → cage starts → FieldRig server starts as
a user service → Chromium opens fullscreen in roughly 15-20 seconds.

## Verifying

- `systemctl --user status fieldrig-server` — server health
- `~/.local/share/fieldrig/venv/bin/python -m fieldrig --check` — headless module check
- Touch test: tap the nav bar in the kiosk
- SSH debug console: `~/.local/share/fieldrig/venv/bin/python -m fieldrig --tui`
- Bluetooth: AUDIO → BT → PAIR MODE, pair your phone to "FieldRig"
- Logs: `/var/log/fieldrig/` and `~/.local/state/fieldrig/logs`

## Notes

- Ignition GPIO sense defaults to BCM pin 17; override with `FIELDRIG_IGNITION_PIN`.
  Graceful shutdown only fires when `FIELDRIG_ENABLE_SHUTDOWN=1` (the autostart
  launcher sets it; dev sessions don't).
- `mpris-proxy` bridges a Bluetooth-connected phone into MPRIS so FieldRig can
  show and control phone media.
- **gpiod caveat:** Pi OS Bookworm ships libgpiod 1.6.x but `gpiod>=2.1` needs
  libgpiod 2.x. If pip fails on gpiod, step 4 will install the rest of the Pi
  extras without it — GPIO ignition sense degrades gracefully.
