# Multi-stage build: build React frontend, then package Python backend + static frontend into one image.

# ---------- Stage 1: build frontend ----------
FROM node:22-slim AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# ---------- Stage 2: Python backend ----------
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/root/.local/bin:$PATH"

# Cloud SQL Auth Proxy sockets mount here (default)
ENV CLOUDSQL_PROXY_SOCKET_DIR=/cloudsql

WORKDIR /app

# Install backend deps first (layer caching)
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r ./requirements.txt

# Copy backend application
COPY backend/app ./app

# Copy built frontend into the location main.py serves from
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Cloud Run expects the app to listen on $PORT, IPv4
ENV PORT=8080

# Non-root user (Cloud Run requirement)
RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /app/reports /app/data /app/data/logs \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

# Start FastAPI via uvicorn on $PORT
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]