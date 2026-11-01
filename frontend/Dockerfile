# GateVision dashboard image: Vite build served by nginx with /api and /media
# reverse-proxied to the API container.
#
# The runtime stage uses nginx-unprivileged (uid 101) and listens on 8080, so
# the container can run with a read-only root filesystem and no capabilities.
# syntax=docker/dockerfile:1.7

FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .

ARG VITE_API_BASE_URL=/api/v1
ARG VITE_MEDIA_BASE_URL=
ARG VITE_WS_BASE_URL=
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_MEDIA_BASE_URL=${VITE_MEDIA_BASE_URL} \
    VITE_WS_BASE_URL=${VITE_WS_BASE_URL} \
    NODE_ENV=production

RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime

LABEL org.opencontainers.image.title="GateVision Dashboard" \
      org.opencontainers.image.description="React dashboard for GateVision smart gate management" \
      org.opencontainers.image.licenses="MIT"

USER root
RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/gatevision.conf
COPY --from=build /app/dist /usr/share/nginx/html
USER 101

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8080/healthz >/dev/null 2>&1 || exit 1

CMD ["nginx", "-g", "daemon off;"]
