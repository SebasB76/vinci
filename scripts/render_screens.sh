#!/usr/bin/env bash
# Renders docs/images/pantallas/pantallas.html, the README's animated demo, to docs/images/vinci-demo.webp
# (an animated WebP: under 1 MB, where the same GIF weighs 6 MB).
# Needs Chromium (or Chrome/Brave), Node and ffmpeg.
set -euo pipefail
cd "$(dirname "$0")/.."
chrome="${CHROME:-$(command -v chromium || command -v google-chrome-stable || command -v brave)}"
fps=12
port=9333
work="$(mktemp -d)"
"$chrome" --headless=new --disable-gpu --hide-scrollbars --allow-file-access-from-files --user-data-dir="$work/profile" \
  --remote-debugging-port="$port" about:blank 2>/dev/null &
chrome_pid=$!
trap 'kill "$chrome_pid" 2>/dev/null; rm -rf "$work"' EXIT
until curl -sf "http://127.0.0.1:$port/json/version" >/dev/null; do sleep 0.2; done
mkdir "$work/frames"
node scripts/render_demo.mjs "$port" "file://$PWD/docs/images/pantallas/pantallas.html" "$work/frames" "$fps"
ffmpeg -v error -y -framerate "$fps" -i "$work/frames/%04d.png" -vf "scale=1200:-1:flags=lanczos" \
  -c:v libwebp_anim -lossless 0 -quality 90 -compression_level 6 -loop 0 docs/images/vinci-demo.webp
ls -lh docs/images/vinci-demo.webp | awk '{print $NF, $5}'
