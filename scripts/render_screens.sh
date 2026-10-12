#!/usr/bin/env bash
# Renders docs/images/pantallas/pantallas.html to the PNG the README shows.
set -euo pipefail
cd "$(dirname "$0")/.."
chrome="${CHROME:-$(command -v chromium || command -v google-chrome-stable || command -v brave)}"
"$chrome" --headless=new --disable-gpu --hide-scrollbars --allow-file-access-from-files \
  --force-device-scale-factor=2 --window-size=1320,900 --virtual-time-budget=3000 \
  --screenshot="$PWD/docs/images/vinci-pantallas.png" "file://$PWD/docs/images/pantallas/pantallas.html" 2>/dev/null
echo "docs/images/vinci-pantallas.png"
