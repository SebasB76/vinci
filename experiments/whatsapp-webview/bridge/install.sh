#!/usr/bin/env bash
# Installs the experiment's bridge route next to Hermes' bridge without editing bridge.js:
# the gateway runs a copy (bridge.webview-experiment.js) through the whatsapp.bridge_script setting.
# Usage: install.sh <recipient number with country code>. Undo: uninstall.sh.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BRIDGE_DIR="${BRIDGE_DIR:-$HOME/.hermes/hermes-agent/scripts/whatsapp-bridge}"
CONFIG="${HERMES_CONFIG:-$HOME/.hermes/config.yaml}"
COPY="$BRIDGE_DIR/bridge.webview-experiment.js"
MARK="# webview-experiment"

number="${1:?usage: install.sh <recipient number with country code>}"
number="${number//[^0-9]/}"

grep -q "^// Health check$" "$BRIDGE_DIR/bridge.js" || { echo "bridge.js changed: no '// Health check' anchor" >&2; exit 1; }

cp "$HERE/webview_variants.js" "$HERE/webview_route.js" "$BRIDGE_DIR/"
printf '{"allowedChat": "%s@s.whatsapp.net"}\n' "$number" > "$BRIDGE_DIR/webview_experiment.json"
chmod 600 "$BRIDGE_DIR/webview_experiment.json"

# An import and a call before the health route; everything else is bridge.js as it is on disk today.
awk '
  /^\/\/ Health check$/ {
    print "registerWebviewExperiment(app, { getSock: () => sock, isConnected: () => !!sock && connectionState === \"connected\", enqueueSend, trackSentMessageId, messageStore, timeoutMs: SEND_TIMEOUT_MS });"
    print ""
  }
  { print }
' "$BRIDGE_DIR/bridge.js" | sed "0,/^import /s//import { registerWebviewExperiment } from '.\/webview_route.js';\nimport /" > "$COPY"

if ! grep -q "$MARK\$" "$CONFIG"; then
  cp "$CONFIG" "$CONFIG.before-webview-experiment"
  sed -i '/^  bridge_script: /d' "$CONFIG"  # Vinci's own launcher, which setup.sh puts back
  sed -i "/^whatsapp:\$/a\\  bridge_script: $COPY  $MARK" "$CONFIG"
fi
echo "Installed. Restart the gateway: systemctl --user restart hermes-gateway"
