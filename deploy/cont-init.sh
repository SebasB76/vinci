#!/command/with-contenv sh
# Installed as /etc/cont-init.d/019-vinci: after Hermes' own setup (01), before its profile reconciler (02).
# A failed step must not stop the container, or nobody could open a shell in it to fix the cause.
s6-setuidgid hermes /opt/vinci/deploy/boot.sh || echo "[vinci] boot.sh failed: see the lines above" >&2
exit 0
