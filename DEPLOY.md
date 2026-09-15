# Guía de Despliegue — Sistema Café

> **Leé esta primera sección antes de mover una rama.** El resto del archivo
> describe un montaje en VPS que **NO es el que está corriendo**, y confundirlos
> puede terminar con el café mirando una base de datos vacía.

---

## 1. Cómo está desplegado HOY

**`develop` es la rama principal del proyecto.** No `main`. Todo el trabajo va a
`develop`, y desde ahí sale a producción.

| Pieza | Dónde corre | Desde qué rama | Cómo se despliega |
|-------|-------------|----------------|-------------------|
| **Backend** | Render — `https://cafe-sistema-oert.onrender.com` | **`develop`** | automático al hacer push (~2 min) |
| **Frontend** | Cloudflare Pages | se configura en el panel de Cloudflare, no en el repo | automático al hacer push |
| **Base de datos** | PostgreSQL en Render | — | — |

El backend en Render **auto-despliega desde `develop`**: medido tres veces el
15-sep-2026, un endpoint nuevo apareció en producción entre 1 y 2 minutos
después del push. O sea que **mergear a `develop` ES desplegar a producción**.
No hay un paso de aprobación: lo que se empuja, sale.

El frontend vive en Cloudflare Pages y **su configuración no está en este repo**
(no hay `wrangler.toml` ni nada equivalente): la rama que construye se ve y se
cambia en el panel de Cloudflare. Para comprobar desde la app qué rama está
sirviendo, entrá como admin a **Conteos → «Editar formato»**: esa pantalla se
agregó el 15-sep-2026 en `develop`. Si está, Cloudflare construye `develop`.

### Lo que el deploy NO hace

Algunas cosas son scripts que corren contra la base y **el deploy no los
ejecuta**. Desplegar no las aplica:

- `backend/cargar_combos.py` — carga/actualiza los combos del POS.
  Correr con las variables de producción cargadas, primero con `--dry-run`.
  (Desde el 15-sep-2026 los combos también se crean desde la app: Combos →
  «Nuevo combo». El script quedó para la carga inicial.)

---

## 2. `main` es un archivo histórico, no producción

**`main` y `develop` tienen historias DISJUNTAS: no comparten ni un commit.**
Medido el 15-sep-2026:

| | `main` | `develop` |
|---|---|---|
| Primer commit | 28-abr-2026 | 22-ago-2026 |
| Último commit | 29-jul-2026 | (vigente) |
| Archivos | 354 | 524 |
| Commits que la otra no tiene | 387 | 58 |
| Ancestro común | **ninguno** | |

`develop` no salió de `main`: es una historia nueva empezada el 22 de agosto.
`main` quedó como la foto de julio, con la historia larga de abril a julio
colgando de ella. La diferencia de código entre las dos es de **264 archivos y
+86.848 líneas**, así que `develop` es el sistema y `main` es el archivo.

**Consecuencias prácticas:**

- No existe forma de «subir los commits que le faltan a `main`»: sin ancestro
  común, un `merge` necesita `--allow-unrelated-histories` y da conflictos en
  los 264 archivos. Lo único que se puede hacer es poner el árbol de `develop`
  en `main` de una sola vez.
- **Empujar a `main` dispara `.github/workflows/deploy-prod.yml`**, que hace SSH
  a un VPS y levanta ahí el contenedor. Ese entorno usa **SQLite en un volumen
  del servidor** (ver la sección 3), o sea **una base distinta** del PostgreSQL
  de Render donde están las ventas, los turnos y el inventario reales. El
  workflow pide aprobación manual (`environment: production`), así que no se
  despliega solo — pero la aprobación está a un clic.
- Si algún día se quiere revivir el camino del VPS, la decisión que hay que
  tomar primero **no es de git, es de datos**: qué base sirve. Mover la rama es
  lo fácil.

---

## 3. El montaje en VPS (NO EN USO)

Lo que sigue documenta el despliegue en VPS con tres entornos
(`dev` / `sandbox` / `main`) para el que se escribieron `docker-compose.prod.yml`,
`docker-compose.sandbox.yml`, `nginx/` y `scripts/promote.sh`. **Hoy no es lo que
sirve la aplicación** — el backend está en Render y el frontend en Cloudflare
Pages, los dos desde `develop`.

Se conserva porque los archivos siguen en el repo y los workflows siguen
armados: si se empuja a `main` o a `sandbox`, esto se dispara de verdad.

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
