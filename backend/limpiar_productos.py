"""Borra TODOS los productos y sus filas dependientes para rearmar el catálogo desde cero.
Seguro DESPUÉS del reset (no hay movimientos/ventas). Corre en Render Shell antes de recargar.

Uso:
    cd /opt/render/project/src/backend && python limpiar_productos.py --si    # ejecuta
    (sin --si solo muestra cuántos borraría)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.database import SessionLocal
from sqlalchemy import text

GO = "--si" in sys.argv
db = SessionLocal()

# TODAS las tablas que referencian producto_id — borrar hijos antes que productos.
DEP = [
    "ticket_items", "notas_credito_items",
    "recetas_ingredientes", "recetas",
    "movimientos_inventario", "lotes_inventario",
    "conteos_fisicos_items", "conteos_compras_items", "inventarios_mensuales_items",
    "auditorias_inventario_items", "facturas_compra_items",
    "pasteleria_diaria", "mermas", "solicitudes_pedido_items",
    "inventario",
]

try:
    n_prod = db.execute(text("SELECT COUNT(*) FROM productos")).scalar()
    print(f"Productos actuales: {n_prod}")
    if not GO:
        print("DRY: agregá --si para borrar productos + dependientes.")
    else:
        for t in DEP:
            try:
                r = db.execute(text(f"DELETE FROM {t}"))
                db.commit()
                if r.rowcount:
                    print(f"  - {t}: {r.rowcount}")
            except Exception as e:
                db.rollback()
                print(f"  (skip) {t}: {str(e)[:80]}")
        try:
            r = db.execute(text("DELETE FROM productos"))
            db.commit()
            print(f"[OK] productos borrados: {r.rowcount}")
        except Exception as e:
            db.rollback()
            print(f"[ERROR] no se pudieron borrar productos — una tabla los referencia:")
            print(f"        {str(e)[:200]}")
            print("        Pegame este error y agrego esa tabla al borrado.")
finally:
    db.close()
