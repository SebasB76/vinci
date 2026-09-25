#!/usr/bin/env bash
# Instala o actualiza el bot académico de ESPOL. Puedes correrlo las veces que quieras.
#
#   ./setup.sh              instala dependencias, el comando `aula`, la skill de Claude Code
#                           y el perfil de Hermes; luego prueba Canvas y Telegram
#   ./setup.sh --skip-deps  no toca el entorno de Python (.venv ya listo)
#   ./setup.sh --sin-pruebas  no consulta Canvas ni envía el mensaje de prueba
#
# Qué modifica fuera de esta carpeta (y nada más):
#   ~/.hermes/profiles/<perfil>/   el perfil propio del bot (nunca el perfil por defecto)
#   ~/.local/bin/<perfil>          el alias que Hermes crea para ese perfil
#   ~/.local/bin/aula              el comando `aula`
#   ~/.claude/skills/aula/         la skill para Claude Code
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SKIP_DEPS=0
RUN_CHECKS=1
for arg in "$@"; do
  case "$arg" in
    --skip-deps) SKIP_DEPS=1 ;;
    --sin-pruebas) RUN_CHECKS=0 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "Opción desconocida: $arg" >&2; exit 2 ;;
  esac
done

MARKER="Generado por setup.sh de espol-academic-bot"
SECRETS="${AULA_SECRETS:-$REPO/secrets.env}"
VENV="$REPO/.venv"
say() { printf '\n==> %s\n' "$*"; }

say "Revisando requisitos"
command -v python3 >/dev/null || { echo "Falta python3 (sudo pacman -S python)" >&2; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || { echo "Necesitas Python 3.11 o más nuevo" >&2; exit 1; }
HERMES_BIN="${HERMES_BIN:-$HOME/.local/bin/hermes}"
[ -x "$HERMES_BIN" ] || { echo "No encuentro Hermes Agent en $HERMES_BIN" >&2; exit 1; }
echo "python3 $(python3 -c 'import platform; print(platform.python_version())') · $("$HERMES_BIN" --version 2>/dev/null | head -1)"

if [ "$SKIP_DEPS" = 0 ]; then
  say "Instalando dependencias de Python en .venv"
  if command -v uv >/dev/null; then
    (cd "$REPO" && uv sync --quiet)
  else
    [ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet -e "$REPO"
  fi
fi
[ -x "$VENV/bin/aula" ] && [ -x "$VENV/bin/espol-bot" ] \
  || { echo "Falta el entorno .venv; corre ./setup.sh sin --skip-deps" >&2; exit 1; }

say "Revisando secretos ($SECRETS)"
if [ ! -f "$SECRETS" ]; then
  cp "$REPO/secrets.env.example" "$SECRETS"
  chmod 600 "$SECRETS"
  echo "Creé $SECRETS a partir de la plantilla."
  echo "Complétalo (mira el README: token de Canvas, bot de Telegram y tu ID) y vuelve a correr ./setup.sh"
  exit 1
fi
chmod 600 "$SECRETS"
missing=""
for key in CANVAS_TOKEN TELEGRAM_BOT_TOKEN TELEGRAM_USER_ID; do
  grep -Eq "^${key}=.+" "$SECRETS" || missing="$missing $key"
done
[ -z "$missing" ] || { echo "Faltan valores en $SECRETS:$missing" >&2; exit 1; }
echo "secrets.env completo (permisos 600)"

say "Instalando el comando aula en ~/.local/bin"
mkdir -p "$HOME/.local/bin"
AULA_WRAPPER="$HOME/.local/bin/aula"
if [ -e "$AULA_WRAPPER" ] && ! grep -q "$MARKER" "$AULA_WRAPPER" 2>/dev/null; then
  echo "⚠ $AULA_WRAPPER ya existe y no es de este proyecto: no lo toco."
else
  new_wrapper="$(cat <<EOF
#!/usr/bin/env bash
# $MARKER. Vuelve a correr setup.sh para actualizarlo.
export AULA_CONFIG="\${AULA_CONFIG:-${AULA_CONFIG:-$REPO/config.toml}}"
export AULA_SECRETS="\${AULA_SECRETS:-$SECRETS}"
exec '$VENV/bin/aula' "\$@"
EOF
)"
  if [ "$(cat "$AULA_WRAPPER" 2>/dev/null)" != "$new_wrapper" ]; then
    printf '%s\n' "$new_wrapper" > "$AULA_WRAPPER"
    chmod 755 "$AULA_WRAPPER"
    echo "aula instalado en $AULA_WRAPPER"
  else
    echo "aula ya estaba instalado"
  fi
  case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "⚠ Agrega ~/.local/bin a tu PATH para usar 'aula'.";; esac
fi

say "Instalando la skill de Claude Code en ~/.claude/skills/aula"
SKILL_DIR="$HOME/.claude/skills/aula"
if [ -e "$SKILL_DIR/SKILL.md" ] && ! grep -q "espol-academic-bot" "$SKILL_DIR/SKILL.md"; then
  echo "⚠ $SKILL_DIR ya existe y no es de este proyecto: no lo toco."
elif cmp -s "$REPO/claude/skills/aula/SKILL.md" "$SKILL_DIR/SKILL.md"; then
  echo "La skill ya estaba al día"
else
  mkdir -p "$SKILL_DIR"
  cp "$REPO/claude/skills/aula/SKILL.md" "$SKILL_DIR/SKILL.md"
  echo "Skill instalada: cualquier sesión de Claude Code en tu PC puede usar 'aula'"
fi

say "Configurando el perfil de Hermes del bot"
AULA_SECRETS="$SECRETS" "$VENV/bin/espol-bot" hermes-perfil --hermes "$HERMES_BIN"

if [ "$RUN_CHECKS" = 1 ]; then
  say "Probando el acceso al aula virtual (solo lectura)"
  if AULA_SECRETS="$SECRETS" "$VENV/bin/aula" cursos --actualizar; then
    echo "✓ Canvas responde"
  else
    echo "⚠ No pude leer el aula virtual; revisa CANVAS_TOKEN en $SECRETS" >&2
  fi
  say "Enviando un mensaje de prueba a tu Telegram"
  AULA_SECRETS="$SECRETS" "$VENV/bin/espol-bot" probar \
    || echo "⚠ Telegram no aceptó el mensaje; revisa TELEGRAM_BOT_TOKEN y que le hayas escrito /start a tu bot" >&2
fi

PROFILE="$("$VENV/bin/python" -c 'from espol_bot.config import load_bot_config; print(load_bot_config().hermes_profile)')"
cat <<EOF

Listo. Para encender el bot (queda corriendo en segundo plano y arranca con tu sesión):
  $PROFILE gateway install     # una sola vez: crea el servicio hermes-gateway-$PROFILE
  $PROFILE gateway start
Para apagarlo:        $PROFILE gateway stop
Ver si está vivo:     $PROFILE gateway status   ·   $PROFILE cron list
(Si el alias '$PROFILE' no está en tu PATH, usa: hermes -p $PROFILE gateway start)
EOF
