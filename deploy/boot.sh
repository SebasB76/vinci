#!/bin/bash
# Prepares Vinci on every container start, as the hermes user (deploy/cont-init.sh): what setup.sh does on a PC.
set -uo pipefail
export HOME=/opt/data
VINCI=/opt/vinci
BOT="$VINCI/.venv/bin/espol-bot"
say() { echo "[vinci] $*"; }

mkdir -p "$(dirname "$AULA_CONFIG")"
if [ ! -f "$AULA_CONFIG" ]; then
  # The repo's config.toml, with its data inside the volume and no notes folder (it lives on the captain's PC).
  sed -e 's|^carpeta_datos = .*|carpeta_datos = "/opt/data/vinci/datos"|' \
      -e 's|^folder = .*|folder = ""|' "$VINCI/config.toml" > "$AULA_CONFIG"
  say "created $AULA_CONFIG"
fi
[ -n "${VINCI_PROVIDER:-}" ] && sed -i "s|^proveedor = .*|proveedor = \"$VINCI_PROVIDER\"|" "$AULA_CONFIG"
[ -n "${VINCI_MODEL:-}" ] && sed -i "s|^modelo = .*|modelo = \"$VINCI_MODEL\"|" "$AULA_CONFIG"

# Coolify's variables only fill keys secrets.env lacks: Vinci renews CANVAS_TOKEN and stores each subject bot's
# token there itself, so a restart must never bring an old value back.
"$VINCI/.venv/bin/python" - "$VINCI/secrets.env.example" <<'EOF'
import os, sys
from pathlib import Path
from aula_core.config import load_secret_values, parse_env_file, secrets_path, update_secret_values

path = secrets_path()
current = load_secret_values(path) if path.exists() else {}
wanted = {key: os.environ[key] for key in parse_env_file(Path(sys.argv[1]))
          if os.environ.get(key) and not current.get(key)}
if wanted or not path.exists():
    update_secret_values(wanted, path=path)
    print(f"[vinci] secrets.env: filled {', '.join(sorted(wanted)) or 'nothing'} from the environment")
EOF

# Hermes mirrors its read-only bridge to the volume once and then keeps that copy: refresh it from the image.
rm -rf /opt/data/scripts/whatsapp-bridge
mkdir -p /opt/data/scripts && cp -a /opt/hermes/scripts/whatsapp-bridge /opt/data/scripts/

if "$BOT" hermes-perfil; then
  say "profiles ready"
else
  say "hermes-perfil failed: Vinci starts without its profiles until the cause is fixed and the container restarts"
fi
