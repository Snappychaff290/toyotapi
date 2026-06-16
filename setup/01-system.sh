#!/usr/bin/env bash
# FieldRig Phase 1 / step 1: system packages and services.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Updating system"
sudo apt-get update && sudo apt-get full-upgrade -y

echo "==> Installing packages"
sudo apt-get install -y \
    python3 python3-venv python3-pip python3-dev \
    git build-essential curl \
    pipewire pipewire-audio pipewire-alsa pipewire-pulse wireplumber \
    bluez \
    chromium cage seatd \
    portaudio19-dev libgpiod-dev gpiod \
    fonts-jetbrains-mono

echo "==> Creating seat group and enabling seatd"
sudo groupadd -r seat 2>/dev/null || true
sudo systemctl enable --now seatd

echo "==> Enabling Bluetooth"
sudo systemctl enable --now bluetooth

echo "==> Adding $USER to hardware groups"
sudo usermod -aG seat,video,input,render,bluetooth "$USER"

echo "==> Enabling linger so user services survive without an active login"
sudo loginctl enable-linger "$USER"

echo "==> Enabling PipeWire user services"
systemctl --user enable --now pipewire wireplumber pipewire-pulse || true

echo "==> Installing mpris-proxy user service"
mkdir -p ~/.config/systemd/user
cp files/mpris-proxy.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable mpris-proxy.service

echo "==> Creating /var/log/fieldrig"
sudo mkdir -p /var/log/fieldrig
sudo chown "$USER" /var/log/fieldrig

echo "==> Done. Log out and back in for group changes, then: ./02-display.sh"
