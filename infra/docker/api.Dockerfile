# syntax=docker/dockerfile:1
#
# Local development image for the FastAPI service.
# Production images (multi-stage, non-root, no build tooling) are Phase 10.
#
# Build context is the repository root so the API's sources can be copied with
# their repository-relative paths.

FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.11.14 /uv /uvx /usr/local/bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

WORKDIR /srv/api

# Resolve dependencies before copying sources so an application edit does not
# invalidate the dependency layer.
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY apps/api/ ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

RUN useradd --create-home --uid 10001 api && chown -R api:api /srv/api /opt/venv
USER api

EXPOSE 8000

# Compose overrides this with a reloading development command.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
