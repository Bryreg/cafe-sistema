"""
Carga el MENÚ DE VENTA del POS desde menu_venta.json.

- Match por nombre normalizado (sin acentos, mayúsculas, espacios colapsados).
- Si el producto existe  -> actualiza precio_venta.
- Si no existe           -> lo crea (controla_stock=False, unidad 'und').
- NO borra ni toca productos que no estén en el menú.
- Idempotente: se puede correr varias veces.

El menú son productos terminados que se venden al cliente (cafés, malteadas,
tortas, porciones). NO controlan stock — el inventario se lleva por insumos.

Uso:
    cd backend
    # dev:
    set ENV_FILE=.env.dev && python cargar_menu_venta.py
    # producción: con las variables de entorno de prod cargadas
    python cargar_menu_venta.py

    python cargar_menu_venta.py --dry-run   # muestra qué haría, sin commitear
    python cargar_menu_venta.py --limpiar   # además, el POS muestra SOLO el menú:
                                            # oculta (precio->0) lo vendible que no esté
                                            # en menu_venta.json. No borra nada.

Recomendado en producción: primero  --dry-run --limpiar  para revisar, luego --limpiar.
"""
import sys, os, json, re, unicodedata

sys.path.append(os.path.dirname(__file__))

from app.database import SessionLocal, engine
from app.models import models  # noqa
from app.models.models import Base, Producto, CategoriaProductoEnum

Base.metadata.create_all(bind=engine)

CAT_MAP = {
    "pasteleria": CategoriaProductoEnum.pasteleria,
    "bebida":     CategoriaProductoEnum.bebida,
    "insumo":     CategoriaProductoEnum.insumo,
    "porciones":  CategoriaProductoEnum.porciones,
}

DATA_FILE = os.path.join(os.path.dirname(__file__), "menu_venta.json")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


def run(dry_run: bool = False, limpiar: bool = False):
    menu = json.load(open(DATA_FILE, encoding="utf-8"))
    db = SessionLocal()
    try:
        # Índice de productos existentes por nombre normalizado.
        existentes = db.query(Producto).all()
        idx = {}
        for p in existentes:
            idx.setdefault(norm(p.nombre), p)

        menu_norm = {norm(item["nombre"]) for item in menu}
        creados, actualizados, sin_cambio, renombrados = 0, 0, 0, 0
        for item in menu:
            nombre = item["nombre"].strip()
            precio = float(item["precio"])
            cat = CAT_MAP[item["categoria"]]
            existente = idx.get(norm(nombre))

            if existente:
                # Normaliza casing: solo renombra los que están en MAYÚSCULAS
                # (creados por una carga previa). NO pisa nombres ya bien escritos.
                if existente.nombre.isupper() and existente.nombre != nombre:
                    print(f"  R nombre  {existente.nombre} -> {nombre}")
                    existente.nombre = nombre
                    renombrados += 1
                if float(existente.precio_venta or 0) != precio:
                    print(f"  ~ precio  {nombre}: {existente.precio_venta} -> {precio}")
                    existente.precio_venta = precio
                    actualizados += 1
                else:
                    sin_cambio += 1
            else:
                print(f"  + nuevo   {nombre}  (${int(precio)})  [{item['categoria']}]")
                db.add(Producto(
                    nombre=nombre,
                    categoria=cat,
                    unidad_medida="und",
                    controla_stock=False,
                    precio_venta=precio,
                ))
                creados += 1

        # --limpiar: el POS muestra SOLO el menú. Cualquier producto vendible
        # (precio_venta > 0) que no esté en el menú se oculta (precio -> 0).
        # NO borra nada: el producto sigue existiendo para inventario.
        ocultos = 0
        if limpiar:
            for p in db.query(Producto).filter(Producto.precio_venta > 0).all():
                if norm(p.nombre) not in menu_norm:
                    print(f"  - oculta  {p.nombre} (${p.precio_venta}) -> 0")
                    p.precio_venta = 0
                    ocultos += 1

        if dry_run:
            db.rollback()
            print("\n[DRY-RUN] nada commiteado.")
        else:
            db.commit()

        vendibles = db.query(Producto).filter(Producto.precio_venta > 0).count()
        print(f"\n[OK] Creados              : {creados}")
        print(f"[OK] Nombre normalizado   : {renombrados}")
        print(f"[OK] Precio actualizado   : {actualizados}")
        print(f"[OK] Sin cambio           : {sin_cambio}")
        if limpiar:
            print(f"[OK] Ocultados (no-menu)  : {ocultos}")
        print(f"[OK] Total vendibles POS  : {vendibles}  (precio_venta > 0)")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv, limpiar="--limpiar" in sys.argv)
