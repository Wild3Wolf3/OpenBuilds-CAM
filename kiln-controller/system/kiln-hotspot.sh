#!/bin/bash
# If the kiln has no network shortly after boot, start a setup hotspot so
# Wi-Fi can be configured from a phone at http://10.42.0.1
set -u
SSID="Kiln-Setup"
PASS="${KILN_HOTSPOT_PASSWORD:-kilnsetup}"

for _ in $(seq 1 45); do
    if [ "$(nmcli -t -f STATE general 2>/dev/null)" = "connected" ]; then
        exit 0
    fi
    sleep 2
done

echo "No network after 90 s - starting hotspot $SSID"
nmcli connection delete "$SSID" >/dev/null 2>&1 || true
nmcli dev wifi hotspot ifname wlan0 con-name "$SSID" ssid "$SSID" password "$PASS"
nmcli connection modify "$SSID" connection.autoconnect no
