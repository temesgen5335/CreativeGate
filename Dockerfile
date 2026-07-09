# CreativeGate service image — one process serving the API and dashboard.
# Deps install from the committed uv.lock (frozen) so builds are reproducible.
FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir uv

# Dependency layer first: cached until pyproject/lock change.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY configs ./configs
RUN uv sync --frozen --no-dev --no-editable

ENV PATH="/app/.venv/bin:$PATH" \
    CREATIVEGATE_HOST=0.0.0.0
# State lives on a mounted volume in real deployments, e.g.:
#   CREATIVEGATE_DB=/data/creativegate.db
#   CREATIVEGATE_ARTIFACT_DIR=/data/artifacts
#   CREATIVEGATE_CACHE_DIR=/data/model-cache
# The platform's $PORT is honored automatically; 8000 is the local default.
EXPOSE 8000

CMD ["creativegate", "serve"]
