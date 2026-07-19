# Backend image: FastAPI, the Celery worker and Celery beat (#530).
#
# One image for all three because they differ only by command — same code, same
# dependency set. Three images would be three things to keep in step.
#
# Python 3.12 rather than the 3.14 used on the developer machine: shapely,
# pyarrow and psycopg all ship prebuilt wheels for 3.12, so the image builds
# without a compiler toolchain. pyproject requires >=3.11, so this is inside the
# supported range rather than a downgrade.
FROM python:3.12-slim AS base

# curl for healthchecks; libpq for psycopg's runtime. Everything else arrives as
# a wheel, which is the point of pinning to 3.12.
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl libpq5 \
    && rm -rf /var/lib/apt/lists/*

# uv gives us `--frozen`: install exactly what uv.lock says, never re-resolve.
# A backtest that cannot be reproduced is not evidence, and that starts with
# the dependency set.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first, in their own layer: application code changes on every
# commit, the lockfile rarely, so this keeps rebuilds to seconds.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

# Install the project itself now that its source is present.
RUN uv sync --frozen --no-dev

# Runs unprivileged. The bind-mounted data directory is chowned by compose's
# user mapping; nothing in the image needs write access to its own filesystem.
RUN useradd --create-home --uid 10001 osint \
    && chown -R osint:osint /app
USER osint

EXPOSE 8000

# Overridden per service in compose; this default makes `docker run` on the
# image alone do something sensible rather than nothing.
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
