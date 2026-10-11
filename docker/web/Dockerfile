# syntax=docker/dockerfile:1
# QueryMind AI — production web image.
#
# Stage 1 builds the React SPA with Vite (the same `npm run build` CI runs,
# which includes `tsc --noEmit`). Stage 2 serves those static files with Caddy
# and reverse-proxies /api/* to the backend, so the whole application stays
# same-origin (required by the session/CSRF cookies).
#
# Build from the REPOSITORY ROOT:
#   docker build -f docker/web/Dockerfile -t querymind-web .

FROM node:24-alpine AS build
WORKDIR /app

# Reproducible dependency install from the committed lockfile.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM caddy:2-alpine AS runtime

# Static SPA output (hashed assets in /assets, index.html at the root).
COPY --from=build /app/dist /srv
# Reverse proxy, TLS and SPA history fallback.
COPY docker/caddy/Caddyfile /etc/caddy/Caddyfile

# Certificates and Caddy state live in volumes (see docker-compose.prod.yml).
EXPOSE 80 443 443/udp
