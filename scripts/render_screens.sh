#!/usr/bin/env bash
# Renders docs/images/pantallas/pantallas.html, the README's animated demo, to docs/images/vinci-demo.webp
# (an animated WebP: under 1 MB, where the same GIF weighs 6 MB), and docs/images/video/video.html, the video Vinci
# sends with its invitation, to docs/images/vinci-video.mp4 (1080×1920, H.264, what WhatsApp plays inline).
# Only the video: ./scripts/render_screens.sh video
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
if [ "${1:-}" != video ]; then
  mkdir "$work/frames"
  node scripts/render_demo.mjs "$port" "file://$PWD/docs/images/pantallas/pantallas.html" "$work/frames" "$fps"
  ffmpeg -v error -y -framerate "$fps" -i "$work/frames/%04d.png" -vf "scale=1200:-1:flags=lanczos" \
    -c:v libwebp_anim -lossless 0 -quality 90 -compression_level 6 -loop 0 docs/images/vinci-demo.webp
  ls -lh docs/images/vinci-demo.webp | awk '{print $NF, $5}'
fi
mkdir "$work/video"
node scripts/render_demo.mjs "$port" "file://$PWD/docs/images/video/video.html" "$work/video" 30 540 960
# A silent track: some phones treat a video with no audio as a GIF.
ffmpeg -v error -y -framerate 30 -i "$work/video/%04d.png" -f lavfi -i anullsrc=r=44100:cl=stereo -shortest \
  -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p -profile:v high -movflags +faststart -c:a aac -b:a 32k \
  docs/images/vinci-video.mp4
ls -lh docs/images/vinci-video.mp4 | awk '{print $NF, $5}'
