#!/usr/bin/env bash
# Instala o actualiza Vinci y tus bots de materia. Puedes correrlo las veces que quieras.
#
#   ./setup.sh              instala dependencias, los comandos `aula` y `vinci-equipo`, la skill
#                           de Claude Code y los perfiles de Hermes; luego prueba Canvas y Telegram
#   ./setup.sh --skip-deps  no toca el entorno de Python (.venv ya listo)
#   ./setup.sh --sin-pruebas  no consulta Canvas ni envía el mensaje de prueba
#
# Qué modifica fuera de esta carpeta (y nada más):
#   ~/.hermes/profiles/vinci/          el perfil de Vinci (nunca el perfil por defecto)
#   ~/.hermes/profiles/vinci-<código>/ un perfil por cada bot de materia ya registrado
#   ~/.local/bin/vinci                 el alias que Hermes crea para el perfil de Vinci
#   ~/.local/bin/aula                  el comando `aula`
#   ~/.local/bin/vinci-equipo          el comando para ver o archivar el equipo desde la terminal
#   ~/.claude/skills/aula/             la skill para Claude Code
# Y, solo si le falta, el conector de Telegram de Hermes (`hermes pm install --extra telegram`).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SKIP_DEPS=0
RUN_CHECKS=1
for arg in "$@"; do
  case "$arg" in
    --skip-deps) SKIP_DEPS=1 ;;
    --sin-pruebas) RUN_CHECKS=0 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
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
[ -x "$VENV/bin/aula" ] && [ -x "$VENV/bin/espol-bot" ] && [ -x "$VENV/bin/vinci-equipo" ] \
  || { echo "Falta el entorno .venv; corre ./setup.sh sin --skip-deps" >&2; exit 1; }

say "Revisando el conector de Telegram de Hermes"
# Vinci y los bots de materia conversan por el gateway de Hermes, que necesita python-telegram-bot.
hermes_has_telegram() {
  local py
  py="$(dirname "$(realpath "$HERMES_BIN")")/python3"
  if [ -x "$py" ] && "$py" -c 'import telegram' >/dev/null 2>&1; then return 0; fi
  "$HERMES_BIN" --run-module telegram >/dev/null 2>&1
}
if hermes_has_telegram; then
  echo "Hermes ya tiene el conector de Telegram"
elif [ "${ESPOL_NO_PM_INSTALL:-0}" = 1 ]; then
  echo "⚠ A Hermes le falta el conector de Telegram. Instálalo con: hermes pm install --extra telegram" >&2
else
  echo "A Hermes le falta el conector de Telegram; lo instalo (hermes pm install --extra telegram)…"
  "$HERMES_BIN" pm install --extra telegram
  hermes_has_telegram || { echo "No pude instalar el conector de Telegram de Hermes" >&2; exit 1; }
fi

say "Revisando secretos ($SECRETS)"
if [ ! -f "$SECRETS" ]; then
  cp "$REPO/secrets.env.example" "$SECRETS"
  chmod 600 "$SECRETS"
  echo "Creé $SECRETS a partir de la plantilla."
  echo "Complétalo (mira el README: token de Canvas, el bot de Vinci y tu ID) y vuelve a correr ./setup.sh"
  exit 1
fi
chmod 600 "$SECRETS"
missing=""
for key in CANVAS_TOKEN TELEGRAM_BOT_TOKEN TELEGRAM_USER_ID; do
  grep -Eq "^${key}=.+" "$SECRETS" || missing="$missing $key"
done
[ -z "$missing" ] || { echo "Faltan valores en $SECRETS:$missing" >&2; exit 1; }
echo "secrets.env completo (permisos 600)"

# install_wrapper <comando>: ~/.local/bin/<comando> → .venv/bin/<comando> con la config de este repo.
install_wrapper() {
  local name="$1" wrapper="$HOME/.local/bin/$1" new_wrapper
  if [ -e "$wrapper" ] && ! grep -q "$MARKER" "$wrapper" 2>/dev/null; then
    echo "⚠ $wrapper ya existe y no es de este proyecto: no lo toco."
    return
  fi
  new_wrapper="$(cat <<EOF
#!/usr/bin/env bash
# $MARKER. Vuelve a correr setup.sh para actualizarlo.
export AULA_CONFIG="\${AULA_CONFIG:-${AULA_CONFIG:-$REPO/config.toml}}"
export AULA_SECRETS="\${AULA_SECRETS:-$SECRETS}"
exec '$VENV/bin/$name' "\$@"
EOF
)"
  if [ "$(cat "$wrapper" 2>/dev/null)" != "$new_wrapper" ]; then
    printf '%s\n' "$new_wrapper" > "$wrapper"
    chmod 755 "$wrapper"
    echo "$name instalado en $wrapper"
  else
    echo "$name ya estaba instalado"
  fi
}

say "Instalando los comandos aula y vinci-equipo en ~/.local/bin"
mkdir -p "$HOME/.local/bin"
install_wrapper aula
install_wrapper vinci-equipo
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "⚠ Agrega ~/.local/bin a tu PATH para usar 'aula' y 'vinci-equipo'.";; esac

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

say "Configurando Vinci y tus bots de materia en Hermes"
AULA_SECRETS="$SECRETS" "$VENV/bin/espol-bot" hermes-perfil --hermes "$HERMES_BIN"

if [ "$RUN_CHECKS" = 1 ]; then
  say "Probando el acceso al aula virtual (solo lectura)"
  if AULA_SECRETS="$SECRETS" "$VENV/bin/aula" cursos --actualizar; then
    echo "✓ Canvas responde"
  else
    echo "⚠ No pude leer el aula virtual; revisa CANVAS_TOKEN en $SECRETS" >&2
  fi
  say "Vinci te manda un mensaje de prueba por Telegram"
  AULA_SECRETS="$SECRETS" "$VENV/bin/espol-bot" probar \
    || echo "⚠ Telegram no aceptó el mensaje; revisa TELEGRAM_BOT_TOKEN y que le hayas escrito /start a Vinci" >&2
fi

PROFILE="$("$VENV/bin/python" -c 'from espol_bot.config import load_bot_config; print(load_bot_config().hermes_profile)')"
cat <<EOF

Listo. Un solo gateway de Hermes atiende a Vinci y a todos tus bots de materia.
Para encenderlo (queda corriendo en segundo plano y arranca con tu sesión):
  hermes gateway install      # una sola vez (si ya usas el gateway de Hermes, sáltate esto)
  hermes gateway start        # si ya estaba encendido, toma los bots nuevos solo en ~30 s
Ver si está vivo:  hermes gateway status   ·   $PROFILE cron list
Apagarlo:          hermes gateway stop     (apaga también tu Hermes personal en Telegram, si lo usas)

Si todavía no lo hiciste (todo en el chat con Vinci):
  1. Escríbele «arma mi equipo» y pulsa «➕ Crear» en cada materia. Si en @BotFather activaste
     «gestionar bots» para Vinci, cada bot se crea con un toque; si no, Vinci te guía con /newbot.
  2. Mándale una captura de tu horario (con la columna de horas) y confírmala con el botón.
EOF
