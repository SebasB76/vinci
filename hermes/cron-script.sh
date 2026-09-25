#!/usr/bin/env bash
# {{MARKER}}. No lo edites: vuelve a correr setup.sh.
# Hermes lo ejecuta como cron "no-agent": no usa el modelo ni gasta tokens.
# Si todo sale bien no imprime nada (Hermes no entrega nada); el bot envía sus propios mensajes.
export AULA_CONFIG='{{CONFIG}}'
export AULA_SECRETS='{{SECRETS}}'
exec '{{BOT}}' {{COMMAND}}
