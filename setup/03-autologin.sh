#!/usr/bin/env bash
# FieldRig Phase 1 / step 3: SDDM autologin straight into Plasma.
# Usage: ./03-autologin.sh [username]   (defaults to current user)
set -euo pipefail

USER_NAME="${1:-$USER}"

echo "==> Enabling autologin for ${USER_NAME}"
sudo mkdir -p /etc/sddm.conf.d
sudo tee /etc/sddm.conf.d/10-fieldrig-autologin.conf >/dev/null <<EOF
[Autologin]
User=${USER_NAME}
Session=plasma.desktop
Relogin=true
EOF

echo "==> Done. Next: ./04-python-env.sh"
