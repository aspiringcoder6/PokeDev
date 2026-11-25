FROM node:22-bookworm-slim
COPY --from=python:3.14-slim /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
WORKDIR /app
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends python3 make g++ \
    && rm -rf /var/lib/apt/lists/*
COPY services/sandbox/vfs-service/package*.json ./
RUN npm ci --no-audit --no-fund
COPY services/sandbox/vfs-service/src ./src
RUN mkdir -p /app/data && chown node:node /app/data
USER node
ENV VFS_PORT=8001
CMD ["node", "--import", "tsx", "src/server.ts"]
