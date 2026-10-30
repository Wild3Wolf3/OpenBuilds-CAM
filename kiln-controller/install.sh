#!/bin/bash
# Install the kiln controller on Raspberry Pi OS (Bookworm or newer, Lite is fine).
#
#   sudo ./install.sh                 install on a running Pi and start it
#   sudo ./install.sh --touchscreen   also show the UI full-screen on an attached touchscreen
#   sudo ./install.sh --image         used by the image builder (chroot, no start)
set -euo pipefail

IMAGE=0
TOUCH=0
for arg in "$@"; do
    case "$arg" in
        --image) IMAGE=1 ;;
        --touchscreen) TOUCH=1 ;;
        *) echo "unknown option: $arg"; exit 1 ;;
    esac
done
[ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST=/opt/kiln-controller

echo "==> Installing packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
    python3 python3-aiohttp python3-spidev python3-gpiozero python3-lgpio \
    network-manager avahi-daemon policykit-1 || \
apt-get install -y --no-install-recommends \
    python3 python3-aiohttp python3-spidev python3-gpiozero python3-lgpio \
    network-manager avahi-daemon polkitd
# Camera support (Pi camera modules). Not fatal if unavailable.
apt-get install -y --no-install-recommends python3-picamera2 || \
    echo "warning: python3-picamera2 not installed - camera disabled"

echo "==> Creating service user"
id kiln >/dev/null 2>&1 || useradd --system --home-dir /var/lib/kiln --shell /usr/sbin/nologin kiln
for g in gpio spi video netdev; do
    getent group "$g" >/dev/null && usermod -aG "$g" kiln
done

echo "==> Copying application to $DEST"
rm -rf "$DEST"
install -d "$DEST"
cp -r "$SRC/kilnctl" "$DEST/"
find "$DEST" -name __pycache__ -prune -exec rm -rf {} +
install -d -o kiln -g kiln /var/lib/kiln

echo "==> Installing system services"
install -m 644 "$SRC/system/kiln-controller.service" /etc/systemd/system/
install -m 644 "$SRC/system/kiln-hotspot.service" /etc/systemd/system/
install -m 755 "$SRC/system/kiln-hotspot.sh" /usr/local/sbin/
install -d /etc/polkit-1/rules.d
install -m 644 "$SRC/system/50-kiln-networkmanager.rules" /etc/polkit-1/rules.d/
install -d /etc/systemd/system.conf.d
install -m 644 "$SRC/system/kiln-watchdog.conf" /etc/systemd/system.conf.d/

echo "==> Enabling SPI and the hardware watchdog"
BOOTCFG=/boot/firmware/config.txt
[ -f "$BOOTCFG" ] || BOOTCFG=/boot/config.txt
if [ -f "$BOOTCFG" ]; then
    grep -q '^dtparam=spi=on' "$BOOTCFG" || echo 'dtparam=spi=on' >> "$BOOTCFG"
    grep -q '^dtparam=watchdog=on' "$BOOTCFG" || echo 'dtparam=watchdog=on' >> "$BOOTCFG"
else
    echo "warning: config.txt not found - enable SPI with raspi-config"
fi

systemctl enable kiln-controller.service kiln-hotspot.service avahi-daemon.service NetworkManager.service

if [ "$TOUCH" = 1 ]; then
    echo "==> Installing touchscreen kiosk"
    apt-get install -y --no-install-recommends cage curl fonts-dejavu-core chromium || \
        apt-get install -y --no-install-recommends cage curl fonts-dejavu-core chromium-browser
    id kiosk >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/kiln-kiosk --shell /usr/sbin/nologin kiosk
    for g in video render input tty; do
        getent group "$g" >/dev/null && usermod -aG "$g" kiosk
    done
    install -m 755 "$SRC/system/kiln-kiosk.sh" /usr/local/sbin/
    install -m 644 "$SRC/system/kiln-kiosk.service" /etc/systemd/system/
    systemctl enable kiln-kiosk.service
    systemctl set-default graphical.target
fi

if [ "$IMAGE" = 0 ]; then
    systemctl daemon-reload
    systemctl restart kiln-controller.service
    [ "$TOUCH" = 1 ] && systemctl restart kiln-kiosk.service
    echo
    echo "Done. Open http://$(hostname).local (reboot first if SPI was just enabled)."
fi
