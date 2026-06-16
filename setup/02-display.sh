#!/usr/bin/env bash
# FieldRig Phase 1 / step 2: fonts for the kiosk.
# Touch targets and UI colors are handled entirely by the web CSS.
# libinput handles the touchscreen digitiser under cage automatically
# once the user is in the seat/input groups from step 1.
set -euo pipefail

echo "==> Installing JetBrains Mono"
sudo apt-get install -y fonts-jetbrains-mono && fc-cache -f \
    || echo "    fonts-jetbrains-mono not found in repos — kiosk will fall back to monospace"

echo "==> Done. Next: ./03-autologin.sh"
