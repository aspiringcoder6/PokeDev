FROM python:3.12-slim
WORKDIR /app
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends libmagic1t64 curl \
    && rm -rf /var/lib/apt/lists/*
COPY services/memory/ ./
RUN pip install --no-cache-dir ".[api]" "fastmcp>=3.4,<4" "mcp>=1.24,<2" \
    && pip install --no-cache-dir --no-deps ./cognee-mcp
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh \
    && useradd -m -u 1000 cognee && mkdir -p /cognee-storage/system /cognee-storage/data \
    && chown -R cognee:cognee /cognee-storage && chown cognee:cognee /app
USER cognee
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOME=/app
ENTRYPOINT ["/app/entrypoint.sh"]
