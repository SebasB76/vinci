# Vinci on Hermes Agent's official image: one container, one gateway for every profile, all state in /opt/data.
# The base is pinned by digest: a Hermes update reaches Vinci only when this line changes and the image is tested.
FROM nousresearch/hermes-agent:latest@sha256:9774f4f39a9bb8c2f68ce728ed5e99ddbad282163be56764afacf88ed952b784

USER root

# OCR for scanned PDFs (aula_core/ocr.py reads the system's tessdata when the data folder has none).
RUN apt-get -o Acquire::Retries=3 update && \
    apt-get -o Acquire::Retries=3 install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng && \
    rm -rf /var/lib/apt/lists/*

# The WhatsApp bridge's Node deps: the image ships bridge.js without them, and /opt/hermes is read-only at runtime.
RUN cd /opt/hermes/scripts/whatsapp-bridge && \
    npm ci --no-audit --omit=dev --fetch-retries=5 && \
    npm cache clean --force

COPY . /opt/vinci
# The versions in uv.lock, installed editable as setup.sh does: the code finds its templates (hermes/) next to src/.
RUN python3 -m venv /tmp/uv && \
    /tmp/uv/bin/pip install --no-cache-dir --disable-pip-version-check uv && \
    cd /opt/vinci && \
    UV_PROJECT_ENVIRONMENT=/opt/vinci/.venv UV_PYTHON=/usr/local/bin/python3 UV_PYTHON_DOWNLOADS=never \
        /tmp/uv/bin/uv sync --frozen --no-dev --no-cache && \
    rm -rf /tmp/uv && \
    chmod 0755 /opt/vinci/deploy/boot.sh && \
    install -m 0755 /opt/vinci/deploy/cont-init.sh /etc/cont-init.d/019-vinci && \
    install -m 0755 /opt/vinci/deploy/as-hermes.sh /usr/local/bin/espol-bot && \
    ln -s espol-bot /usr/local/bin/vinci-move

ENV VINCI_HERMES_ROOT=/opt/data \
    AULA_CONFIG=/opt/data/vinci/config.toml \
    AULA_SECRETS=/opt/data/vinci/secrets.env \
    HERMES_BIN=/opt/hermes/.venv/bin/hermes \
    GATEWAY_ALLOW_ALL_USERS=false

# Hermes' s6 tree supervises the gateway; `gateway run` marks it to start on a fresh volume.
CMD ["gateway", "run"]
