"""
Reset SOLO de ventas y turnos — empezar la operación de caja desde 0.

Borra: ventas (tickets, notas crédito, ventas diarias) y todo lo atado al turno
(cuadres/entregas, movimientos de caja, consignaciones, conteos de apertura/cierre,
baristas del turno, turnos y días operativos).

CONSERVA: productos, inventario (STOCK), lotes, movimientos de inventario, facturas
de compra, mermas, solicitudes, novedades, rutinas, comunicados, auditorías, checklist,
pastelería, inventarios mensuales, configuración del ticket (y su logo), usuarios y sedes.

Ejecutar desde Render Shell:
    cd /opt/render/project/src/backend && python reset_ventas_turnos.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal, engine
from sqlalchemy import text

print("=" * 52)
print("  RESET DE VENTAS Y TURNOS (conserva inventario)")
print("=" * 52)

db = SessionLocal()

# ── 1. Recopilar imágenes de las filas que se van a borrar ──────────────────
print("\n[1/3] Recopilando imágenes de caja...")
img_urls = []
IMG_COLS = [
    ("movimientos_caja", "imagen_url"),
    ("entregas_turno",   "imagen_url"),
    ("consignaciones",   "imagen_url"),
]
for table, col in IMG_COLS:
    try:
        rows = db.execute(text(f"SELECT {col} FROM {table} WHERE {col} IS NOT NULL")).fetchall()
        found = [r[0] for r in rows if r[0]]
        img_urls.extend(found)
        print(f"  {table}.{col}: {len(found)} imagen(es)")
    except Exception as e:
        print(f"  {table}.{col}: skip ({str(e)[:60]})")
print(f"  Total: {len(img_urls)} imágenes")

# ── 2. Borrar esas imágenes de Cloudinary (opcional) ────────────────────────
print("\n[2/3] Eliminando imágenes de Cloudinary...")
CLOUDINARY_URL = os.getenv("CLOUDINARY_URL", "")
if CLOUDINARY_URL and img_urls:
    try:
        import cloudinary, cloudinary.uploader
        cloudinary.config(cloudinary_url=CLOUDINARY_URL)
        deleted = 0
        for url in img_urls:
            try:
                parts = url.split("/upload/")
                if len(parts) == 2:
                    raw = parts[1]
                    if raw.startswith("v") and "/" in raw:
                        raw = raw.split("/", 1)[1]
                    public_id = raw.rsplit(".", 1)[0]
                    cloudinary.uploader.destroy(public_id)
                    deleted += 1
            except Exception as ex:
                print(f"    no se pudo borrar {url}: {ex}")
        print(f"  {deleted}/{len(img_urls)} imágenes eliminadas")
    except ImportError:
        print("  cloudinary no disponible — imágenes no borradas")
else:
    print("  Sin CLOUDINARY_URL o sin imágenes — se omite")

# ── 3. Borrar SOLO ventas + turnos (hijos antes que padres) ─────────────────
print("\n[3/3] Eliminando ventas y turnos...")

TABLES = [
    # Ventas (POS) y notas de crédito
    "notas_credito_items",
    "notas_credito",
    "ticket_items",
    "tickets",
    "ventas_diarias",
    # Caja atada al turno
    "movimientos_caja",
    "entregas_turno",
    "consignaciones",
    "conteos_fisicos_items",
    "conteos_fisicos",
    # Turnos
    "turno_baristas",
    "caja_turnos",
    "dias_operativos",
]

with engine.connect() as conn:
    total = 0
    for table in TABLES:
        try:
            r = conn.execute(text(f"DELETE FROM {table}"))
            conn.commit()
            if r.rowcount:
                print(f"  - {table}: {r.rowcount}")
            total += r.rowcount
        except Exception as e:
            conn.rollback()
            print(f"  (skip) {table}: {str(e)[:70]}")
    print(f"\n  Total filas eliminadas: {total}")

db.close()
print("\n" + "=" * 52)
print("  LISTO. Ventas y turnos en 0; inventario intacto.")
print("=" * 52)
