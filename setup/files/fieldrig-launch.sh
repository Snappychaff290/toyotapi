#!/usr/bin/env bash
# FieldRig kiosk launcher: wait for the server, then open Chromium fullscreen.
# The server itself runs as the fieldrig-server systemd user service.

URL="http://127.0.0.1:8000"
CHROMIUM=$(command -v chromium || command -v chromium-browser)

# Chromium must write its profile/cache somewhere writable. Under the
# read-only root that lands on tmpfs (XDG_RUNTIME_DIR is /run/user/<uid>,
# falling back to /tmp) so a fresh profile is built each boot.
PROFILE="${XDG_RUNTIME_DIR:-/tmp}/fieldrig-chromium"
mkdir -p "$PROFILE"

until curl -fsS "$URL/api/state" >/dev/null 2>&1; do
    sleep 0.5
done

exec "$CHROMIUM" \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-pinch \
    --overscroll-history-navigation=0 \
    --ozone-platform=wayland \
    --user-data-dir="$PROFILE" \
    --disk-cache-dir="$PROFILE/cache" \
    "$URL"
