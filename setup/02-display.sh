#!/usr/bin/env bash
# FieldRig Phase 1 / step 2: KDE Plasma touch optimizations.
# Bigger fonts, bigger cursor, single-click, virtual keyboard, taller panel.
set -euo pipefail

echo "==> Fonts (JetBrains Mono, scaled up for the 10.1in screen)"
kwriteconfig6 --file kdeglobals --group General --key font "JetBrains Mono,12,-1,5,50,0,0,0,0,0"
kwriteconfig6 --file kdeglobals --group General --key fixed "JetBrains Mono,12,-1,5,50,0,0,0,0,0"
kwriteconfig6 --file kdeglobals --group General --key menuFont "JetBrains Mono,12,-1,5,50,0,0,0,0,0"
kwriteconfig6 --file kdeglobals --group General --key toolBarFont "JetBrains Mono,11,-1,5,50,0,0,0,0,0"

echo "==> Touch behavior"
kwriteconfig6 --file kdeglobals --group KDE --key SingleClick true
kwriteconfig6 --file kcminputrc --group Mouse --key cursorSize 36

echo "==> Virtual keyboard (maliit) under Wayland"
kwriteconfig6 --file kwinrc --group Wayland --key InputMethod \
    /usr/share/applications/com.github.maliit.keyboard.desktop
kwriteconfig6 --file kwinrc --group Wayland --key VirtualKeyboardEnabled true

echo "==> Taller panel for finger targets"
qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript \
    'panels().forEach(function(p){ p.height = 60; });' \
    || echo "    (plasmashell not running; panel height will need a logged-in session)"

echo "==> Done. Log out/in (or reboot) to apply. Next: ./03-autologin.sh"
