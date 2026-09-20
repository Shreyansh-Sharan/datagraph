FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install ".[databricks]"
EXPOSE 8000
ENV ONTOFORGE_LOG_FORMAT=json
# migrations run at startup (create_app_from_settings)
CMD ["uvicorn", "ontoforge.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
