# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=10082 \
    DB_PATH=/app/data/forwarder.db \
    SESSION_PATH=/app/data/sessions/forwarder.session
WORKDIR /app
COPY pyproject.toml README.md /tmp/tg-forward/
COPY src/tg_forwarder/ /tmp/tg-forward/src/tg_forwarder/
COPY --from=frontend /build/frontend/dist/ /tmp/tg-forward/src/tg_forwarder/web/dist/
RUN pip install --no-cache-dir /tmp/tg-forward \
    && rm -rf /tmp/tg-forward \
    && groupadd --gid 10001 tg-forward \
    && useradd --uid 10001 --gid tg-forward --no-create-home --home-dir /app tg-forward \
    && mkdir -p /app/data/sessions /app/temp \
    && chown -R tg-forward:tg-forward /app
USER tg-forward
EXPOSE 10082
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['WEB_PORT'] + '/api/auth', timeout=3).close()"]
ENTRYPOINT ["tg-forward"]
CMD ["serve"]
