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

# La consola de Windows viene en cp1252 y el reporte lleva flechas y comillas
# angulares: sin esto el script muere al imprimir la primera fusión.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine                               # noqa: E402
from sqlalchemy.orm import sessionmaker                            # noqa: E402

# UNA sola verdad. El criterio de qué apunta a un producto, qué está archivado,
# con quién se fusiona y qué choca vive en el servicio — el mismo que sirve el
# endpoint `GET /inventario/duplicados/plan` y el que ejecuta la fusión. Este
# script es solo su cara de consola: dos copias del criterio se desincronizan, y
# acá desincronizarse significa mover ventas reales al producto equivocado.
from app.services.fusion_duplicados import (                       # noqa: E402,F401
    analizar,
    es_archivado,
    norm,
    parejas,
    referencias,
    uniques_con_producto,
)


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

    limpias, bloqueadas, total_filas = [], [], 0
    for muerto, vivo in fusionables:
        mueve, choques, bloqueos = analizar(db, muerto, vivo, refs, uniques)
        n = sum(mueve.values())
        total_filas += n
        estado = "BLOQUEA" if bloqueos else "limpia "
        print(f"[{estado}] #{muerto.id} «{muerto.nombre}»  →  #{vivo.id} «{vivo.nombre}»")
        if not mueve:
            print("    (sin historia: se puede borrar directo)")
        for t, c in sorted(mueve.items(), key=lambda x: -x[1]):
            print(f"    {c:>6} × {t}")
        # Un choque NO bloquea: la fusión sabe resolverlo (borra la fila repetida
        # del archivado). Se imprime para que se vea qué se va a descartar.
        for c in choques:
            print(f"    ~~ {c['tabla']}: {c['detalle']} → {c['resolucion']}")
        for b in bloqueos:
            print(f"    !! {b}")
        print()
        (bloqueadas if bloqueos else limpias).append((muerto, vivo))

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
    print(f"  Fusiones limpias:       {len(limpias)}")
    print(f"  Bloqueadas (a mano):    {len(bloqueadas)}")
    print(f"  Ambiguas (2+ vivos):    {len(ambiguos)}")
    print(f"  Huérfanas (0 vivos):    {len(huerfanos)}")
    print(f"  Registros a re-apuntar: {total_filas}")
    print("\nEste script NO escribió nada. La ejecución es un paso aparte:")
    print("POST /inventario/duplicados/fusionar, o el botón «Fusionar» del catálogo.")


if __name__ == "__main__":
    main()
