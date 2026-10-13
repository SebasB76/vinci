#!/bin/sh
# Docker's HEALTHCHECK: "Running" only says the container is up. Unhealthy when hermes-perfil failed at boot or no
# gateway process runs (the init shell also carries `gateway run`, so only a Python one counts).
[ -e /opt/data/vinci/boot-failed ] && exit 1
for cmdline in /proc/[0-9]*/cmdline; do
  tr '\0' ' ' < "$cmdline" 2>/dev/null | grep -q '^[^ ]*python[^ ]* .*gateway run' && exit 0
done
exit 1
