FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY app ./app
COPY config ./config
COPY prompts ./prompts
COPY schemas ./schemas

RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 controller \
    && mkdir -p /app/data \
    && chown -R controller:controller /app/data

USER controller
ENV CONTROLLER_STATE_PATH=/app/data/state.json
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
