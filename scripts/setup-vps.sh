#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# scripts/setup-vps.sh — configuración inicial del servidor (correr UNA sola vez)
# Probado en Ubuntu 22.04 / 24.04
#
# Uso:
#   ssh root@IP_DEL_VPS
#   curl -fsSL https://raw.githubusercontent.com/TU_USUARIO/cafe-sistema/main/scripts/setup-vps.sh | bash
# ─────────────────────────────────────────────────────────────────────────────
set -e

# ── 1. Paquetes del sistema ───────────────────────────────────────────────────
echo "=== [1/8] Actualizando paquetes ==="
apt-get update -qq
apt-get install -y --no-install-recommends \
  git curl nginx certbot python3-certbot-nginx \
  ufw fail2ban

# ── 2. Docker ─────────────────────────────────────────────────────────────────
echo "=== [2/8] Instalando Docker ==="
if ! command -v docker &> /dev/null; then
  curl -fsSL https://get.docker.com | bash
  usermod -aG docker "$USER"
fi
docker --version
docker compose version

# ── 3. Firewall básico ────────────────────────────────────────────────────────
echo "=== [3/8] Configurando UFW ==="
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# ── 4. Red Docker compartida entre contenedores ───────────────────────────────
echo "=== [4/8] Creando red Docker cafe_net ==="
docker network create cafe_net 2>/dev/null || echo "  Red cafe_net ya existe"

# ── 5. Clonar repositorio ─────────────────────────────────────────────────────
echo "=== [5/8] Clonando repositorio ==="
mkdir -p /opt/cafe-sistema
if [ ! -d /opt/cafe-sistema/.git ]; then
  # Reemplaza con la URL de tu repo
  git clone https://github.com/TU_USUARIO/cafe-sistema.git /opt/cafe-sistema
else
  echo "  Repositorio ya existe"
fi
cd /opt/cafe-sistema

# ── 6. Archivos .env de producción (debes editarlos manualmente) ───────────────
echo "=== [6/8] Creando archivos .env ==="
if [ ! -f backend/.env.prod ]; then
  cat > backend/.env.prod << 'EOF'
DATABASE_URL=sqlite:///./cafe_sistema.db
SECRET_KEY=CAMBIA_ESTO_POR_UNA_CLAVE_SEGURA_DE_AL_MENOS_32_CARACTERES
ACCESS_TOKEN_EXPIRE_MINUTES=480
ALGORITHM=HS256
UPLOAD_DIR=uploads
ENV=production
EOF
  echo "  ⚠️  EDITA backend/.env.prod con tu SECRET_KEY real antes de continuar"
fi

# ── 7. Nginx ──────────────────────────────────────────────────────────────────
echo "=== [7/8] Configurando nginx ==="
cp nginx/cafe.conf /etc/nginx/sites-available/cafe
ln -sf /etc/nginx/sites-available/cafe /etc/nginx/sites-enabled/cafe
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo ""
echo "  ⚠️  Recuerda reemplazar 'tudominio.com' en nginx/cafe.conf con tu dominio real"
echo "  Luego corre:  certbot --nginx -d app.tudominio.com -d sandbox.tudominio.com"

# ── 8. Primer deploy ──────────────────────────────────────────────────────────
echo "=== [8/8] Primer deploy ==="
echo ""
echo "  Cuando hayas editado los .env, corre:"
echo "    cd /opt/cafe-sistema"
echo "    git checkout sandbox && docker compose -f docker-compose.sandbox.yml up -d --build"
echo "    git checkout main    && docker compose -f docker-compose.prod.yml    up -d --build"
echo ""
echo "✅ Setup del VPS completado"
