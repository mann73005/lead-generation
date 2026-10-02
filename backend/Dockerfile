# Deliberately a plain Dockerfile rather than a platform-specific build
# config: the same image runs on Railway, Render, Fly and locally, so the
# choice of host stays a deployment decision rather than a code one.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so a source change does not invalidate the install layer.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Migrations run on boot. For a single-instance deployment this is the simplest
# thing that keeps schema and code in step; with multiple replicas it would
# need to move to a release phase so they do not race.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
