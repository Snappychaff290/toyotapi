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

echo "==> Generating transparent cursor theme (hides the kiosk pointer)"
# cage draws its own mouse pointer at screen centre (a touchscreen counts as a
# pointer device, so it never moves away). CSS cursor:none only hides it over
# the page; the compositor pointer needs a transparent cursor theme. We cover
# two cases because cage versions differ: (1) it honours XCURSOR_THEME (set in
# .bash_profile below); (2) it asks wlroots for the "default" theme and ignores
# the env -- so we also make "default" inherit the transparent theme. Both are
# installed in the two icon search paths. Lives in home, survives the seal.
for base in "$HOME/.local/share/icons" "$HOME/.icons"; do
    python3 files/make-blank-cursor.py "$base/fieldrig-hidden"
    mkdir -p "$base/default"
    cat > "$base/default/index.theme" <<'THEME'
[Icon Theme]
Name=Default
Comment=FieldRig: redirect the default cursor to the transparent theme
Inherits=fieldrig-hidden
THEME
done

echo "==> Adding cage kiosk to ~/.bash_profile (tty1 autologin hook)"
PROFILE="$HOME/.bash_profile"
BEGIN="# >>> FieldRig kiosk >>>"
END="# <<< FieldRig kiosk <<<"
touch "$PROFILE"

# Drop any previous block (current BEGIN/END region or the older single-marker
# version) so re-running setup updates the launch hook in place.
tmp="$(mktemp)"
awk '
    /^# >>> FieldRig kiosk >>>/  { skip=1 }
    /^# FieldRig kiosk/          { skip=1; legacy=1 }
    skip==0 { print }
    /^# <<< FieldRig kiosk <<</  { skip=0 }
    legacy && $0=="fi"          { skip=0; legacy=0 }
' "$PROFILE" > "$tmp" && mv "$tmp" "$PROFILE"

cat >> "$PROFILE" <<EOF

$BEGIN
# launches cage+Chromium on tty1 autologin. XCURSOR_THEME must be set for the
# cage process (it draws the pointer), so it's exported here, not in the
# launcher Chromium runs from.
if [ -z "\$WAYLAND_DISPLAY" ] && [ "\$(tty)" = "/dev/tty1" ]; then
    export XCURSOR_THEME=fieldrig-hidden
    export XCURSOR_SIZE=24
    exec cage -- "\$HOME/.local/bin/fieldrig-launch"
fi
$END
EOF
echo "    Updated $PROFILE"

echo "==> Done. Reboot to test: ignition on -> FieldRig fullscreen."
