#!/bin/bash -e
# Runs inside the image.
bash /opt/kiln-src/install.sh --image
rm -rf /opt/kiln-src
