FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    FASTEMBED_CACHE_PATH=/opt/fastembed \
    SENTINEL_DATA_DIR=/data

# Pango and HarfBuzz are WeasyPrint's native dependencies; git clones audit targets.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY sentinel ./sentinel
# Editable, so the package resolves demo_repo/ and evals/ beside it under /app.
RUN pip install -e ".[pdf]" \
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

# Bake the embedding model into the image so a run never waits on a download.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5')"

COPY demo_repo ./demo_repo
COPY evals ./evals
ENV SENTINEL_TARGET_REPO=/app/demo_repo

RUN useradd --create-home sentinel \
    && mkdir -p /data \
    && chown -R sentinel:sentinel /data /opt/playwright /opt/fastembed
USER sentinel

CMD ["sentinel", "worker", "--cron", "0 6 * * *"]
