# Vinci on Hermes Agent's official image: one container, one gateway for every profile, all state in /opt/data.
# The base is pinned by digest: a Hermes update reaches Vinci only when this line changes and the image is tested.
FROM nousresearch/hermes-agent:latest@sha256:9774f4f39a9bb8c2f68ce728ed5e99ddbad282163be56764afacf88ed952b784

USER root

# OCR for scanned PDFs (aula_core/ocr.py reads the system's tessdata when the data folder has none), and the font
# of the PDF summaries (espol_bot/resumen.py).
RUN apt-get -o Acquire::Retries=3 update && \
    apt-get -o Acquire::Retries=3 install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng \
        fonts-dejavu-core && \
    rm -rf /var/lib/apt/lists/*

# The WhatsApp bridge's Node deps: the image ships bridge.js without them, and /opt/hermes is read-only at runtime.
RUN cd /opt/hermes/scripts/whatsapp-bridge && \
    npm ci --no-audit --omit=dev --fetch-retries=5 && \
    npm cache clean --force

COPY . /opt/vinci
# The versions in uv.lock, installed editable as setup.sh does: the code finds its templates (hermes/) next to src/.
# Vinci's voice (Edge TTS) goes into Hermes' venv: the image lacks it, and Microsoft refuses edge-tts 7.2.7 (403).
RUN python3 -m venv /tmp/uv && \
    /tmp/uv/bin/pip install --no-cache-dir --disable-pip-version-check uv && \
    cd /opt/vinci && \
    UV_PROJECT_ENVIRONMENT=/opt/vinci/.venv UV_PYTHON=/usr/local/bin/python3 UV_PYTHON_DOWNLOADS=never \
        /tmp/uv/bin/uv sync --frozen --no-dev --no-cache && \
    /tmp/uv/bin/uv pip install --no-cache --python /opt/hermes/.venv/bin/python edge-tts==7.3.1 && \
    rm -rf /tmp/uv && \
    chmod 0755 /opt/vinci/deploy/boot.sh /opt/vinci/deploy/healthcheck.sh && \
    install -m 0755 /opt/vinci/deploy/cont-init.sh /etc/cont-init.d/019-vinci && \
    install -m 0755 /opt/vinci/deploy/as-hermes.sh /usr/local/bin/espol-bot && \
    ln -s espol-bot /usr/local/bin/vinci-move && \
    ln -s espol-bot /usr/local/bin/vinci-check && \
    cp -r /opt/vinci/deploy/s6/vinci-panel /etc/s6-overlay/s6-rc.d/vinci-panel && \
    touch /etc/s6-overlay/s6-rc.d/user/contents.d/vinci-panel && \
    cp -r /opt/vinci/deploy/s6/vinci-mantenimiento /etc/s6-overlay/s6-rc.d/vinci-mantenimiento && \
    touch /etc/s6-overlay/s6-rc.d/user/contents.d/vinci-mantenimiento && \
    cp -r /opt/vinci/deploy/s6/vinci-sondeo /etc/s6-overlay/s6-rc.d/vinci-sondeo && \
    touch /etc/s6-overlay/s6-rc.d/user/contents.d/vinci-sondeo

# VINCI_MAINTENANCE_SERVICE and VINCI_POLL_SERVICE: deploy/s6/vinci-mantenimiento renews every token chain and
# deploy/s6/vinci-sondeo runs every poll and 7:00 summary outside the gateway, so hermes_setup drops those crons.
# MALLOC_ARENA_MAX: glibc's per-thread arenas let the gateway's threads hold freed memory that never shrinks.
# HERMES_WRITE_SAFE_ROOT: the image allows writes only under /opt/data, but Hermes writes a spoken reply to
# /tmp/hermes_voice before sending it.
ENV VINCI_HERMES_ROOT=/opt/data \
    AULA_CONFIG=/opt/data/vinci/config.toml \
    AULA_SECRETS=/opt/data/vinci/secrets.env \
    HERMES_BIN=/opt/hermes/.venv/bin/hermes \
    GATEWAY_ALLOW_ALL_USERS=false \
    VINCI_MAINTENANCE_SERVICE=1 \
    VINCI_POLL_SERVICE=1 \
    MALLOC_ARENA_MAX=2 \
    HERMES_WRITE_SAFE_ROOT=/opt/data:/tmp/hermes_voice

# One MCP server for every profile (deploy/s6/vinci-mcp, on 127.0.0.1 only) instead of a stdio process each:
# hermes-perfil points each profile's config.yaml at VINCI_MCP_URL.
RUN cp -r /opt/vinci/deploy/s6/vinci-mcp /etc/s6-overlay/s6-rc.d/vinci-mcp && \
    touch /etc/s6-overlay/s6-rc.d/user/contents.d/vinci-mcp
ENV VINCI_MCP_URL=http://127.0.0.1:8788

# The admin panel (deploy/s6/vinci-panel): Coolify's proxy publishes this port on the app's domain.
EXPOSE 8787

HEALTHCHECK --interval=60s --timeout=10s --start-period=5m --retries=3 CMD ["/opt/vinci/deploy/healthcheck.sh"]

# Hermes' s6 tree supervises the gateway; `gateway run` marks it to start on a fresh volume.
CMD ["gateway", "run"]
