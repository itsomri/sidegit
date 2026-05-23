FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY sidegit/ sidegit/

RUN pip install --no-cache-dir ".[postgres,s3]"

# Default config search path inside the container:
#   1. /etc/sidegit/config.yaml   (mount or COPY your config here)
#   2. ./sidegit.yaml             (next to the source, for ad-hoc use)
# Env vars and CLI flags still override the file.

EXPOSE 8080

# Single worker is the safe default — SQLite can't handle concurrent writes.
# Bump --workers only when DATABASE_URL points at PostgreSQL.
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --timeout 60 'sidegit.app:create_app()'"]
