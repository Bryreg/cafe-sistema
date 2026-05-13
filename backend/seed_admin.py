"""
seed_admin.py — Crea el primer admin y la primera tienda en la base de datos.
Uso local:
    cd backend
    DATABASE_URL="postgresql://..." python seed_admin.py

Uso en Render Shell:
    python seed_admin.py
"""
import os, sys

# ── Leer DATABASE_URL (obligatorio) ─────────────────────────────────────────
DB_URL = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL_PROD")
if not DB_URL:
    # Intentar leer del .env.prod si existe
    env_file = os.path.join(os.path.dirname(__file__), ".env.prod")
    if os.path.exists(env_file):
        for line in open(env_file):
            k, _, v = line.strip().partition("=")
            if k == "DATABASE_URL":
                DB_URL = v.strip()
                break

if not DB_URL:
    print("ERROR: Define DATABASE_URL como variable de entorno.")
    print("Ejemplo: DATABASE_URL='postgresql://user:pass@host/db?sslmode=require' python seed_admin.py")
    sys.exit(1)

# asyncpg usa postgresql+asyncpg:// pero SQLAlchemy sync usa postgresql://
# Render / Neon puede mandar postgresql+asyncpg:// — normalizamos
DB_URL = DB_URL.replace("postgresql+asyncpg://", "postgresql://")

# ── Configuración del admin a crear ─────────────────────────────────────────
NOMBRE_TIENDA = os.getenv("SEED_TIENDA", "Sede Principal")
ADMIN_NOMBRE  = os.getenv("SEED_ADMIN_NOMBRE",  "Administrador")
ADMIN_EMAIL   = os.getenv("SEED_ADMIN_EMAIL",   "admin@cafesistema.com")
ADMIN_PASS    = os.getenv("SEED_ADMIN_PASS",    "Admin2024!")

# ── Conexión y seed ─────────────────────────────────────────────────────────
from sqlalchemy import create_engine, text
from passlib.context import CryptContext

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

engine = create_engine(DB_URL, connect_args={"sslmode": "require"} if "neon.tech" in DB_URL or "sslmode=require" in DB_URL else {})

with engine.connect() as conn:
    # 1. Crear tablas si no existen (requiere modelos — usamos SQL directo para no importar todo)
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS tiendas (
            id SERIAL PRIMARY KEY,
            nombre VARCHAR(100) NOT NULL,
            direccion VARCHAR(200),
            activa BOOLEAN DEFAULT TRUE
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            nombre VARCHAR(100) NOT NULL,
            email VARCHAR(150) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            pin_hash VARCHAR(255),
            rol VARCHAR(20) NOT NULL DEFAULT 'barista',
            tienda_id INTEGER REFERENCES tiendas(id),
            activo BOOLEAN DEFAULT TRUE,
            ultimo_acceso TIMESTAMP
        )
    """))
    conn.commit()

    # 2. Verificar si ya existe algún admin
    row = conn.execute(text("SELECT id, nombre, email FROM usuarios WHERE rol = 'admin' LIMIT 1")).fetchone()
    if row:
        print(f"✓ Ya existe un admin: [{row[0]}] {row[1]} <{row[2]}>")
        print("  No se creó nada nuevo.")
        sys.exit(0)

    # 3. Crear tienda
    tienda_row = conn.execute(
        text("INSERT INTO tiendas (nombre, activa) VALUES (:nombre, TRUE) RETURNING id"),
        {"nombre": NOMBRE_TIENDA}
    ).fetchone()
    tienda_id = tienda_row[0]
    conn.commit()
    print(f"✓ Tienda creada: [{tienda_id}] {NOMBRE_TIENDA}")

    # 4. Crear admin
    pw_hash = pwd_ctx.hash(ADMIN_PASS)
    user_row = conn.execute(
        text("""
            INSERT INTO usuarios (nombre, email, password_hash, rol, tienda_id, activo)
            VALUES (:nombre, :email, :pw, 'admin', :tienda_id, TRUE)
            RETURNING id
        """),
        {"nombre": ADMIN_NOMBRE, "email": ADMIN_EMAIL, "pw": pw_hash, "tienda_id": tienda_id}
    ).fetchone()
    conn.commit()
    print(f"✓ Admin creado:  [{user_row[0]}] {ADMIN_NOMBRE} <{ADMIN_EMAIL}>")
    print(f"  Contraseña:    {ADMIN_PASS}")
    print()
    print("  ⚠️  Cambia la contraseña desde el panel de usuarios después del primer login.")
