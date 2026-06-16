#!/usr/bin/env bash
# FieldRig Phase 1 / step 3: console autologin on tty1 (no display manager).
# Usage: ./03-autologin.sh [username]   (defaults to current user)
set -euo pipefail

USER_NAME="${1:-$USER}"

echo "==> Enabling console autologin for ${USER_NAME} on tty1"
sudo mkdir -p /etc/systemd/system/getty@tty1.service.d
sudo tee /etc/systemd/system/getty@tty1.service.d/autologin.conf >/dev/null <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin ${USER_NAME} --noclear %I \$TERM
EOF

sudo systemctl daemon-reload

echo "==> Done. Next: ./04-python-env.sh"
