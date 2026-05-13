#!/usr/bin/env bash
# deploy.sh — construye el frontend y arranca el backend en modo producción
# Uso: bash deploy.sh [puerto]   (default 8000)
set -e

PORT=${1:-8000}
ROOT="$(cd "$(dirname "$0")" && pwd)"
FRONTEND="$ROOT/frontend"
BACKEND="$ROOT/backend"

echo "=== Build frontend ==="
cd "$FRONTEND"
npm install --silent
npm run build
echo "  dist/ generado en $FRONTEND/dist"

echo ""
echo "=== Arrancando backend (puerto $PORT) ==="
cd "$BACKEND"

# Instalar dependencias Python si hace falta
if [ -f requirements.txt ]; then
  pip install -r requirements.txt -q
fi

# Usar .env.production si existe, si no .env
ENV_FILE=".env.production"
[ ! -f "$ENV_FILE" ] && ENV_FILE=".env"

echo "  ENV: $ENV_FILE"
echo "  URL: http://0.0.0.0:$PORT"
echo ""

ENV_FILE="$ENV_FILE" python -m uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "$PORT" \
  --workers 2
