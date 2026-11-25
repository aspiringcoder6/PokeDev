FROM grafana/k6:latest AS k6
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
COPY --from=k6 /usr/bin/k6 /usr/local/bin/k6
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends libatomic1 \
    && rm -rf /var/lib/apt/lists/*
COPY services/testforge/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
RUN playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*
COPY services/testforge/ ./
RUN useradd -m -u 1000 testforge && mkdir -p /app/artifacts \
    && chown testforge:testforge /app/artifacts
RUN chmod -R a+rX /ms-playwright
USER testforge
CMD ["python", "testforge_broker.py", "--host", "0.0.0.0", "--port", "9099"]
