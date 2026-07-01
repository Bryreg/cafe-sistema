"""Carga el inventario inicial de VIDA desde inventario_inicial.json.

- Crea/actualiza cada producto (match por nombre normalizado, idempotente).
- Setea categoría, controla_stock=True, fraccionable, envase, incluir_en_conteo (conteo diario),
  y precio_venta si el producto también se vende.
- Setea el stock SELLADO en la sede Vida. Lo ABIERTO lo llena el usuario con el dibujo (nivel).
- Crea filas de Inventario en todas las sedes (stock 0 en las demás).

Uso (Render Shell, con las env de prod):
    cd /opt/render/project/src/backend && python cargar_inventario.py            # aplica
    cd /opt/render/project/src/backend && python cargar_inventario.py --dry-run  # solo muestra
"""
import json, os, sys, re, unicodedata
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal, engine
from app.models.models import Base, Producto, Inventario, Tienda, CategoriaProductoEnum

Base.metadata.create_all(bind=engine)

DRY = "--dry-run" in sys.argv
SEDE = "Vida"
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inventario_inicial.json")

CAT = {
    "bebida": CategoriaProductoEnum.bebida,
    "pasteleria": CategoriaProductoEnum.pasteleria,
    "insumo": CategoriaProductoEnum.insumo,
    "porciones": CategoriaProductoEnum.porciones,
}

def norm(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()).strip().upper()

def run():
    data = json.load(open(DATA, encoding="utf-8"))
    db = SessionLocal()
    try:
        vida = db.query(Tienda).filter(Tienda.nombre == SEDE).first()
        if not vida:
            print(f"ERROR: no existe la sede '{SEDE}'"); return
        tiendas = db.query(Tienda).all()
        idx = {norm(p.nombre): p for p in db.query(Producto).all()}

        creados = act = 0
        for item in data:
            k = norm(item["nombre"])
            p = idx.get(k)
            if not p:
                p = Producto(nombre=item["nombre"], categoria=CAT[item["categoria"]],
                             unidad_medida=(item["envase"] or "und"), controla_stock=True)
                db.add(p); db.flush(); idx[k] = p
                creados += 1
            else:
                act += 1
            p.categoria = CAT[item["categoria"]]
            p.controla_stock = True
            p.fraccionable = bool(item["fraccionable"])
            p.envase = item["envase"]
            p.incluir_en_conteo = bool(item["diario"])
            if item.get("precio"):
                p.precio_venta = item["precio"]
            if item["fraccionable"] and item["envase"]:
                p.unidad_medida = item["envase"]
            db.flush()

            for t in tiendas:
                inv = db.query(Inventario).filter_by(producto_id=p.id, tienda_id=t.id).first()
                if not inv:
                    inv = Inventario(producto_id=p.id, tienda_id=t.id, stock_actual=0.0, stock_minimo=0.0)
                    db.add(inv)
                if t.id == vida.id:
                    inv.stock_actual = float(item["sellado"])

        if DRY:
            db.rollback()
            print(f"[DRY-RUN] {len(data)} productos ({creados} nuevos, {act} existentes). Nada commiteado.")
        else:
            db.commit()
            print(f"[OK] {len(data)} productos cargados en {SEDE} ({creados} nuevos, {act} actualizados).")
            print(f"[OK] Fraccionables: {sum(1 for i in data if i['fraccionable'])} · Conteo diario: {sum(1 for i in data if i['diario'])}")
    except Exception as e:
        db.rollback(); print("ERROR:", e); raise
    finally:
        db.close()

if __name__ == "__main__":
    run()
