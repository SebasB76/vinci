#!/bin/sh
# Installed as /usr/local/bin/espol-bot and /usr/local/bin/vinci-move. Coolify's terminal opens a root shell, and
# a file root writes into /opt/data is one the gateway (user hermes) cannot read: run as hermes instead.
case "$(basename "$0")" in
  vinci-move) set -- /opt/vinci/.venv/bin/python /opt/vinci/deploy/move.py "$@" ;;
  *) set -- /opt/vinci/.venv/bin/espol-bot "$@" ;;
esac
[ "$(id -u)" = 0 ] && set -- /command/s6-setuidgid hermes "$@"
HOME=/opt/data exec "$@"
