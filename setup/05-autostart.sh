#!/usr/bin/env bash
# FieldRig Phase 1 / step 5: boot into the app automatically.
# Installs the fieldrig-server user service and wires cage into ~/.bash_profile
# so it fires on tty1 console autologin.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Installing server user service"
mkdir -p "$HOME/.config/systemd/user"
cp files/fieldrig-server.service "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable fieldrig-server.service

echo "==> Installing kiosk launcher to ~/.local/bin/fieldrig-launch"
install -Dm755 files/fieldrig-launch.sh "$HOME/.local/bin/fieldrig-launch"

echo "==> Adding cage kiosk to ~/.bash_profile (tty1 autologin hook)"
PROFILE="$HOME/.bash_profile"
MARKER="# FieldRig kiosk"

if grep -q "$MARKER" "$PROFILE" 2>/dev/null; then
    echo "    Already present in $PROFILE, skipping."
else
    cat >> "$PROFILE" <<'EOF'

# FieldRig kiosk — launches cage+Chromium on tty1 autologin
if [ -z "$WAYLAND_DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    exec cage -- "$HOME/.local/bin/fieldrig-launch"
fi
EOF
    echo "    Written to $PROFILE"
fi

echo "==> Done. Reboot to test: ignition on -> FieldRig fullscreen."
