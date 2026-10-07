#!/usr/bin/env bash
# {{MARKER}}. No lo edites: vuelve a correr setup.sh.
# Lo ejecuta el cron de Hermes. `sondeo`, `mantenimiento` y `resumen` son crons "no-agent": no usan el modelo
# y, si todo sale bien, no imprimen nada (el bot manda sus propios mensajes).
# `agenda` es la compuerta del bot de una materia: imprime {"wakeAgent": false} (no se llama al
# modelo, cero tokens) salvo cuando toca un brief de clase o hay algo que Vinci le pasó.
export AULA_CONFIG='{{CONFIG}}'
export AULA_SECRETS='{{SECRETS}}'
{{ENV_EXTRA}}exec '{{BOT}}' {{COMMAND}}
