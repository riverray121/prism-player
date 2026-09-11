FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN mkdir -p /config /data
VOLUME ["/data"]
ENV PLAYER_PORT=8760

HEALTHCHECK --interval=60s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PLAYER_PORT\", \"8760\")}/healthz', timeout=5)"

CMD ["prism-player", "serve", "--config", "/config/config.yaml"]
