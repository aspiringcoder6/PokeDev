FROM node:22-bookworm-slim
COPY --from=python:3.14-slim /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends bubblewrap socat iptables ca-certificates curl git python3 procps \
    && rm -rf /var/lib/apt/lists/*
ARG DSH_VERSION=0.1.5-rc.2
RUN npm install -g "@deepseek-ai/dsh@${DSH_VERSION}"
COPY deploy/local/harness-modules.cjs /tmp/harness-modules.cjs
RUN node /tmp/harness-modules.cjs
WORKDIR /app
COPY services/harness/plugins /app/plugins-source
COPY deploy/local/harness.patch.yml /app/plugins-source/patch.yml
COPY deploy/local/harness-lock.mjs /tmp/harness-lock.mjs
RUN node /tmp/harness-lock.mjs
COPY deploy/local/harness-entrypoint.sh /entrypoint.sh
COPY deploy/local/harness-config.mjs /app/harness-config.mjs
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh \
    && mkdir -p /app/data /app/workspace && chown -R node:node /app/data /app/workspace
EXPOSE 3080
ENTRYPOINT ["/entrypoint.sh"]
