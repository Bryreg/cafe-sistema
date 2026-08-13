"""Fusión de duplicados archivados: EL REPORTE. No escribe NADA.

Un duplicado archivado (ej. #1001 «Almojábanas») está fuera del inventario, del
POS, de los pedidos y de los conteos — pero NO se puede borrar, porque adentro
tiene registros que las baristas hicieron de verdad: conteos de junio, entradas
de mercancía, ventas. Borrar la fila dejaría esos registros apuntando a la nada,
y la base se niega (FK RESTRICT).

La fusión de verdad es en dos tiempos:

    1. RE-APUNTAR la historia del muerto al vivo (23 tablas la referencian)
    2. Recién entonces borrar el cascarón, ya vacío

Este script hace el paso 0: decir EXACTAMENTE qué se movería y qué chocaría, sin
tocar un solo registro. Es la condición que puso el dueño y es la correcta —
sobre datos de una cafetería que opera todos los días, el reporte se lee ANTES.

    python scripts/fusionar_duplicados_dryrun.py
    python scripts/fusionar_duplicados_dryrun.py --db sqlite:///cafe_dev.db

Beneficio que la fusión trae más allá de limpiar: hoy la historia de cada
producto está PARTIDA. Las compras de junio de almojábanas cuelgan de la fila
vieja, así que el catálogo de proveedores, la rotación y el costeo del producto
vivo no las ven. Fusionar le devuelve al producto vivo su primer mes de vida.
"""
import argparse
import os
import sys
import unicodedata
from collections import defaultdict

# La consola de Windows viene en cp1252 y el reporte lleva flechas y comillas
# angulares: sin esto el script muere al imprimir la primera fusión.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, func, select                # noqa: E402
from sqlalchemy.orm import sessionmaker                            # noqa: E402

from app.models import models as M                                 # noqa: E402


# ─── Qué apunta a un producto ────────────────────────────────────────────────

def referencias():
    """(clase, columna) de TODO lo que apunta a productos.id.

    Se descubre del mapeo, no de una lista escrita a mano: una tabla nueva con
    FK a productos entra sola en el reporte. Una lista tipeada se desactualiza
    en silencio, y acá eso significa historia que se queda huérfana."""
    out = []
    for mapper in M.Base.registry.mappers:
        cls = mapper.class_
        for col in cls.__table__.columns:
            if any(fk.target_fullname == "productos.id" for fk in col.foreign_keys):
                out.append((cls, col.name))
    return sorted(out, key=lambda t: (t[0].__tablename__, t[1]))


def uniques_con_producto():
    """Restricciones únicas que incluyen una columna de producto.

    Son las que pueden CHOCAR al re-apuntar: si la barista contó las dos filas
    el mismo día, mover una encima de la otra viola el único y la transacción
    revienta a mitad de camino. Hay que saberlo antes, no después."""
    out = []
    for mapper in M.Base.registry.mappers:
        cls = mapper.class_
        for con in cls.__table__.constraints:
            cols = [c.name for c in getattr(con, "columns", [])]
            if con.__class__.__name__ == "UniqueConstraint" and _tiene_producto(cols):
                out.append((cls, sorted(cols)))
        for idx in cls.__table__.indexes:
            cols = [c.name for c in idx.columns]
            if idx.unique and _tiene_producto(cols):
                out.append((cls, sorted(cols)))
    return out


def _tiene_producto(cols):
    return any(c in ("producto_id", "insumo_id", "sustituto_id") for c in cols)


# ─── Qué está archivado y con quién se fusiona ───────────────────────────────

def norm(nombre):
    """La misma idea que usa la vista Duplicados del catálogo: sin tildes, sin
    palabras de relleno ni unidades, en orden alfabético. «PULPA DE MANGO» y
    «Pulpa Mango» son el mismo producto escrito por dos manos distintas."""
    STOP = {"de", "la", "el", "los", "las", "con", "y", "x", "und", "unidad",
            "unidades", "para", "o", "a", "botella"}
    UNITS = {"oz", "onz", "onza", "onzas", "gr", "g", "gramos", "ml", "cc",
             "lt", "litro", "litros", "kg"}
    s = unicodedata.normalize("NFD", nombre or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    fuera = []
    for t in "".join(ch if ch.isalnum() else " " for ch in s).split():
        if t in STOP or t in UNITS:
            continue
        if t.isdigit():
            t = str(int(t))
        elif t.endswith("s") and len(t) > 4:
            t = t[:-1]
        if t and t not in STOP and t not in UNITS:
            fuera.append(t)
    return " ".join(sorted(fuera))


def es_archivado(p):
    """Fuera del POS, del conteo y del stock. La misma firma que usa el catálogo."""
    return (not p.controla_stock
            and p.incluir_en_conteo is False
            and not float(p.precio_venta or 0))


def parejas(db):
    """(muerto archivado → vivo) por nombre normalizado.

    Solo se propone fusionar cuando hay EXACTAMENTE un vivo candidato. Con dos
    vivos el script no adivina: lo reporta y sigue. Una fusión hacia el producto
    equivocado mueve ventas reales al lugar equivocado."""
    todos = db.query(M.Producto).all()
    por_clave = defaultdict(lambda: {"vivos": [], "archivados": []})
    for p in todos:
        k = norm(p.nombre)
        if not k:
            continue
        por_clave[k]["archivados" if es_archivado(p) else "vivos"].append(p)

    # TRES desenlaces, y no dos: un archivado sin ningún vivo NO es «ambiguo»,
    # es HUÉRFANO — no hay a dónde fusionarlo. Meterlos en la misma bolsa hacía
    # que el reporte dijera «más de un producto vivo» sobre casos que tienen
    # cero, que es exactamente la clase de rótulo falso que este proyecto
    # persigue en todas sus pantallas.
    fusionables, ambiguos, huerfanos = [], [], []
    for k, g in sorted(por_clave.items()):
        if not g["archivados"]:
            continue
        if len(g["vivos"]) == 1:
            for a in g["archivados"]:
                fusionables.append((a, g["vivos"][0]))
        elif not g["vivos"]:
            huerfanos.append((k, g["archivados"]))
        else:
            ambiguos.append((k, g))
    return fusionables, ambiguos, huerfanos


# ─── El reporte ──────────────────────────────────────────────────────────────

def analizar(db, muerto, vivo, refs, uniques):
    """Qué se movería y qué chocaría. SOLO CUENTA — ni un UPDATE."""
    mueve, choques = {}, []

    for cls, col in refs:
        columna = getattr(cls, col)
        n = db.query(func.count()).select_from(cls).filter(columna == muerto.id).scalar()
        if n:
            mueve[f"{cls.__tablename__}.{col}"] = n

    # Choques: para cada único que incluya producto, ¿existe ya una fila del VIVO
    # con el mismo resto de la clave? Si sí, re-apuntar viola la restricción.
    for cls, cols in uniques:
        pcol = next((c for c in cols if c in ("producto_id", "insumo_id")), None)
        if pcol is None:
            continue
        otras = [c for c in cols if c != pcol]
        filas_muerto = db.query(cls).filter(getattr(cls, pcol) == muerto.id).all()
        for fila in filas_muerto:
            q = db.query(func.count()).select_from(cls).filter(getattr(cls, pcol) == vivo.id)
            for c in otras:
                q = q.filter(getattr(cls, c) == getattr(fila, c))
            if q.scalar():
                detalle = ", ".join(f"{c}={getattr(fila, c)!r}" for c in otras) or "(sin más clave)"
                choques.append(f"{cls.__tablename__}: ya existe una fila del vivo con {detalle}")

    return mueve, choques


def main():
    ap = argparse.ArgumentParser(description="Dry-run de la fusión de duplicados. NO escribe.")
    ap.add_argument("--db", default=os.getenv("DATABASE_URL", "sqlite:///cafe_dev.db"))
    args = ap.parse_args()

    engine = create_engine(args.db)
    db = sessionmaker(bind=engine)()

    refs, uniques = referencias(), uniques_con_producto()
    print(f"Base: {args.db.split('@')[-1]}")
    print(f"Apuntan a un producto: {len(refs)} columnas en "
          f"{len({c.__tablename__ for c, _ in refs})} tablas.")
    print(f"Restricciones únicas que pueden chocar: {len(uniques)}.\n")

    fusionables, ambiguos, huerfanos = parejas(db)
    if not fusionables and not ambiguos and not huerfanos:
        print("No hay duplicados archivados para fusionar.")
        return

    limpias, conflictivas, total_filas = [], [], 0
    for muerto, vivo in fusionables:
        mueve, choques = analizar(db, muerto, vivo, refs, uniques)
        n = sum(mueve.values())
        total_filas += n
        estado = "CHOCA " if choques else "limpia"
        print(f"[{estado}] #{muerto.id} «{muerto.nombre}»  →  #{vivo.id} «{vivo.nombre}»")
        if not mueve:
            print("    (sin historia: se puede borrar directo)")
        for t, c in sorted(mueve.items(), key=lambda x: -x[1]):
            print(f"    {c:>6} × {t}")
        for c in choques:
            print(f"    !! {c}")
        print()
        (conflictivas if choques else limpias).append((muerto, vivo))

    if ambiguos:
        print("── SIN FUSIONAR: hay MÁS DE UN producto vivo con ese nombre ──")
        print("   (el script no adivina cuál es el bueno: lo elegís vos)")
        for k, g in ambiguos:
            vivos = ", ".join(f"#{p.id} «{p.nombre}»" for p in g["vivos"])
            arch = ", ".join(f"#{p.id} «{p.nombre}»" for p in g["archivados"])
            print(f"   {k}: vivos [{vivos}] · archivados [{arch}]")
        print()

    if huerfanos:
        print("── SIN FUSIONAR: archivados que NO tienen ningún vivo ──")
        print("   Productos que se dejaron de manejar (el menú viejo). No hay a")
        print("   dónde fusionarlos: su historia solo puede quedarse donde está.")
        for k, arch in huerfanos:
            print("   " + ", ".join(f"#{p.id} «{p.nombre}»" for p in arch))
        print()

    print("── RESUMEN ──")
    print(f"  Fusiones limpias:      {len(limpias)}")
    print(f"  Con choque a resolver: {len(conflictivas)}")
    print(f"  Ambiguas (2+ vivos):   {len(ambiguos)}")
    print(f"  Huérfanas (0 vivos):   {len(huerfanos)}")
    print(f"  Registros a re-apuntar: {total_filas}")
    print("\nEste script NO escribió nada. La ejecución es un paso aparte,")
    print("y solo después de que el dueño lea esto.")


if __name__ == "__main__":
    main()
