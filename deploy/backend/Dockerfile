# The API image. Build from the repository root, which is where the context must start:
#
#   docker build -f deploy/backend/Dockerfile -t datagraph-api .
#
# Migrations run at startup, so the container is the only thing that needs deploying.
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
# The package first and the sources after, so a code change does not reinstall the dependencies.
COPY backend/pyproject.toml /src/pyproject.toml
COPY backend/src /src/src
RUN pip install --upgrade pip && pip install "/src[databricks]"

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH" ONTOFORGE_LOG_FORMAT=json
# A compiler never reaches the runtime image, and the process never runs as root.
RUN useradd --system --create-home --uid 10001 datagraph
COPY --from=builder /opt/venv /opt/venv
USER datagraph
WORKDIR /app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"
# Behind a proxy the signed-in user arrives in a header, so the forwarded headers must be trusted.
CMD ["uvicorn", "ontoforge.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
