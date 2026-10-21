# Build context is docs/ (Coolify: base directory /docs). The site needs
# ../compliance at build time, which is why the Dockerfile sits one level up.
FROM node:22-alpine AS build
RUN corepack enable && corepack prepare pnpm@9.15.9 --activate
WORKDIR /docs/site
COPY site/package.json site/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY compliance /docs/compliance
COPY site /docs/site
RUN pnpm build

FROM caddy:2-alpine
COPY --from=build /docs/site/dist /srv
COPY site/Caddyfile /etc/caddy/Caddyfile
EXPOSE 8080
