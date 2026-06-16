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
./install.sh           # runs steps 01-06 in order
sudo reboot
```

`./install.sh --reboot` reboots automatically when it finishes. Run it as
your normal user (not root) — it installs per-user systemd services. It
leaves the filesystem **writable**; you seal it read-only afterward (below).

## Or run the steps individually

```bash
cd ~/fieldrig/setup
./01-system.sh           # apt packages, groups, bluetooth, PipeWire, log dir
./02-display.sh          # fonts for the kiosk
./03-autologin.sh        # console autologin on tty1 (no display manager)
./04-python-env.sh       # venv + FieldRig install with Pi extras
./05-autostart.sh        # server service + cage kiosk launcher + hidden cursor
./06-readonly.sh --no-seal  # read-only tooling + tmpfs (stays writable)
reboot
```

## Read-only filesystem (do this once the kiosk works)

A car cuts power the instant the ignition turns off, so the SD card must
never be mid-write or it corrupts. After you've rebooted and confirmed the
kiosk runs, seal the filesystem read-only:

```bash
sudo fieldrig-seal       # adds `ro` to root+boot in fstab, then reboots
```

From then on the root filesystem is read-only and all runtime writes
(logs, the Chromium profile) go to tmpfs (RAM) — a hard power-off can't
corrupt the card. Managing it:

- **In-app UPDATE button** — automatically remounts read-write, pulls,
  re-seals read-only, and restarts. No manual steps.
- `fieldrig-rw` / `fieldrig-ro` — remount read-write/read-only *now*
  (doesn't change the boot default) for quick manual edits over SSH.
- `sudo fieldrig-unseal` — boot read-write again (for apt upgrades or big
  maintenance); `sudo fieldrig-seal` to re-seal.

If a sealed Pi ever won't boot, pop the SD into a PC and remove `,ro` from
the `/` line in `/etc/fstab` (or restore `/etc/fstab.fieldrig.bak`).

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
- **Bluetooth pairing survives the read-only seal.** BlueZ stores pairing keys
  in `/var/lib/bluetooth`, which is on the sealed root. PAIR MODE briefly
  remounts read-write (same helper as the UPDATE button), lets the key +
  auto-trust land on disk, then re-seals — so you pair a phone once and it
  reconnects every drive without re-pairing. Only pairing needs the write;
  reconnects are read-only. Forgetting a device (REMOVE) is wrapped in the same
  brief write window, so it sticks too.
- **Hidden mouse cursor:** cage draws a pointer at screen centre (a touchscreen
  registers as a pointer device, so it never moves off). Step 5 generates a
  transparent Xcursor theme in `~/.local/share/icons/fieldrig-hidden` and
  exports `XCURSOR_THEME` for cage, so the compositor pointer is invisible;
  CSS `cursor: none` covers the page itself. To apply on an existing install,
  re-run `./05-autostart.sh` and reboot (remount read-write first if sealed:
  `fieldrig-rw`).
- **gpiod caveat:** Pi OS Bookworm ships libgpiod 1.6.x but `gpiod>=2.1` needs
  libgpiod 2.x. If pip fails on gpiod, step 4 will install the rest of the Pi
  extras without it — GPIO ignition sense degrades gracefully.
