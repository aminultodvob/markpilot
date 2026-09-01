# Web app: Next.js in standalone output mode.
#
# `output: "standalone"` in next.config.ts traces exactly the dependencies the
# server needs, so the runtime image carries neither node_modules nor the
# build toolchain.

# --- dependencies -----------------------------------------------------------
FROM node:22-bookworm-slim AS deps

WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json ./
# `npm ci` installs exactly the lockfile, which is what makes builds repeatable.
RUN npm ci --no-audit --no-fund

# --- build ------------------------------------------------------------------
FROM node:22-bookworm-slim AS build

WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY apps/web ./
# The formats registry lives outside apps/web and is imported via @formats/*.
COPY packages/formats ../../packages/formats

ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# --- runtime ----------------------------------------------------------------
FROM node:22-bookworm-slim AS runtime

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN apt-get update && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

# node:22 images already ship a `node` user; run as it rather than root.
WORKDIR /app
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./apps/web/.next/static
COPY --from=build --chown=node:node /app/public ./apps/web/public

USER node
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:3000/ >/dev/null || exit 1

CMD ["node", "apps/web/server.js"]
