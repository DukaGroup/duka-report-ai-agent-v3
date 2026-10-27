FROM node:24-bookworm-slim AS build
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginxinc/nginx-unprivileged:stable-alpine AS frontend
COPY --from=build /build/frontend/dist /usr/share/nginx/html
COPY frontend/deploy/nginx.conf.template /etc/nginx/duka.conf.template
COPY --chmod=755 frontend/deploy/start.sh /usr/local/bin/start-frontend
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q --spider http://127.0.0.1:8080/healthz || exit 1
ENTRYPOINT ["/usr/local/bin/start-frontend"]
