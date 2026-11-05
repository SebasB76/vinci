#!/usr/bin/env bash
# {{MARKER}}. No lo edites: vuelve a correr setup.sh.
# Lo ejecuta el cron de Hermes. `sondeo`, `mantenimiento` y `resumen` son crons "no-agent": no usan el modelo
# y, si todo sale bien, no imprimen nada (el bot manda sus propios mensajes).
# `agenda` es la compuerta del bot de una materia: imprime {"wakeAgent": false} (no se llama al
# modelo, cero tokens) salvo cuando toca un brief de clase o hay algo que Vinci le pasó.
export AULA_CONFIG='{{CONFIG}}'
export AULA_SECRETS='{{SECRETS}}'
export VINCI_HERMES_ROOT='{{HERMES_ROOT}}'
{{ENV_EXTRA}}case '{{COMMAND}}' in
  sondeo|resumen)
    # Every profile reads Canvas (and OCRs) at the same minute; one at a time keeps the container under its memory
    # limit. A poll that waits too long skips its turn; the 7:00 summary waits longer.
    wait=480; [ '{{COMMAND}}' = resumen ] && wait=1800
    flock -E 75 -w "${VINCI_CANVAS_WAIT:-$wait}" '{{HERMES_ROOT}}/canvas-jobs.lock' '{{BOT}}' {{COMMAND}}
    status=$?
    [ "$status" = 75 ] && exit 0
    exit "$status" ;;
esac
exec '{{BOT}}' {{COMMAND}}
