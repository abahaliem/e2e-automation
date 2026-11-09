# QA Agent - image server (sub-proyek 4)
# 1) build dashboard (Node)  2) Python 3.12 + Chromium Playwright + adb

FROM node:22-bookworm-slim AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN mkdir -p ../qa_agent/server/static && npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    QA_AGENT_AUTH=1 \
    QA_AGENT_SECRET_BACKEND=file
RUN apt-get update \
    && apt-get install -y --no-install-recommends adb ca-certificates fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY qa_agent/ qa_agent/
COPY --from=web /src/qa_agent/server/static/ qa_agent/server/static/
RUN pip install --no-cache-dir . \
    && playwright install --with-deps chromium \
    && useradd --create-home --uid 1000 qa \
    && mkdir -p /data && chown qa:qa /data
USER qa
VOLUME ["/data"]
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/auth/status')"
CMD ["qa-agent", "serve", "--host", "0.0.0.0", "--port", "8787", "--data-dir", "/data", "--no-browser"]
