FROM node:22-alpine AS deps
RUN corepack enable
WORKDIR /srv
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM node:22-alpine AS build
RUN corepack enable
WORKDIR /srv
COPY --from=deps /srv/node_modules ./node_modules
COPY . .
# Next.js resolves rewrite destinations at build time, so the backend
# origin must be provided here (compose passes http://backend:8000).
ARG BACKEND_URL=http://localhost:8000
ENV BACKEND_URL=$BACKEND_URL
RUN pnpm build

FROM node:22-alpine AS run
WORKDIR /srv
ENV NODE_ENV=production
# Server components fetch the backend at runtime (rewrites are baked at
# build time, but SSR data fetching is not)
ARG BACKEND_URL=http://localhost:8000
ENV BACKEND_URL=$BACKEND_URL
COPY --from=build /srv/.next/standalone ./
COPY --from=build /srv/.next/static ./.next/static
COPY --from=build /srv/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
