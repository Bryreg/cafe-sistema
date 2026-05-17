"""
fix_stock_values.py
Corrige los stock_actual del inventario: redondea decimales y asigna
valores realistas a productos en gramos que tienen cantidades absurdas (<50g).

Uso:
  python fix_stock_values.py          # dev
  python fix_stock_values.py --prod   # Neon
"""
import os, sys, random

if "--prod" in sys.argv:
    from dotenv import load_dotenv
    load_dotenv(".env.production") if os.path.exists(".env.production") else load_dotenv(".env")
    print("DB:", os.environ.get("DATABASE_URL", "")[:60])
else:
    os.environ["DATABASE_URL"] = "sqlite:///./cafe_dev.db"
    print("DB: sqlite (dev)")

sys.path.insert(0, ".")
from app.database import SessionLocal
from app.models.models import Inventario, Producto

rng = random.Random(99)

def realistic_qty(p) -> int:
    u  = p.unidad_medida
    nb = p.nombre.lower()
    c  = p.categoria.value if hasattr(p.categoria, "value") else str(p.categoria)
    if u == "g":
        if "cafe" in nb or "caf" in nb:      return rng.randint(1000, 6000)
        if "velino" in nb or "saborizante" in nb: return rng.randint(500, 1800)
        if "polvo" in nb:                    return rng.randint(1500, 5000)
        if "condensada" in nb:               return rng.randint(800, 4000)
        if "salsa" in nb:                    return rng.randint(300, 3500)
        if "milo" in nb:                     return rng.randint(500, 2500)
        if "oreo" in nb or "galleta" in nb:  return rng.randint(300, 1500)
        if "azucar" in nb or "ázuc" in nb: return rng.randint(500, 5000)
        if "chai" in nb:                     return rng.randint(300, 900)
        if "licor" in nb:                    return rng.randint(300, 1500)
        if "sour" in nb or "crema" in nb:    return rng.randint(100, 500)
        if "jabon" in nb or "jab" in nb:     return rng.randint(200, 1000)
        if "limpiapisos" in nb or "blanqueador" in nb: return rng.randint(500, 3000)
        if "detergente" in nb:               return rng.randint(200, 1500)
        if "papel" in nb or "vinilpel" in nb or "aluminio" in nb: return rng.randint(100, 800)
        return rng.randint(200, 2000)
    elif c == "pasteleria":
        return rng.randint(0, 60)
    else:
        return rng.randint(10, 100)


db = SessionLocal()
rows = db.query(Inventario, Producto).join(Producto, Inventario.producto_id == Producto.id).all()

fixed = 0
for inv, p in rows:
    v = inv.stock_actual
    u = p.unidad_medida

    if u == "g" and v > 0 and v < 50:
        # Valor absurdo para gramos: reemplazar con cantidad realista
        inv.stock_actual = realistic_qty(p)
        print(f"  RESET  {p.nombre:35s} {v:.1f}g -> {inv.stock_actual}g")
        fixed += 1
    elif v != int(v):
        # Decimal en cualquier unidad: redondear
        inv.stock_actual = round(v)
        print(f"  ROUND  {p.nombre:35s} {v} -> {int(inv.stock_actual)}")
        fixed += 1

db.commit()
print(f"\nOK  {fixed} valores corregidos.")
db.close()
