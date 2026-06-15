#!/usr/bin/env bash
# FieldRig Phase 1 / step 1: system packages and services.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Installing packages"
sudo pacman -Syu --needed --noconfirm \
    python python-pip git base-devel curl \
    pipewire pipewire-audio pipewire-alsa pipewire-pulse wireplumber \
    bluez bluez-utils \
    chromium konsole ttf-jetbrains-mono \
    maliit-keyboard \
    portaudio

echo "==> Enabling Bluetooth"
sudo systemctl enable --now bluetooth.service

echo "==> Enabling PipeWire user services"
systemctl --user enable --now pipewire wireplumber pipewire-pulse || true

echo "==> Installing mpris-proxy user service (phone media over Bluetooth)"
mkdir -p ~/.config/systemd/user
cp files/mpris-proxy.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable mpris-proxy.service

echo "==> Creating /var/log/fieldrig"
sudo mkdir -p /var/log/fieldrig
sudo chown "$USER" /var/log/fieldrig

echo "==> Done. Next: ./02-kde-touch.sh"
