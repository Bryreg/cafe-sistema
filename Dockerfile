# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: Build del frontend (React + Vite)
# ─────────────────────────────────────────────────────────────────────────────
FROM node:20-alpine AS frontend-build

WORKDIR /app/frontend

# Instalar dependencias primero (cache layer)
COPY frontend/package*.json ./
RUN npm ci --silent

# Copiar fuente y compilar
COPY frontend/ ./
ARG VITE_ENV=production
ENV VITE_ENV=$VITE_ENV
RUN npm run build

# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: Runtime — backend Python sirve el frontend compilado
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Instalar curl para healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Dependencias Python (usando requirements-prod.txt — 12 paquetes, no 165)
COPY backend/requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

# Código backend
COPY backend/ ./backend/

# Frontend compilado (main.py lo busca en ../../frontend/dist relativo a app/)
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Directorio de uploads (se sobreescribirá con un volumen en producción)
RUN mkdir -p ./backend/uploads ./backend/uploads_sandbox

# El backend se ejecuta desde /app/backend
WORKDIR /app/backend

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2"]
