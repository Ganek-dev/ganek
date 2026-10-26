# Build context is the REPO ROOT (docker build -f backend/Dockerfile .), so the
# question bank ships inside the image and an image-only compose file seeds
# it without a checkout. The root .dockerignore allowlists backend/ and
# questions/ only.
FROM python:3.14-slim AS base
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /srv
COPY backend/pyproject.toml backend/uv.lock* ./
RUN uv sync --frozen --no-dev 2>/dev/null || uv sync --no-dev
COPY backend/app ./app
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
# seed.questions_dir() resolves /srv/questions; a compose bind mount of
# ./questions over it still wins for local question editing
COPY questions ./questions
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
