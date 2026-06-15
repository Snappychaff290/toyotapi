# FieldRig Phase 1: Core Foundation

Takes a fresh Manjaro ARM KDE Plasma install on the Pi 5 to a
touch-configured terminal that boots straight into the FieldRig app.

## Step 0 — Flash Manjaro ARM KDE (manual, once)

1. Download the Manjaro ARM **KDE Plasma** image for Raspberry Pi
   (rpi4 image — it covers the Pi 5) from https://manjaro.org/download/
2. Flash to the Samsung Pro Endurance microSD:
   ```
   xzcat Manjaro-ARM-kde-plasma-rpi4-*.img.xz | sudo dd of=/dev/sdX bs=4M status=progress conv=fsync
   ```
3. Boot the Pi with the touchscreen attached, complete the first-boot
   wizard (user, locale, wifi).
4. Clone this repo onto the Pi, e.g. `git clone <repo> ~/fieldrig`.

## Steps 1-5 — Run the scripts in order

```bash
cd ~/fieldrig/setup
./01-system.sh      # packages (incl. chromium), audio/bluetooth services
./02-kde-touch.sh   # KDE touch targets, fonts, virtual keyboard
./03-autologin.sh   # SDDM autologin to Plasma
./04-python-env.sh  # venv + FieldRig install with Pi extras
./05-autostart.sh   # server user service + Chromium kiosk at login
reboot
```

After the reboot: ignition on → Pi boots → KDE autologin → the
FieldRig server starts (systemd user service) → Chromium opens
fullscreen on it, in roughly 15-20 seconds.

## Verifying

- `systemctl --user status fieldrig-server` — server health;
  `~/.local/share/fieldrig/venv/bin/python -m fieldrig --check` runs
  the modules headless and reports status.
- Touch test: tap the nav bar buttons in the kiosk.
- SSH debug: `python -m fieldrig --tui` gives a Textual console over
  SSH against the same core code (handy when the screen is in the car).
- Pairing test: AUDIO → BT → PAIR MODE, then pick "FieldRig" in the
  phone's Bluetooth menu. Pairing is auto-accepted, the phone is
  auto-trusted (so it reconnects every drive), and phone audio plays
  out the Pi's aux jack to the amp. Track info and prev/play/next on
  the audio screen control the phone via AVRCP (mpris-proxy).
- Logs land in `/var/log/fieldrig/` (created by 01-system.sh).

## Notes

- The ignition GPIO sense line defaults to BCM pin 17; override with
  `FIELDRIG_IGNITION_PIN`. Graceful shutdown only happens when
  `FIELDRIG_ENABLE_SHUTDOWN=1` is set (the autostart launcher sets it;
  dev sessions don't).
- `mpris-proxy` (from bluez-utils) bridges a phone connected over
  Bluetooth into MPRIS so FieldRig can show and control phone media.
