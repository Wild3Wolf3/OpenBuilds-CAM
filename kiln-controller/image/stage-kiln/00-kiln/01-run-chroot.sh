#!/bin/bash -e
# Runs inside the image.
if [ -f /opt/kiln-src/.touchscreen ]; then
    bash /opt/kiln-src/install.sh --image --touchscreen
else
    bash /opt/kiln-src/install.sh --image
fi
rm -rf /opt/kiln-src
