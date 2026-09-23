# The UI image: the built single-page app on nginx, which also fronts the API and the connection hub.
# Build from the repository root. The @polestar package comes from a private feed, so its token
# arrives as a build secret and never lands in a layer:
#
#   docker build --secret id=npm_token,env=NPM_TOKEN -f deploy/frontend/Dockerfile -t datagraph-web .
#
# Without the secret the build still works wherever the feed allows anonymous reads.
FROM node:22-alpine AS build
RUN corepack enable
WORKDIR /app
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/.npmrc ./
# The token lives only in this layer's secret mount and in a file deleted in the same step.
RUN --mount=type=secret,id=npm_token,required=false \
    if [ -s /run/secrets/npm_token ]; then \
      printf '//pkgs.dev.azure.com/polestar-products/nextgen_platform/_packaging/microservices-shared/npm/registry/:_authToken=%s\n' "$(cat /run/secrets/npm_token)" >> .npmrc; \
    fi; \
    pnpm install --frozen-lockfile; \
    sed -i '/_authToken/d' .npmrc
COPY frontend/ ./
# The API and the hub are same-origin behind this nginx, so the app needs no absolute URLs.
ENV VITE_API_MODE=rest VITE_BASE=/ VITE_API_BASE=/api VITE_CONNECTIONS_URL=/hub
RUN pnpm run build

FROM nginx:1.27-alpine AS runtime
ENV API_UPSTREAM=http://api:8000 HUB_UPSTREAM=http://hub:8025 AUTH_HEADER=X-Actor
COPY --from=build /app/dist /usr/share/nginx/html
COPY deploy/frontend/nginx.conf.template /etc/nginx/templates/default.conf.template
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
