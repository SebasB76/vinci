#!/usr/bin/env bash
# Puts Hermes back on its own bridge.js and removes every file install.sh added.
set -euo pipefail

BRIDGE_DIR="${BRIDGE_DIR:-$HOME/.hermes/hermes-agent/scripts/whatsapp-bridge}"
CONFIG="${HERMES_CONFIG:-$HOME/.hermes/config.yaml}"

sed -i '/# webview-experiment$/d' "$CONFIG"
rm -f "$BRIDGE_DIR/bridge.webview-experiment.js" "$BRIDGE_DIR/webview_route.js" \
      "$BRIDGE_DIR/webview_variants.js" "$BRIDGE_DIR/webview_experiment.json"
echo "Removed. Restart the gateway: systemctl --user restart hermes-gateway"
