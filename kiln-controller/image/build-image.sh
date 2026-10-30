#!/bin/bash
# Build a flashable Raspberry Pi OS Lite (64-bit) image with the kiln
# controller pre-installed, using the official pi-gen tool in Docker.
#
# Needs: Linux with Docker, git, ~25 GB free disk. On an x86 host also
# qemu-user-static + binfmt-support. An arm64 host (or GitHub's
# ubuntu-24.04-arm runner) builds natively and much faster.
#
# Optional environment variables:
#   KILN_ADMIN_PASSWORD   password for the 'kiln-admin' SSH login (default: kilnadmin - CHANGE IT)
#   KILN_WIFI_SSID        Wi-Fi to join on first boot (else the Kiln-Setup hotspot starts)
#   KILN_WIFI_PASSWORD
#   KILN_WIFI_COUNTRY     two-letter country code (default: US)
#   KILN_HOTSPOT_PASSWORD setup hotspot password (default: kilnsetup)
#   KILN_TIMEZONE         e.g. America/Chicago (default: Etc/UTC)
#   KILN_TOUCHSCREEN      1 = show the UI full-screen on an attached touchscreen (kiosk)
#   KILN_HOSTNAME         default: kiln  (browse to http://kiln.local)
#   PIGEN_REF             pi-gen branch/tag (default: arm64 = latest 64-bit Raspberry Pi OS)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$(cd "$HERE/.." && pwd)"
WORK="${WORK_DIR:-$HERE/build}"
PIGEN_REF="${PIGEN_REF:-arm64}"

if [ -z "${KILN_ADMIN_PASSWORD:-}" ]; then
    echo "WARNING: KILN_ADMIN_PASSWORD not set - using 'kilnadmin'. Change it after first boot (passwd)."
    KILN_ADMIN_PASSWORD=kilnadmin
fi

mkdir -p "$WORK"
if [ ! -d "$WORK/pi-gen" ]; then
    git clone --depth 1 --branch "$PIGEN_REF" https://github.com/RPi-Distro/pi-gen.git "$WORK/pi-gen"
fi
PG="$WORK/pi-gen"

# Our stage goes after stage2 (= Raspberry Pi OS Lite). Only export our image.
rm -rf "$PG/stage-kiln"
cp -r "$HERE/stage-kiln" "$PG/stage-kiln"
touch "$PG/stage2/SKIP_IMAGES"

tar -czf "$PG/stage-kiln/00-kiln/files/kiln-controller.tar.gz" -C "$APP" \
    --exclude=__pycache__ --exclude=image/build kilnctl system install.sh
cat > "$PG/stage-kiln/00-kiln/files/kiln-build.env" <<ENV
KILN_WIFI_SSID=$(printf %q "${KILN_WIFI_SSID:-}")
KILN_WIFI_PASSWORD=$(printf %q "${KILN_WIFI_PASSWORD:-}")
KILN_HOTSPOT_PASSWORD=$(printf %q "${KILN_HOTSPOT_PASSWORD:-}")
KILN_TOUCHSCREEN=$(printf %q "${KILN_TOUCHSCREEN:-0}")
ENV

cat > "$PG/config" <<CFG
IMG_NAME=kiln-controller
RELEASE_NOTES=""
TARGET_HOSTNAME=${KILN_HOSTNAME:-kiln}
FIRST_USER_NAME=kiln-admin
FIRST_USER_PASS=$(printf %q "$KILN_ADMIN_PASSWORD")
DISABLE_FIRST_BOOT_USER_RENAME=1
ENABLE_SSH=1
WPA_COUNTRY=${KILN_WIFI_COUNTRY:-US}
TIMEZONE_DEFAULT=${KILN_TIMEZONE:-Etc/UTC}
LOCALE_DEFAULT=en_US.UTF-8
KEYBOARD_KEYMAP=us
KEYBOARD_LAYOUT="English (US)"
DEPLOY_COMPRESSION=xz
STAGE_LIST="stage0 stage1 stage2 stage-kiln"
CFG

cd "$PG"
CONTINUE="${CONTINUE:-0}" ./build-docker.sh
echo
echo "Image(s):"
ls -lh "$PG"/deploy/*.img.xz
