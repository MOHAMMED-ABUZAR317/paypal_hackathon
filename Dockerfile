# syntax=docker/dockerfile:1

# ---------- UI build ----------
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm install --no-audit
COPY frontend/ ./
RUN npm run build

# ---------- Runtime ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY --from=ui /ui/dist ./frontend/dist

# The app writes SQLite and receipt data under backend/. Create the directory
# before dropping privileges. Override DATABASE_URL for Postgres or a disk mount.
RUN mkdir -p /app/backend/data \
    && useradd --create-home --uid 10001 raincheck \
    && chown -R raincheck:raincheck /app

USER raincheck
WORKDIR /app/backend

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
