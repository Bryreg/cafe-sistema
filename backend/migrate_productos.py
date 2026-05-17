"""
Migracion de productos:
1. Corrige unidades: velinos, licores, sour cream (und -> g)
2. Renombra productos
3. Consolida 5 aromaticas -> 1 "Aromaticas"

Uso:
  python migrate_productos.py                  # dev (cafe_dev.db)
  python migrate_productos.py --prod           # Neon
"""
import sys, os

if "--prod" in sys.argv:
    from dotenv import load_dotenv
    load_dotenv(".env.production") if os.path.exists(".env.production") else load_dotenv(".env")
    print("DB:", os.environ.get("DATABASE_URL", "")[:60])
else:
    os.environ["DATABASE_URL"] = "sqlite:///./cafe_dev.db"
    print("DB: sqlite (dev)")

sys.path.insert(0, ".")
from app.database import SessionLocal, engine
from app.models.models import Producto, Inventario
from sqlalchemy import text

db = SessionLocal()

# ── 1. Corregir unidades ──────────────────────────────────────────────────────

UNIT_FIX = {
    "Saborizante Vainilla": "g",
    "Saborizante Canela": "g",
    "Saborizante Macadamia": "g",
    "Saborizante Frutos Amarillos": "g",
    "Saborizante Kiwi Fresa": "g",
    "Licor Baileys": "g",
    "Licor Amaretto": "g",
    "Licor Black & White": "g",
    "Sour Cream": "g",
}

for nombre, nueva_unidad in UNIT_FIX.items():
    p = db.query(Producto).filter(Producto.nombre == nombre).first()
    if p:
        p.unidad_medida = nueva_unidad
        print(f"  Unidad: {nombre} -> {nueva_unidad}")
    else:
        print(f"  [!] No encontrado: {nombre}")

# ── 2. Renombrar productos ────────────────────────────────────────────────────

RENAMES = {
    "Saborizante Vainilla":         "Velino Vainilla",
    "Saborizante Canela":           "Velino Canela",
    "Saborizante Macadamia":        "Velino Macadamia",
    "Saborizante Frutos Amarillos": "Velino Frutos Amarillos",
    "Saborizante Kiwi Fresa":       "Velino Kiwi Fresa",
    "Dedo de Queso":                "Palito de Queso",
    "Omelette Queso":               "Omelette Jamon y Queso",
    "Licor Black & White":          "Licor Whisky",
}

for viejo, nuevo in RENAMES.items():
    p = db.query(Producto).filter(Producto.nombre == viejo).first()
    if p:
        p.nombre = nuevo
        print(f"  Nombre: '{viejo}' -> '{nuevo}'")
    else:
        print(f"  [!] No encontrado para renombrar: '{viejo}'")

db.flush()

# ── 3. Consolidar aromaticas -> una sola ─────────────────────────────────────

AROM_NOMBRES = [
    "Aromatica Toronjil",
    "Aromatica Limoncillo",
    "Aromatica Cidron",
    "Aromatica Manzanilla",
    "Aromatica Hierbabuena",
    # variantes con tilde por si acaso
    "Aromática Toronjil",
    "Aromática Limoncillo",
    "Aromática Cidrón",
    "Aromática Manzanilla",
    "Aromática Hierbabuena",
]

arom_prods = db.query(Producto).filter(Producto.nombre.in_(AROM_NOMBRES)).all()
if not arom_prods:
    print("[!] No se encontraron aromaticas -- ya migradas o nombres distintos")
    # intentar buscar por LIKE
    arom_prods = db.query(Producto).filter(Producto.nombre.ilike("Arom%tica%")).all()
    if arom_prods:
        print(f"  Encontradas por LIKE: {[p.nombre for p in arom_prods]}")

if arom_prods:
    maestro = arom_prods[0]
    otros_ids = [p.id for p in arom_prods[1:]]
    maestro_id = maestro.id

    print(f"  Maestro id={maestro_id} ('{maestro.nombre}'), otros={otros_ids}")

    # Flush ORM antes de usar SQL directo
    db.commit()

    with engine.begin() as conn:
        # Inventario: sumar stock_actual donde ya existe registro del maestro
        for oid in otros_ids:
            conn.execute(text("""
                UPDATE inventario SET stock_actual = stock_actual + (
                    SELECT COALESCE(i2.stock_actual, 0)
                    FROM inventario i2
                    WHERE i2.producto_id = :oid AND i2.tienda_id = inventario.tienda_id
                )
                WHERE inventario.producto_id = :mid
                AND EXISTS (
                    SELECT 1 FROM inventario i2
                    WHERE i2.producto_id = :oid AND i2.tienda_id = inventario.tienda_id
                )
            """), {"oid": oid, "mid": maestro_id})

            # Reasignar registros de inventario sin maestro en esa tienda
            conn.execute(text("""
                UPDATE inventario SET producto_id = :mid
                WHERE producto_id = :oid
                AND NOT EXISTS (
                    SELECT 1 FROM inventario i2
                    WHERE i2.producto_id = :mid AND i2.tienda_id = inventario.tienda_id
                )
            """), {"oid": oid, "mid": maestro_id})

            # Borrar sobrantes de inventario
            conn.execute(text("DELETE FROM inventario WHERE producto_id = :oid"), {"oid": oid})

        # Todas las demas tablas: simple reasignacion
        TABLAS = [
            "conteos_fisicos_items",
            "conteos_compras_items",
            "movimientos_inventario",
            "mermas",
            "lotes_inventario",
            "facturas_compra_items",
            "pasteleria_diaria",
            "recetas_ingredientes",
            "solicitudes_pedido_items",
        ]
        for tabla in TABLAS:
            for oid in otros_ids:
                try:
                    r = conn.execute(
                        text(f"UPDATE {tabla} SET producto_id = :mid WHERE producto_id = :oid"),
                        {"mid": maestro_id, "oid": oid}
                    )
                    if r.rowcount:
                        print(f"    {tabla}: {r.rowcount} filas -> maestro")
                except Exception as e:
                    print(f"    [!] {tabla}: {e}")

        # Borrar los productos sobrantes
        for oid in otros_ids:
            conn.execute(text("DELETE FROM productos WHERE id = :id"), {"id": oid})

    # Actualizar nombre y unidad del maestro via ORM
    db = SessionLocal()
    m = db.query(Producto).filter(Producto.id == maestro_id).first()
    m.nombre = "Aromaticas"
    m.unidad_medida = "und"
    db.commit()
    print(f"  Aromaticas consolidadas. Eliminados {len(otros_ids)} productos.")
else:
    db.commit()

print("\n OK Migracion completada.")
db.close()
