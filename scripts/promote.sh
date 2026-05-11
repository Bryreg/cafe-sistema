#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# scripts/promote.sh — promueve sandbox → producción sin parar lo que corre
#
# Uso (desde tu máquina de desarrollo):
#   bash scripts/promote.sh
#
# Qué hace:
#   1. Verifica que estás en la rama sandbox y que está limpia
#   2. Fusiona sandbox → main
#   3. Push a main → dispara GitHub Actions → deploy automático con ~3s downtime
#   4. Regresa a sandbox para que puedas seguir trabajando
# ─────────────────────────────────────────────────────────────────────────────
set -e

# Colores
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo -e "${YELLOW}=== Promote: sandbox → producción ===${NC}"

# 1. Verificar que estamos en sandbox
BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$BRANCH" != "sandbox" ]; then
  echo -e "${RED}❌ Debes estar en la rama 'sandbox' (estás en '$BRANCH')${NC}"
  exit 1
fi

# 2. Verificar que el working tree está limpio
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo -e "${RED}❌ Tienes cambios sin commitear. Haz commit antes de promover.${NC}"
  exit 1
fi

# 3. Asegurarse de estar actualizado
echo "── Pulling sandbox..."
git pull origin sandbox

# 4. Mostrar resumen de commits que se van a promover
echo ""
echo -e "${YELLOW}Commits que se van a pasar a producción:${NC}"
git log main..sandbox --oneline
echo ""
read -p "¿Confirmas el promote a producción? (s/N): " CONFIRM
if [[ "$CONFIRM" != "s" && "$CONFIRM" != "S" ]]; then
  echo "Cancelado."
  exit 0
fi

# 5. Merge sandbox → main
echo "── Cambiando a main..."
git checkout main
git pull origin main

echo "── Merge sandbox → main..."
git merge sandbox --no-ff -m "chore: promote sandbox → producción [$(date +'%Y-%m-%d %H:%M')]"

# 6. Push (dispara GitHub Actions)
echo "── Push a main (dispara deploy automático)..."
git push origin main

echo ""
echo -e "${GREEN}✅ Promote lanzado${NC}"
echo "   → GitHub Actions está desplegando en producción"
echo "   → Sigue el progreso en: https://github.com/TU_USUARIO/cafe-sistema/actions"
echo ""

# 7. Volver a sandbox
git checkout sandbox
echo -e "${GREEN}✅ De vuelta en sandbox — puedes seguir desarrollando${NC}"
