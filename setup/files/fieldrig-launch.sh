#!/usr/bin/env bash
# FieldRig kiosk launcher: wait for the server, then go fullscreen.
# The server itself runs as the fieldrig-server systemd user service.

URL="http://127.0.0.1:8000"

until curl -fsS "$URL/api/state" >/dev/null 2>&1; do
    sleep 0.5
done

exec chromium \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-pinch \
    --overscroll-history-navigation=0 \
    --ozone-platform-hint=auto \
    "$URL"
