# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS frontend
WORKDIR /app/adlc-flow/frontend
ENV PUPPETEER_SKIP_DOWNLOAD=true PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
COPY adlc-flow/frontend/package.json adlc-flow/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY adlc-flow/frontend/ ./
COPY adlc_components /app/adlc_components
ENV GOMAXPROCS=2 GOMEMLIMIT=768MiB NODE_OPTIONS=--max-old-space-size=3072
RUN npx vite build

FROM python:3.14-slim AS backend
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DO_NOT_TRACK=1 LANGFLOW_DO_NOT_TRACK=true
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends libgomp1 libmagic1t64 git \
    && rm -rf /var/lib/apt/lists/*
COPY deploy/local/requirements.lock.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY pyproject.toml ./
COPY deploy/local/requirements.in ./deploy/local/requirements.in
COPY sdk ./sdk
COPY adlc-flow/langflow ./adlc-flow/langflow
COPY adlc-flow/lfx ./adlc-flow/lfx
COPY adlc_components ./adlc_components
COPY adlc-contracts ./adlc-contracts
COPY integration-sources ./integration-sources
RUN pip install --no-cache-dir --no-deps -e . -e ./sdk \
    && useradd -m -u 1000 pokedev && mkdir -p /app/adlc-flow/data /app/data \
    && chown -R pokedev:pokedev /app/adlc-flow/data /app/data
COPY --from=frontend /app/adlc-flow/frontend/build ./adlc-flow/frontend/build
USER pokedev
EXPOSE 7862
CMD ["python", "-m", "langflow", "run", "--host", "0.0.0.0", "--port", "7862", "--workers", "1", "--frontend-path", "/app/adlc-flow/frontend/build", "--no-open-browser"]
