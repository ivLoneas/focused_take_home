FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH=/app/.venv/bin:$PATH \
    HF_HOME=/var/cache/models/huggingface \
    DOCLING_ARTIFACTS_PATH=/var/cache/models/docling

RUN apt-get update \
    && apt-get install --no-install-recommends -y libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY etl ./etl
COPY utils ./utils
COPY README.md ./README.md

RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home app \
    && mkdir -p /app/data /var/cache/models \
    && chown -R app:app /app /var/cache/models \
    && chmod 0777 /var/cache/models \
    && chmod -R a+rwX /app/.venv/lib/python3.14/site-packages/rapidocr/models

USER app
ENTRYPOINT ["python", "-m", "etl"]
CMD ["--help"]
