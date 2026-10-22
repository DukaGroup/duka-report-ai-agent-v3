FROM node:24-bookworm-slim AS frontend-build
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM node:24-bookworm-slim AS codex-runtime
WORKDIR /opt/codex
RUN npm install --omit=dev --save-exact @openai/codex@0.162.1

FROM python:3.12-slim-bookworm AS application
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=codex-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=codex-runtime /opt/codex /opt/codex
RUN ln -s /opt/codex/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex
WORKDIR /app
COPY backend/requirements*.txt backend/constraints.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip==26.2 \
    && pip install --no-cache-dir -r requirements.txt -r requirements-voice.txt
COPY backend/app /app/app
COPY backend/queries /app/queries
COPY --from=frontend-build /build/frontend/dist /app/frontend
RUN useradd --create-home --uid 10001 app && mkdir -p /data && chown app:app /data
USER app
ENV DATA_DIR=/data FRONTEND_DIR=/app/frontend PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    REPORT_QUERY_DIR=/app/queries \
    XDG_CACHE_HOME=/data/cache HF_HOME=/data/speech-cache/huggingface HF_XET_CACHE=/data/speech-cache/xet
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log"]
