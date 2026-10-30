#!/bin/bash -e
# Runs on the build host. Copies the app into the image and, if requested,
# pre-configures Wi-Fi.
. files/kiln-build.env

install -d "${ROOTFS_DIR}/opt/kiln-src"
tar -xzf files/kiln-controller.tar.gz -C "${ROOTFS_DIR}/opt/kiln-src"

if [ -n "${KILN_WIFI_SSID:-}" ]; then
    conn="${ROOTFS_DIR}/etc/NetworkManager/system-connections/kiln-wifi.nmconnection"
    install -d -m 700 "$(dirname "$conn")"
    cat > "$conn" <<NM
[connection]
id=kiln-wifi
type=wifi
autoconnect=true

[wifi]
mode=infrastructure
ssid=${KILN_WIFI_SSID}

[wifi-security]
key-mgmt=wpa-psk
psk=${KILN_WIFI_PASSWORD}

[ipv4]
method=auto

[ipv6]
method=auto
NM
    chmod 600 "$conn"
fi

if [ -n "${KILN_HOTSPOT_PASSWORD:-}" ]; then
    echo "KILN_HOTSPOT_PASSWORD=${KILN_HOTSPOT_PASSWORD}" > "${ROOTFS_DIR}/etc/default/kiln-hotspot"
    chmod 600 "${ROOTFS_DIR}/etc/default/kiln-hotspot"
fi
