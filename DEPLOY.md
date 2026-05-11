# Guía de Despliegue — Sistema Café

## Arquitectura de 3 entornos

```
[Tu PC — rama dev]
        ↓  git push origin sandbox
[VPS — sandbox.tudominio.com]   ← pruebas antes de publicar
        ↓  bash scripts/promote.sh
[VPS — app.tudominio.com]       ← producción, siempre activo
```

| Entorno | Rama git | URL | Base de datos | Deploy |
|---------|----------|-----|---------------|--------|
| **Dev** | `dev` | localhost | SQLite local | manual (`iniciar-dev.bat`) |
| **Sandbox** | `sandbox` | sandbox.tudominio.com | SQLite en VPS | automático al hacer push |
| **Prod** | `main` | app.tudominio.com | SQLite en VPS (volumen) | `bash scripts/promote.sh` |

---

## 1. Prerrequisitos

- VPS Ubuntu 22.04+ con mínimo **1 GB RAM** (recomendado: DigitalOcean $12/mes, Hetzner €4/mes o Vultr $6/mes con Miami)
- Dominio propio con dos subdominios: `app.tudominio.com` y `sandbox.tudominio.com`
- Repositorio en **GitHub** (privado)
- Git instalado en tu PC

---

## 2. Configurar GitHub

### 2a. Subir el repositorio

```bash
# En tu PC, dentro de la carpeta cafe-sistema
git remote add origin https://github.com/TU_USUARIO/cafe-sistema.git
git checkout -b dev
git add .
git commit -m "init: sistema café v1"
git push -u origin dev

# Crear ramas sandbox y main
git checkout -b sandbox && git push -u origin sandbox
git checkout -b main    && git push -u origin main
git checkout dev        # volver a trabajar en dev
```

### 2b. Agregar Secrets en GitHub

Ve a: **Repositorio → Settings → Secrets and variables → Actions → New repository secret**

| Secret | Valor |
|--------|-------|
| `VPS_HOST` | IP pública del VPS (ej: `164.90.xxx.xxx`) |
| `VPS_USER` | `root` o el usuario que creaste |
| `VPS_SSH_KEY` | Contenido completo de `~/.ssh/id_rsa` (la clave privada) |

### 2c. Proteger producción con aprobación manual (opcional pero recomendado)

Ve a: **Repositorio → Settings → Environments → New environment → `production`**
- Activa "Required reviewers" y agrégarte a ti mismo
- Así un push a `main` pide tu aprobación antes de desplegar

---

## 3. Configurar el VPS (una sola vez)

```bash
# Conectarse al VPS
ssh root@IP_DEL_VPS

# Clonar y correr el setup automático
git clone https://github.com/TU_USUARIO/cafe-sistema.git /opt/cafe-sistema
cd /opt/cafe-sistema
bash scripts/setup-vps.sh
```

### 3a. Editar el .env de producción

```bash
nano /opt/cafe-sistema/backend/.env.prod
```

Cambia `SECRET_KEY` por una clave segura (mínimo 32 caracteres):
```
SECRET_KEY=genera_una_aqui_con: python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 3b. Apuntar el dominio al VPS

En tu proveedor de dominio, crea dos registros A:
```
app.tudominio.com      → IP_DEL_VPS
sandbox.tudominio.com  → IP_DEL_VPS
```

### 3c. Reemplazar el dominio en nginx.conf

```bash
sed -i 's/tudominio.com/TU_DOMINIO_REAL.com/g' /opt/cafe-sistema/nginx/cafe.conf
cp /opt/cafe-sistema/nginx/cafe.conf /etc/nginx/sites-available/cafe
nginx -t && systemctl reload nginx
```

### 3d. Certificados SSL gratuitos (HTTPS)

```bash
certbot --nginx -d app.tudominio.com -d sandbox.tudominio.com
```

### 3e. Primer deploy manual

```bash
cd /opt/cafe-sistema

# Sandbox
git checkout sandbox
docker compose -f docker-compose.sandbox.yml up -d --build

# Producción
git checkout main
docker compose -f docker-compose.prod.yml up -d --build
```

---

## 4. Flujo de trabajo diario

### Desarrollar (en tu PC)

```bash
git checkout dev
# ... hacer cambios ...
git add . && git commit -m "feat: descripción del cambio"
```

### Probar en sandbox

```bash
# Fusionar dev → sandbox y desplegar
git checkout sandbox
git merge dev --no-ff
git push origin sandbox
# ↑ GitHub Actions despliega automáticamente a sandbox.tudominio.com
```

### Pasar a producción (sin parar el sistema)

```bash
git checkout sandbox
bash scripts/promote.sh
# ↑ Fusiona sandbox → main, push, GitHub Actions despliega (~3s de corte)
```

---

## 5. Comandos útiles en el VPS

```bash
# Ver logs en tiempo real
docker compose -f docker-compose.prod.yml logs -f app

# Ver logs de sandbox
docker compose -f docker-compose.sandbox.yml logs -f app

# Reiniciar producción
docker compose -f docker-compose.prod.yml restart app

# Estado de los contenedores
docker ps

# Backup de la base de datos de producción
docker run --rm -v cafe-sistema_prod_db:/data alpine \
  tar czf - /data > backup_$(date +%Y%m%d).tar.gz

# Acceder a la base de datos SQLite de producción
docker exec -it cafe_prod sqlite3 /app/backend/data/cafe_sistema.db
```

---

## 6. Costos estimados

| Proveedor | Especificaciones | Precio | Recomendado para |
|-----------|-----------------|--------|-----------------|
| DigitalOcean | 2 GB RAM, 1 vCPU, Miami | ~$12/mes | Inicio recomendado |
| Hetzner | 2 GB RAM, 1 vCPU, Falkenstein | ~€4/mes | Más económico |
| Vultr | 1 GB RAM, 1 vCPU, Miami | ~$6/mes | Latencia Colombia |

**Dominio:** ~$10-15/año (Namecheap, Porkbun, o tu registrador preferido)

---

## 7. Seguridad importante

- ✅ `.env.prod` está en `.gitignore` — nunca va a GitHub
- ✅ HTTPS obligatorio con certbot (Let's Encrypt)
- ✅ Firewall UFW: solo puertos 22, 80, 443
- ✅ fail2ban instalado para proteger SSH
- ⚠️ Cambia `SECRET_KEY` antes del primer deploy de producción
- ⚠️ Considera restringir sandbox por IP en nginx.conf (ver comentario en el archivo)
