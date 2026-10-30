#!/bin/bash
# Full-screen browser showing the kiln UI on an attached touchscreen.
# Started by kiln-kiosk.service inside the 'cage' Wayland kiosk compositor.
URL="${KILN_KIOSK_URL:-http://localhost/?kiosk=1}"
BROWSER=$(command -v chromium || command -v chromium-browser)

# Wait for the controller's web server so the screen never shows an error page.
for _ in $(seq 1 60); do
    curl -fs -o /dev/null "${URL%%\?*}api/auth" && break
    sleep 1
done

exec "$BROWSER" --kiosk "$URL" \
    --ozone-platform=wayland --noerrdialogs --disable-infobars --no-first-run \
    --disable-session-crashed-bubble --disable-features=Translate,TouchpadOverscrollHistoryNavigation \
    --overscroll-history-navigation=0 --disable-pinch --password-store=basic \
    --check-for-update-interval=31536000 --user-data-dir=/var/lib/kiln-kiosk/chromium
