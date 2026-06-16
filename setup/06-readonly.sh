#!/usr/bin/env bash
# FieldRig Phase 1 / step 6: read-only root filesystem.
#
# A car stereo loses power the instant the ignition is cut, so the SD card
# must never be mid-write — otherwise it corrupts (the "error code 7" kernel
# loss). This seals root + boot read-only and routes all runtime writes to
# tmpfs (RAM). The in-app UPDATE button and the fieldrig-rw/fieldrig-ro
# helpers briefly remount read-write to persist changes.
#
# Re-runnable. Run WITHOUT --seal to install the tooling but stay writable
# (useful while still setting things up); run with --seal (the default from
# install.sh) to also seal read-only and reboot.
set -euo pipefail
cd "$(dirname "$0")"

SEAL=1
[ "${1:-}" = "--no-seal" ] && SEAL=0
USER_NAME="${SUDO_USER:-$USER}"

echo "==> Installing remount helper, toggles, and sudoers rule"
sudo install -Dm755 files/fieldrig-mount  /usr/local/sbin/fieldrig-mount
sudo install -Dm755 files/fieldrig-seal   /usr/local/sbin/fieldrig-seal
sudo install -Dm755 files/fieldrig-unseal /usr/local/sbin/fieldrig-unseal
sudo install -Dm755 files/fieldrig-rw     /usr/local/bin/fieldrig-rw
sudo install -Dm755 files/fieldrig-ro     /usr/local/bin/fieldrig-ro
sudo install -Dm755 files/fieldrig-status /usr/local/bin/fieldrig-status

sed "s/%USER%/${USER_NAME}/" files/fieldrig.sudoers > /tmp/fieldrig.sudoers
sudo install -Dm440 /tmp/fieldrig.sudoers /etc/sudoers.d/fieldrig
rm -f /tmp/fieldrig.sudoers
sudo visudo -cf /etc/sudoers.d/fieldrig

echo "==> Routing volatile paths to tmpfs (RAM)"
sudo cp /etc/fstab /etc/fstab.fieldrig.bak
MARK="# FieldRig read-only tmpfs"
if ! grep -qF "$MARK" /etc/fstab; then
    sudo tee -a /etc/fstab >/dev/null <<EOF

$MARK
tmpfs /tmp     tmpfs nosuid,nodev,mode=1777 0 0
tmpfs /var/tmp tmpfs nosuid,nodev,mode=1777 0 0
tmpfs /var/log tmpfs nosuid,nodev,mode=0755 0 0
EOF
fi

if [ "$SEAL" -eq 1 ]; then
    echo "==> Sealing root + boot read-only (will reboot)"
    sudo /usr/local/sbin/fieldrig-seal --no-reboot
    echo "==> Done. Read-only after reboot. UPDATE button toggles writes."
else
    echo "==> Tooling installed; filesystem left WRITABLE."
    echo "    Seal it when ready with:  sudo fieldrig-seal"
fi
