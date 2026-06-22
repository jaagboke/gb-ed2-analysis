# ── Stage 1: build the React frontend ────────────────────────────────────────
FROM node:20-slim AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --prefer-offline
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python / Flask runtime ──────────────────────────────────────────
FROM python:3.11-slim
WORKDIR /app

# Python dependencies (lean — pipelines are run offline, not at server start)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code + pre-built CSV data
COPY . .

# Overlay the freshly built frontend (dist/ is gitignored so won't be in COPY above)
COPY --from=frontend-build /build/dist ./frontend/dist

# Render sets $PORT at runtime; fall back to 10000 for local docker run
EXPOSE 10000
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-10000} --workers 1 --threads 4 --timeout 120 app.backend:app"]
