"""
Reset de datos de prueba.
Elimina toda la información transaccional y fotos de Cloudinary.
Conserva: tiendas, usuarios, productos, inventario (stock), config, plantillas.

Ejecutar desde Render Shell:
    cd /app && python reset_data.py
"""
import os, sys
sys.path.insert(0, "/app")

from app.database import SessionLocal, engine
from sqlalchemy import text

print("=" * 50)
print("  RESET DE DATOS DE PRUEBA")
print("=" * 50)

db = SessionLocal()

# ── 1. Recopilar URLs de imágenes antes de borrar ──────────────────────────
print("\n[1/3] Recopilando imágenes...")
img_urls = []
IMG_COLS = [
    ("movimientos_caja",  "imagen_url"),
    ("entregas_turno",    "imagen_url"),
    ("facturas_compra",   "imagen_soporte_url"),
    ("config_tickets",    "logo_url"),
]
for table, col in IMG_COLS:
    try:
        rows = db.execute(text(f"SELECT {col} FROM {table} WHERE {col} IS NOT NULL")).fetchall()
        found = [r[0] for r in rows if r[0]]
        img_urls.extend(found)
        print(f"  {table}.{col}: {len(found)} imágen(es)")
    except Exception as e:
        print(f"  {table}.{col}: skip ({e})")

print(f"  Total: {len(img_urls)} imágenes")

# ── 2. Eliminar imágenes de Cloudinary ─────────────────────────────────────
print("\n[2/3] Eliminando imágenes de Cloudinary...")
CLOUDINARY_URL = os.getenv("CLOUDINARY_URL", "")
if CLOUDINARY_URL and img_urls:
    try:
        import cloudinary, cloudinary.uploader
        cloudinary.config(cloudinary_url=CLOUDINARY_URL)
        deleted = 0
        for url in img_urls:
            try:
                # Extrae public_id: .../upload/v123/folder/name.jpg → folder/name
                parts = url.split("/upload/")
                if len(parts) == 2:
                    raw = parts[1]
                    # quitar versión (v1234567/)
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
    if not CLOUDINARY_URL:
        print("  CLOUDINARY_URL no configurado — imágenes no borradas")
    else:
        print("  Sin imágenes para borrar")

# ── 3. Borrar tablas transaccionales (orden: hijos antes que padres) ────────
print("\n[3/3] Eliminando datos transaccionales...")

TABLES = [
    # POS / ventas
    "notas_credito_items",
    "notas_credito",
    "ticket_items",
    "tickets",
    # Compras
    "conteos_compras_items",
    "conteos_compras",
    "facturas_compra_items",
    "facturas_compra",
    # Recepciones y temperaturas
    "recepcion_items",
    "recepciones",
    "temperaturas_lecturas",
    # Operativas
    "rutina_eventos",
    "novedades",
    "comunicados_leidos",
    "comunicados",
    # Notificaciones
    "push_subscriptions",
    "notificaciones",
    # Auditoría
    "audit_events",
    "audit_log",
    "auditorias_limpieza_items",
    "auditorias_limpieza",
    "auditorias_inventario_items",
    "auditorias_inventario",
    # Limpieza y mantenimiento
    "limpieza_semanal",
    "mantenimientos",
    "checklist_diario",
    # Inventario
    "consignaciones",
    "pasteleria_diaria",
    "entregas_turno",
    "solicitudes_sencilla",
    "solicitudes_pedido_items",
    "solicitudes_pedido",
    "mermas",
    "conteos_fisicos_items",
    "conteos_fisicos",
    "ventas_diarias",
    "inventarios_mensuales_items",
    "inventarios_mensuales",
    "movimientos_inventario",
    "lotes_inventario",
    "movimientos_caja",
    # Turnos y baristas
    "turno_baristas",
    "caja_turnos",
    "dias_operativos",
]

with engine.connect() as conn:
    total_rows = 0
    for table in TABLES:
        try:
            result = conn.execute(text(f"DELETE FROM {table}"))
            conn.commit()
            n = result.rowcount
            total_rows += n
            if n > 0:
                print(f"  ✓ {table}: {n} fila(s)")
        except Exception as e:
            conn.rollback()
            print(f"  ✗ {table}: {e}")

print(f"\n  Total filas eliminadas: {total_rows}")

# ── Resetear stock a cero ──────────────────────────────────────────────────
try:
    with engine.connect() as conn:
        result = conn.execute(text("UPDATE inventario SET stock_actual = 0"))
        conn.commit()
    print(f"  ✓ inventario: stock reseteado a 0 ({result.rowcount} productos)")
except Exception as e:
    print(f"  inventario stock: {e}")

# ── Limpiar logo del config_ticket (foto de prueba) ────────────────────────
try:
    with engine.connect() as conn:
        conn.execute(text("UPDATE config_tickets SET logo_url = NULL"))
        conn.commit()
    print("  ✓ config_tickets.logo_url limpiado")
except Exception as e:
    print(f"  config_tickets logo: {e}")

db.close()
print("\n" + "=" * 50)
print("  RESET COMPLETADO")
print("=" * 50)
