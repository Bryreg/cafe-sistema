"""
Carga los COMBOS del POS (precio fijo, grupos de opciones) — solo sede Vida.

- Match por nombre normalizado (sin acentos, mayúsculas, espacios colapsados),
  igual que cargar_menu_venta.py.
- Si el combo existe  -> actualiza precio/orden/activo y sincroniza su estructura.
- Si no existe        -> lo crea junto con su producto SOMBRA (precio_venta=0,
  controla_stock=False: la línea del ticket apunta a él, pero NO aparece en la
  grilla del POS ni descuenta stock).
- Los PRODUCTOS componentes deben existir en la DB: si falta alguno, el script
  falla con la lista de faltantes (no los inventa).
- Idempotente: correrlo dos veces no duplica nada.

Uso:
    cd backend
    # dev:
    set ENV_FILE=.env.dev && python cargar_combos.py
    # producción: con las variables de entorno de prod cargadas
    python cargar_combos.py

    python cargar_combos.py --dry-run   # muestra qué haría, sin commitear
"""
import sys, os, re, unicodedata

sys.path.append(os.path.dirname(__file__))

from app.models import models  # noqa
from app.models.models import (
    Producto, Tienda, CategoriaProductoEnum,
    Combo, ComboGrupo, ComboOpcion, ComboOpcionProducto, ComboTienda,
)

TIENDA_COMBOS = "Vida"   # los combos SOLO están disponibles en esta sede

# Estructura: cada opción lista sus productos reales (nombre, cantidad).
# Una opción puede componerse de VARIOS productos (ej. "Americano Grande" =
# Americano Medium + Bebida Agrandada) y un grupo con UNA sola opción es fijo
# (se auto-selecciona, ej. las bebidas del Combo 03).
COMBOS = [
    {
        "nombre": "Combo 01",
        "precio": 9900,
        "orden": 1,
        "grupos": [
            {"nombre": "Bebida", "opciones": [
                {"nombre": "Americano Medium", "productos": [("Americano Medium", 1)]},
                {"nombre": "Cafe con Leche", "productos": [("Cafe con Leche", 1)]},
            ]},
            {"nombre": "Acompañamiento", "opciones": [
                {"nombre": "Almojabanas", "productos": [("Almojabanas", 1)]},
                {"nombre": "Croissant Mantequilla", "productos": [("Croissant Mantequilla", 1)]},
            ]},
        ],
    },
    {
        "nombre": "Combo 02",
        "precio": 15900,
        "orden": 2,
        "grupos": [
            {"nombre": "Bebida", "opciones": [
                {"nombre": "Cafe Latte", "productos": [("Cafe Latte", 1)]},
                # Opción compuesta: DOS productos reales detrás de un solo display
                {"nombre": "Americano Grande", "productos": [
                    ("Americano Medium", 1), ("Bebida Agrandada", 1)]},
            ]},
            {"nombre": "Acompañamiento", "opciones": [
                {"nombre": "Pastel de Pollo", "productos": [("Pastel de Pollo", 1)]},
                {"nombre": "Esponjado de Queso", "productos": [("Esponjado de Queso", 1)]},
            ]},
        ],
    },
    {
        "nombre": "Combo 03",
        "precio": 27900,
        "orden": 3,
        "grupos": [
            # Grupo FIJO: una sola opción → sin elección, ×2 cappuccinos
            {"nombre": "Bebidas", "opciones": [
                {"nombre": "Cappuccino Tradicional Medium x2", "productos": [
                    ("Cappuccino Tradicional Medium", 2)]},
            ]},
            {"nombre": "Torta", "opciones": [
                {"nombre": "Torta Naranja", "productos": [("Torta Naranja", 1)]},
                {"nombre": "Torta Chocolate", "productos": [("Torta Chocolate", 1)]},
            ]},
        ],
    },
]


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


def run(dry_run: bool = False, db=None):
    """db=None → sesión propia contra la DB configurada (create_all incluido).
    Con `db` explícito (tests) usa esa sesión y no toca el engine global."""
    own_session = db is None
    if own_session:
        from app.database import SessionLocal, engine
        models.Base.metadata.create_all(bind=engine)
        db = SessionLocal()
    try:
        productos_idx = {norm(p.nombre): p for p in db.query(Producto).all()}

        # Validar que TODOS los productos componentes existan (no se inventan)
        referenciados = {
            nombre
            for cdef in COMBOS
            for gdef in cdef["grupos"]
            for odef in gdef["opciones"]
            for nombre, _ in odef["productos"]
        }
        faltantes = sorted(n for n in referenciados if norm(n) not in productos_idx)
        if faltantes:
            raise ValueError(
                "Productos NO encontrados en la DB (crearlos primero o corregir el nombre): "
                + ", ".join(faltantes)
            )

        # Un combo sin grupos (o con grupos sin opciones) sería vendible a precio
        # completo sin entregar ni descontar nada — se aborta antes de crear.
        sin_grupos = sorted(
            cdef["nombre"] for cdef in COMBOS
            if not cdef.get("grupos") or any(not g.get("opciones") for g in cdef["grupos"])
        )
        if sin_grupos:
            raise ValueError(
                "Combos sin grupos de opciones definidos (o con grupos vacíos): "
                + ", ".join(sin_grupos)
            )

        tiendas_idx = {norm(t.nombre): t for t in db.query(Tienda).all()}
        tienda = tiendas_idx.get(norm(TIENDA_COMBOS))
        if not tienda:
            raise ValueError(f"Tienda '{TIENDA_COMBOS}' no encontrada en la DB")

        combos_idx = {norm(c.nombre): c for c in db.query(Combo).all()}

        # Un producto REAL con el nombre de un combo NO se adopta como sombra:
        # la sombra debe ser inerte (precio_venta=0, controla_stock=False).
        conflictos = []
        for cdef in COMBOS:
            if norm(cdef["nombre"]) in combos_idx:
                continue  # combo ya existente: su sombra se validó al crearse
            p = productos_idx.get(norm(cdef["nombre"]))
            if p is not None and (float(p.precio_venta or 0) > 0 or p.controla_stock):
                conflictos.append(
                    f"'{cdef['nombre']}' (producto id={p.id}, precio_venta={p.precio_venta}, "
                    f"controla_stock={p.controla_stock})"
                )
        if conflictos:
            raise ValueError(
                "Producto REAL en colisión de nombre con un combo — no se adopta como "
                "sombra (renombrar el combo o el producto): " + "; ".join(conflictos)
            )

        creados, actualizados, sin_cambio = 0, 0, 0

        for cdef in COMBOS:
            combo = combos_idx.get(norm(cdef["nombre"]))
            precio = float(cdef["precio"])

            if combo is None:
                # Producto sombra para la línea del ticket (precio 0: invisible en la grilla)
                sombra = productos_idx.get(norm(cdef["nombre"]))
                if sombra is None:
                    sombra = Producto(
                        nombre=cdef["nombre"],
                        # Inerte para la grilla (precio 0); analytics la ignora vía Combo.producto_id
                        categoria=CategoriaProductoEnum.bebida,
                        unidad_medida="und",
                        controla_stock=False,
                        incluir_en_conteo=False,
                        precio_venta=0,
                    )
                    db.add(sombra)
                    db.flush()
                    productos_idx[norm(sombra.nombre)] = sombra
                combo = Combo(nombre=cdef["nombre"], precio_venta=precio,
                              activo=True, orden=cdef["orden"], producto_id=sombra.id)
                db.add(combo)
                db.flush()
                combos_idx[norm(combo.nombre)] = combo
                print(f"  + combo   {combo.nombre}  (${int(precio)})")
                creados += 1
            else:
                cambio = False
                if float(combo.precio_venta or 0) != precio:
                    print(f"  ~ precio  {combo.nombre}: {combo.precio_venta} -> {precio}")
                    combo.precio_venta = precio
                    cambio = True
                if combo.orden != cdef["orden"]:
                    combo.orden = cdef["orden"]
                    cambio = True
                if not combo.activo:
                    combo.activo = True
                    cambio = True
                if cambio:
                    actualizados += 1
                else:
                    sin_cambio += 1

            # ── Sincronizar grupos/opciones/productos (match por nombre normalizado)
            grupos_db = {norm(g.nombre): g for g in combo.grupos}
            grupos_def = set()
            for gi, gdef in enumerate(cdef["grupos"]):
                grupos_def.add(norm(gdef["nombre"]))
                grupo = grupos_db.get(norm(gdef["nombre"]))
                if grupo is None:
                    grupo = ComboGrupo(combo_id=combo.id, nombre=gdef["nombre"], orden=gi)
                    db.add(grupo)
                    db.flush()
                    print(f"    + grupo   {combo.nombre} / {grupo.nombre}")
                else:
                    grupo.orden = gi

                opciones_db = {norm(o.nombre): o for o in grupo.opciones}
                opciones_def = set()
                for oi, odef in enumerate(gdef["opciones"]):
                    opciones_def.add(norm(odef["nombre"]))
                    opcion = opciones_db.get(norm(odef["nombre"]))
                    if opcion is None:
                        opcion = ComboOpcion(grupo_id=grupo.id, nombre=odef["nombre"], orden=oi)
                        db.add(opcion)
                        db.flush()
                        print(f"      + opcion  {grupo.nombre} / {opcion.nombre}")
                    else:
                        opcion.orden = oi

                    # Productos de la opción: upsert por producto_id, borrar sobrantes
                    deseados = {
                        productos_idx[norm(nombre)].id: cant
                        for nombre, cant in odef["productos"]
                    }
                    existentes = {op.producto_id: op for op in opcion.productos}
                    for pid, op in existentes.items():
                        if pid not in deseados:
                            db.delete(op)
                    for pid, cant in deseados.items():
                        op = existentes.get(pid)
                        if op is None:
                            db.add(ComboOpcionProducto(
                                opcion_id=opcion.id, producto_id=pid, cantidad=cant))
                        elif op.cantidad != cant:
                            op.cantidad = cant

                # Opciones que ya no están en la definición → fuera
                for key, opcion in opciones_db.items():
                    if key not in opciones_def:
                        print(f"      - opcion  {grupo.nombre} / {opcion.nombre} (retirada)")
                        db.delete(opcion)

            # Grupos que ya no están en la definición → fuera
            for key, grupo in grupos_db.items():
                if key not in grupos_def:
                    print(f"    - grupo   {combo.nombre} / {grupo.nombre} (retirado)")
                    db.delete(grupo)

            # ── Disponibilidad: SOLO la sede Vida
            asociado = db.query(ComboTienda).filter(
                ComboTienda.combo_id == combo.id,
                ComboTienda.tienda_id == tienda.id,
            ).first()
            if not asociado:
                db.add(ComboTienda(combo_id=combo.id, tienda_id=tienda.id))
                print(f"    + tienda  {combo.nombre} -> {tienda.nombre}")

        if dry_run:
            db.rollback()
            print("\n[DRY-RUN] nada commiteado.")
        else:
            db.commit()

        print(f"\n[OK] Combos creados      : {creados}")
        print(f"[OK] Combos actualizados : {actualizados}")
        print(f"[OK] Sin cambio          : {sin_cambio}")
        print(f"[OK] Disponibles en      : {tienda.nombre}")

    except Exception:
        db.rollback()
        raise
    finally:
        if own_session:
            db.close()


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
