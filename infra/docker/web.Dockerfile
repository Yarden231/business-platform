# syntax=docker/dockerfile:1
#
# Local development image for the Next.js application.
# Production images (standalone output, non-root, no dev dependencies) are
# Phase 10.
#
# Build context is the repository root because the npm workspace root owns the
# lockfile and the hoisted node_modules.

FROM node:24-bookworm-slim

ENV NODE_ENV=development \
    NEXT_TELEMETRY_DISABLED=1

WORKDIR /srv/app

COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
RUN --mount=type=cache,target=/root/.npm npm ci

COPY apps/web/ apps/web/

# These directories are mounted as anonymous volumes by Compose so the host's
# macOS/Windows build artefacts never shadow the Linux ones. Creating them here
# gives the volumes the right ownership.
RUN mkdir -p /srv/app/apps/web/node_modules /srv/app/apps/web/.next \
    && chown -R node:node /srv/app

USER node
WORKDIR /srv/app/apps/web

EXPOSE 3000

CMD ["npm", "run", "dev"]
