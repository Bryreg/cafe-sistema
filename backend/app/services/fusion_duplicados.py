"""Fusión de duplicados archivados: re-apuntar la historia y borrar el cascarón.

Un duplicado archivado (ej. #33 «Pastel Queso») está fuera del inventario, del
POS, de los pedidos y de los conteos — pero NO se puede borrar, porque adentro
tiene registros que las baristas hicieron de verdad: conteos de junio, entradas
de mercancía, ventas. Borrar la fila dejaría esos registros apuntando a la nada.

La fusión es en dos tiempos:

    1. RE-APUNTAR la historia del muerto al vivo (25 columnas en 23 tablas)
    2. Recién entonces borrar el cascarón, ya vacío

Este módulo es LA ÚNICA VERDAD de esa operación: el reporte (`plan`), la
ejecución (`fusionar`) y el script de consola `scripts/fusionar_duplicados_dryrun.py`
salen todos de acá. Dos copias del mismo criterio se desincronizan, y acá
desincronizarse significa mover ventas reales al producto equivocado.

Lo que este módulo NO hace, por diseño:
  · no fusiona dos productos VIVOS (el muerto tiene que estar archivado);
  · no toca el producto sombra de un combo (tiene la firma exacta de un
    archivado y fusionarlo movería el combo a un producto real del POS);
  · no borra un archivado que tiene historia, ni con la bandera puesta;
  · no inventa ni suma stock: si un choque de inventario traería mercancía,
    aborta ese par y lo reporta.
"""
import unicodedata
from collections import defaultdict

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.models import Combo, Producto, ProductoAlias
from app.services import audit


# ─── Qué apunta a un producto ────────────────────────────────────────────────

_COLS_PRODUCTO = ("producto_id", "insumo_id", "sustituto_id")


def referencias():
    """(clase, columna) de TODO lo que apunta a productos.id.

    Se descubre del mapeo, no de una lista escrita a mano: una tabla nueva con
    FK a productos entra sola en el reporte Y en la fusión. Una lista tipeada se
    desactualiza en silencio, y acá eso significa historia que se queda
    huérfana o una fusión que deja referencias colgando."""
    from app.models import models as M
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
    from app.models import models as M
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
    return any(c in _COLS_PRODUCTO for c in cols)


# ─── Estrategia POR TABLA frente a un choque de único ────────────────────────
#
# Re-apuntar a ciegas viola los únicos. Por cada tabla con un único que incluye
# producto se decide A MANO qué pasa cuando el VIVO ya tiene la fila gemela:
#
#   "borrar"         la fila del muerto es información REPETIDA: la misma
#                    membresía, la misma línea de receta, la misma verificación
#                    del mismo conteo. Manda la del vivo, que es la que el
#                    sistema usa hoy. El contenido de la fila borrada queda
#                    escrito en la auditoría, así que el dato no se pierde.
#   "borrar_si_vacio" la fila del muerto es un CASILLERO de stock, no un
#                    registro que alguien escribió. Con stock 0 no aporta nada y
#                    se borra. Con stock ≠ 0 se ABORTA el par: sumar dos stocks
#                    en silencio inventaría mercancía que nadie contó.
#   "abortar"        la fila NO es una repetición sino una configuración entera
#                    (un combo con sus grupos, opciones y sedes). Borrarla
#                    destruiría trabajo de una persona: se aborta y se reporta.
#
# El default para una tabla desconocida es "abortar": si mañana alguien agrega
# un único nuevo con producto_id, la fusión se planta y pide una decisión en vez
# de borrar filas por su cuenta. El test `test_toda_tabla_con_unique_tiene_una_
# estrategia_decidida` exige que ese default nunca se use en silencio.
ESTRATEGIA_CHOQUE: dict[str, str] = {
    "inventario":            "borrar_si_vacio",
    "producto_insumos":      "borrar",
    "producto_desechables":  "borrar",
    "combo_opcion_productos": "borrar",
    "conteo_verificaciones": "borrar",
    "combos":                "abortar",
}
ESTRATEGIA_DEFECTO = "abortar"


class FusionAbortada(Exception):
    """Este par no se fusiona. Los demás siguen su curso."""


# ─── Clasificación de productos ──────────────────────────────────────────────

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


def es_combo_sombra(db: Session, producto_id: int) -> bool:
    """¿Este producto es la SOMBRA de un combo?

    El producto sombra de un combo se crea con precio 0, sin control de stock y
    fuera del conteo: la firma EXACTA de un archivado (ver cargar_combos.py). No
    es basura — es la fila a la que apunta cada línea de ticket del combo.
    Fusionarlo mandaría el combo a un producto real del POS, y borrarlo como
    «huérfano vacío» dejaría el combo sin línea de venta."""
    return db.query(Combo.id).filter(Combo.producto_id == producto_id).first() is not None


def parejas(db: Session):
    """(muerto archivado → vivo) por nombre normalizado.

    Solo se propone fusionar cuando hay EXACTAMENTE un vivo candidato. Con dos
    vivos no se adivina: se reporta y sigue. Una fusión hacia el producto
    equivocado mueve ventas reales al lugar equivocado.

    TRES desenlaces, y no dos: un archivado sin ningún vivo NO es «ambiguo», es
    HUÉRFANO — no hay a dónde fusionarlo."""
    todos = db.query(Producto).all()
    por_clave = defaultdict(lambda: {"vivos": [], "archivados": []})
    for p in todos:
        k = norm(p.nombre)
        if not k:
            continue
        por_clave[k]["archivados" if es_archivado(p) else "vivos"].append(p)

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


# ─── Lectura: qué hay colgando de un producto ────────────────────────────────

def historia(db: Session, producto_id: int, refs=None) -> dict:
    """{'tabla.columna': filas} de todo lo que apunta a este producto. Solo cuenta."""
    refs = refs if refs is not None else referencias()
    out = {}
    for cls, col in refs:
        n = (db.query(func.count()).select_from(cls)
             .filter(getattr(cls, col) == producto_id).scalar())
        if n:
            out[f"{cls.__tablename__}.{col}"] = n
    return out


def casilleros_inertes(db: Session, producto_id: int) -> list:
    """Filas de `inventario` en 0 y sin ningún umbral configurado.

    Al dar de alta un producto el sistema le crea una fila por sede. Esa fila es
    un CASILLERO, no algo que alguien escribió: mientras siga en 0 y sin
    mínimo/crítico/ideal, nadie la tocó. Distinguirla importa porque si no, el
    reporte le dice al dueño «no puedo borrarlo, tiene historia» sobre productos
    que no tienen absolutamente nada — el rótulo falso que este proyecto
    persigue en todas sus pantallas. Un stock ≠ 0 o un umbral puesto a mano sí
    son un registro y el producto se conserva."""
    from app.models.models import Inventario
    campos = ("stock_actual", "stock_minimo", "stock_ideal", "stock_critico")
    return [f for f in db.query(Inventario).filter(Inventario.producto_id == producto_id)
            if all(round(float(getattr(f, c) or 0), 3) == 0 for c in campos)]


def ancla(db: Session, producto_id: int, refs=None) -> dict:
    """Qué IMPIDE de verdad borrar este producto: su historia, sin casilleros."""
    refs = refs if refs is not None else referencias()
    out = historia(db, producto_id, refs)
    inertes = len(casilleros_inertes(db, producto_id))
    if inertes:
        restantes = out.get("inventario.producto_id", 0) - inertes
        if restantes > 0:
            out["inventario.producto_id"] = restantes
        else:
            out.pop("inventario.producto_id", None)
    return out


def analizar(db: Session, muerto, vivo, refs, uniques):
    """Qué se movería, qué chocaría y qué BLOQUEA. SOLO CUENTA — ni un UPDATE.

    Devuelve (mueve, choques, bloqueos):
      · mueve    {'tabla.columna': filas} que se re-apuntarían
      · choques  filas del muerto que la fusión resolvería sola (y cómo)
      · bloqueos razones por las que este par NO se puede ejecutar
    """
    mueve = historia(db, muerto.id, refs)
    choques, bloqueos = [], []

    if es_combo_sombra(db, muerto.id):
        bloqueos.append("es el producto sombra de un combo: fusionarlo movería el combo")
    if not es_archivado(muerto):
        bloqueos.append("el producto a fusionar no está archivado")

    # STOCK: la guarda va sobre TODAS las filas de inventario del archivado, no
    # solo sobre las que chocan. La primera versión era asimétrica —abortaba solo
    # si el vivo YA tenía casillero en esa sede— así que en el caso contrario la
    # fila con stock se re-apuntaba y el vivo heredaba mercancía que nadie contó,
    # con el plan diciendo «seguro» y sin una palabra de stock. No es teórico: en
    # la base hay archivados con 6, 10, 15 y 17 unidades. Mercancía sin contar no
    # se mueve en silencio por ningún camino.
    from app.models.models import Inventario as _Inv
    for inv in db.query(_Inv).filter(_Inv.producto_id == muerto.id):
        if _stock_de(inv) != 0:
            bloqueos.append(
                f"inventario: el archivado tiene stock {_stock_de(inv):g} en la sede "
                f"{inv.tienda_id} — mover mercancía que nadie contó al producto vivo "
                f"inventaría existencias. Ajustá ese stock a 0 antes de fusionar.")

    for cls, cols in uniques:
        estrategia = ESTRATEGIA_CHOQUE.get(cls.__tablename__, ESTRATEGIA_DEFECTO)
        for fila, _clave in _filas_que_chocan(db, cls, cols, muerto.id, vivo.id):
            detalle = _detalle_fila(cls, cols, fila)
            if estrategia == "borrar":
                choques.append({"tabla": cls.__tablename__, "detalle": detalle,
                                "resolucion": "se borra la fila repetida del archivado"})
            elif estrategia == "borrar_si_vacio":
                if _stock_de(fila) == 0:
                    choques.append({"tabla": cls.__tablename__, "detalle": detalle,
                                    "resolucion": "la fila del archivado está en 0: se borra"})
                else:
                    bloqueos.append(
                        f"{cls.__tablename__}: el archivado tiene stock {_stock_de(fila):g} "
                        f"({detalle}) y el vivo ya tiene su fila — sumarlos inventaría mercancía")
            else:
                bloqueos.append(f"{cls.__tablename__}: el vivo ya tiene su fila ({detalle}) "
                                f"y no es una repetición que se pueda descartar")

    for a in db.query(ProductoAlias).filter(ProductoAlias.producto_id == muerto.id):
        gemelo = (db.query(ProductoAlias)
                  .filter(ProductoAlias.alias_normalizado == a.alias_normalizado,
                          ProductoAlias.producto_id == vivo.id).first())
        if gemelo is not None:
            choques.append({"tabla": "producto_aliases",
                            "detalle": f"alias «{a.alias_original}»",
                            "resolucion": "el vivo ya tiene ese alias: se borra el del archivado"})

    return mueve, choques, bloqueos


def _filas_que_chocan(db: Session, cls, cols, muerto_id: int, vivo_id: int):
    """Filas del muerto cuya clave única, ya re-apuntada, YA EXISTE en el vivo.

    Ojo con `producto_insumos` y `producto_desechables`: su único tiene DOS
    columnas de producto (producto_id e insumo_id) y las dos se re-apuntan, así
    que el choque hay que calcularlo sobre la clave COMPLETA ya traducida, no
    sobre una sola columna."""
    pcols = [c for c in cols if c in _COLS_PRODUCTO]
    if not pcols:
        return
    filtro = or_(*[getattr(cls, c) == muerto_id for c in pcols])
    for fila in db.query(cls).filter(filtro).all():
        clave = {}
        for c in cols:
            v = getattr(fila, c)
            clave[c] = vivo_id if (c in pcols and v == muerto_id) else v
        q = db.query(cls).filter(*[getattr(cls, c) == clave[c] for c in cols])
        gemela = q.first()
        if gemela is not None and gemela.id != fila.id:
            yield fila, clave


def _detalle_fila(cls, cols, fila):
    otras = [c for c in cols if c not in _COLS_PRODUCTO]
    return ", ".join(f"{c}={getattr(fila, c)!r}" for c in otras) or "(sin más clave)"


def _stock_de(fila):
    return round(float(getattr(fila, "stock_actual", 0) or 0), 3)


# ─── EL PLAN (read-only) ─────────────────────────────────────────────────────

def plan(db: Session) -> dict:
    """El reporte completo. NO escribe una sola fila.

    Es el mismo dry-run del script, servido como dato para que se pueda leer
    desde la app y desde producción sin abrir una consola."""
    refs, uniques = referencias(), uniques_con_producto()
    fusionables_raw, ambiguos_raw, huerfanos_raw = parejas(db)

    fusionables = []
    for muerto, vivo in fusionables_raw:
        mueve, choques, bloqueos = analizar(db, muerto, vivo, refs, uniques)
        fusionables.append({
            "muerto": {"id": muerto.id, "nombre": muerto.nombre},
            "vivo": {"id": vivo.id, "nombre": vivo.nombre},
            "mueve": mueve,
            "total_filas": sum(mueve.values()),
            "choques": choques,
            "bloqueos": bloqueos,
            "seguro": not bloqueos,
        })

    ambiguos = [{
        "clave": k,
        "vivos": [{"id": p.id, "nombre": p.nombre} for p in g["vivos"]],
        "archivados": [{"id": p.id, "nombre": p.nombre} for p in g["archivados"]],
    } for k, g in ambiguos_raw]

    huerfanos = []
    for _k, archivados in huerfanos_raw:
        for p in archivados:
            lo_ancla = ancla(db, p.id, refs)
            sombra = es_combo_sombra(db, p.id)
            huerfanos.append({
                "id": p.id, "nombre": p.nombre,
                "tiene_historia": bool(lo_ancla) or sombra,
                "ancla": lo_ancla,
                "combo_sombra": sombra,
            })

    seguros = [f for f in fusionables if f["seguro"]]
    return {
        "columnas_que_apuntan": len(refs),
        "tablas": len({c.__tablename__ for c, _ in refs}),
        "uniques": len(uniques),
        "fusionables": fusionables,
        "ambiguos": ambiguos,
        "huerfanos": huerfanos,
        "resumen": {
            "fusionables": len(fusionables),
            "seguros": len(seguros),
            "bloqueados": len(fusionables) - len(seguros),
            "ambiguos": len(ambiguos),
            "huerfanos": len(huerfanos),
            "huerfanos_borrables": sum(1 for h in huerfanos if not h["tiene_historia"]),
            "filas_a_reapuntar": sum(f["total_filas"] for f in fusionables),
            "filas_a_reapuntar_seguras": sum(f["total_filas"] for f in seguros),
        },
    }


# ─── LA EJECUCIÓN ────────────────────────────────────────────────────────────

def fusionar_par(db: Session, muerto_id: int, vivo_id: int, usuario_id: int | None) -> dict:
    """Fusiona UN par en UNA transacción. Nunca levanta: devuelve el desenlace.

    Cada par es su propia transacción para que uno que falle no arrastre a los
    demás — en una cafetería que opera todos los días, media limpieza aplicada
    es peor que ninguna."""
    try:
        return _fusionar_par(db, muerto_id, vivo_id, usuario_id)
    except FusionAbortada as e:
        db.rollback()
        return {"ok": False, "muerto": muerto_id, "vivo": vivo_id,
                "movidos": {}, "borrados": [], "error": str(e)}
    except Exception as e:                                   # noqa: BLE001
        db.rollback()
        return {"ok": False, "muerto": muerto_id, "vivo": vivo_id,
                "movidos": {}, "borrados": [], "error": f"error inesperado: {e}"}


def _fusionar_par(db: Session, muerto_id: int, vivo_id: int, usuario_id: int | None) -> dict:
    refs, uniques = referencias(), uniques_con_producto()

    if muerto_id == vivo_id:
        raise FusionAbortada("el producto a fusionar y el destino son el mismo")
    muerto = db.query(Producto).filter_by(id=muerto_id).first()
    vivo = db.query(Producto).filter_by(id=vivo_id).first()
    if muerto is None:
        raise FusionAbortada(f"el producto #{muerto_id} ya no existe")
    if vivo is None:
        raise FusionAbortada(f"el producto #{vivo_id} ya no existe")

    # LA GUARDA MÁS IMPORTANTE DEL MÓDULO. Fusionar dos vivos movería ventas
    # reales al producto equivocado: es el daño máximo de esta operación.
    if not es_archivado(muerto):
        raise FusionAbortada(
            f"#{muerto_id} «{muerto.nombre}» NO está archivado: solo se fusiona un archivado")
    if es_archivado(vivo):
        raise FusionAbortada(
            f"#{vivo_id} «{vivo.nombre}» también está archivado: no hay a dónde fusionar")
    if es_combo_sombra(db, muerto_id):
        raise FusionAbortada(
            f"#{muerto_id} «{muerto.nombre}» es el producto sombra de un combo, no un duplicado")

    # Mercancía sin contar no se mueve por NINGÚN camino. La guarda va sobre todas
    # las filas de inventario del archivado, no solo las que chocan: si el vivo no
    # tenía casillero en esa sede, la fila con stock se re-apuntaba y el vivo
    # heredaba existencias que nadie contó. Va acá además de en el plan porque el
    # stock pudo cambiar entre que el admin miró y apretó.
    from app.models.models import Inventario as _Inv
    for inv in db.query(_Inv).filter(_Inv.producto_id == muerto_id):
        if _stock_de(inv) != 0:
            raise FusionAbortada(
                f"el archivado tiene stock {_stock_de(inv):g} en la sede {inv.tienda_id}: "
                f"mover mercancía que nadie contó inventaría existencias. "
                f"Ajustá ese stock a 0 antes de fusionar.")

    nombre_muerto, nombre_vivo = muerto.nombre, vivo.nombre
    borrados = []

    # 1. Choques de único: resolverlos ANTES de re-apuntar.
    borrados += _resolver_choques(db, muerto_id, vivo_id, uniques)
    borrados += _resolver_choques_alias(db, muerto_id, vivo_id)
    db.flush()

    # `movidos` se cuenta DESPUÉS de resolver los choques: lo que se borró no se
    # movió. Contándolo antes, el botón prometía «2 registros» sobre dos filas
    # que la propia fusión destruía, y la auditoría anotaba la misma fila como
    # movida Y como borrada. El número que se le muestra al dueño es el de lo
    # que de verdad cambió de dueño.
    movidos = historia(db, muerto_id, refs)

    # 2. Re-apuntar TODA referencia del muerto al vivo.
    for cls, col in refs:
        (db.query(cls).filter(getattr(cls, col) == muerto_id)
         .update({col: vivo_id}, synchronize_session=False))
    db.flush()

    # 3. Auto-referencias que el re-apuntado deja sin sentido.
    borrados += _limpiar_autoreferencias(db, vivo_id)
    db.flush()
    db.expire_all()

    # 4. Verificar que no quedó NINGUNA referencia colgada. Si quedó, este par
    #    se revierte entero: mejor no fusionar que dejar historia apuntando a un
    #    producto que ya no existe.
    quedan = historia(db, muerto_id, refs)
    if quedan:
        raise FusionAbortada(f"quedaron referencias sin re-apuntar: {quedan}")

    # 5. Borrar el cascarón, ya vacío.
    db.query(Producto).filter_by(id=muerto_id).delete(synchronize_session=False)

    audit.registrar(
        db, accion="fusionar_duplicado", tabla="productos", registro_id=vivo_id,
        usuario_id=usuario_id,
        datos_antes={"muerto_id": muerto_id, "muerto_nombre": nombre_muerto},
        datos_despues={"vivo_id": vivo_id, "vivo_nombre": nombre_vivo,
                       "movidos": movidos, "filas_borradas": borrados},
    )
    db.commit()
    return {"ok": True, "muerto": muerto_id, "muerto_nombre": nombre_muerto,
            "vivo": vivo_id, "vivo_nombre": nombre_vivo,
            "movidos": movidos, "total_filas": sum(movidos.values()),
            "borrados": borrados, "error": None}


def _resolver_choques(db: Session, muerto_id: int, vivo_id: int, uniques) -> list[dict]:
    """Aplica ESTRATEGIA_CHOQUE tabla por tabla. Devuelve lo borrado, con su
    contenido completo, para que la auditoría lo conserve."""
    borrados = []
    for cls, cols in uniques:
        estrategia = ESTRATEGIA_CHOQUE.get(cls.__tablename__, ESTRATEGIA_DEFECTO)
        for fila, _clave in list(_filas_que_chocan(db, cls, cols, muerto_id, vivo_id)):
            detalle = _detalle_fila(cls, cols, fila)
            if estrategia == "borrar_si_vacio" and _stock_de(fila) != 0:
                raise FusionAbortada(
                    f"{cls.__tablename__}: el archivado tiene stock {_stock_de(fila):g} "
                    f"({detalle}) y el vivo ya tiene su fila. Sumarlos inventaría "
                    f"mercancía que nadie contó: revisá ese stock antes de fusionar.")
            if estrategia not in ("borrar", "borrar_si_vacio"):
                raise FusionAbortada(
                    f"{cls.__tablename__}: el vivo ya tiene su fila ({detalle}) y esa fila "
                    f"no es una repetición descartable. Este par necesita una decisión a mano.")
            borrados.append({"tabla": cls.__tablename__, "fila": _snapshot(fila)})
            db.delete(fila)
        db.flush()
    return borrados


def _resolver_choques_alias(db: Session, muerto_id: int, vivo_id: int) -> list[dict]:
    """`producto_aliases.alias_normalizado` es único GLOBAL — no lo ve
    `uniques_con_producto()`, porque la columna del único no es de producto.

    Si el vivo ya tiene ese mismo alias, el del muerto sobra y se borra. Si no,
    se re-apunta con todo lo demás: y con eso el OCR de facturas aprende a
    mandar ese nombre de proveedor al producto vivo — la fusión no solo limpia,
    mejora el escaneo."""
    borrados = []
    for a in db.query(ProductoAlias).filter(ProductoAlias.producto_id == muerto_id).all():
        gemelo = (db.query(ProductoAlias)
                  .filter(ProductoAlias.alias_normalizado == a.alias_normalizado,
                          ProductoAlias.producto_id == vivo_id).first())
        if gemelo is not None:
            borrados.append({"tabla": "producto_aliases", "fila": _snapshot(a)})
            db.delete(a)
    db.flush()
    return borrados


def _limpiar_autoreferencias(db: Session, vivo_id: int) -> list[dict]:
    """Después de re-apuntar, el vivo puede haber quedado apuntándose a sí mismo.

    Pasa cuando el vivo usaba a su propio duplicado como sustituto o lo tenía en
    su receta. Un producto que se sustituye o se consume a sí mismo no es una
    fusión bien hecha: el sustituto se limpia a NULL y la línea de receta que
    quedó `producto == insumo` se borra."""
    from app.models.models import ProductoDesechable, ProductoInsumo

    borrados = []
    (db.query(Producto).filter(Producto.id == vivo_id, Producto.sustituto_id == vivo_id)
     .update({"sustituto_id": None}, synchronize_session=False))

    # Acotado al VIVO: la primera versión barría las tablas ENTERAS borrando toda
    # fila con producto == insumo, aunque no tuviera nada que ver con este par —
    # dentro de su transacción y anotada en su auditoría. Hoy el radio real es
    # cero, pero es una mina de una línea.
    for cls in (ProductoInsumo, ProductoDesechable):
        for fila in db.query(cls).filter(cls.producto_id == cls.insumo_id,
                                         cls.producto_id == vivo_id).all():
            borrados.append({"tabla": cls.__tablename__, "fila": _snapshot(fila)})
            db.delete(fila)
    return borrados


def _snapshot(fila) -> dict:
    return {c.name: getattr(fila, c.name) for c in fila.__table__.columns}


# ─── Huérfanos: archivados sin ningún vivo (el menú viejo) ───────────────────

def _huerfanos_planos(db: Session, refs):
    _f, _a, huerfanos_raw = parejas(db)
    for _k, archivados in huerfanos_raw:
        for p in archivados:
            yield p, ancla(db, p.id, refs)


def fusionar(db: Session, pares, borrar_huerfanos_vacios: bool,
             usuario_id: int | None) -> dict:
    """Ejecuta la limpieza: cada par en su propia transacción, y opcionalmente
    borra los huérfanos que no tienen NINGUNA referencia.

    Sobre los huérfanos con historia: el dueño pidió no tener archivados, pero
    también pidió que el sistema jamás destruya un registro que alguien hizo.
    Cuando los dos deseos chocan gana el registro — se conservan y se devuelven
    con el detalle de qué los ancla."""
    resultados = []
    for par in pares or []:
        muerto_id = par["muerto"] if isinstance(par, dict) else par.muerto
        vivo_id = par["vivo"] if isinstance(par, dict) else par.vivo
        resultados.append(fusionar_par(db, muerto_id, vivo_id, usuario_id))

    refs = referencias()
    borrados, conservados = [], []
    for p, lo_ancla in _huerfanos_planos(db, refs):
        sombra = es_combo_sombra(db, p.id)
        if lo_ancla or sombra:
            conservados.append({
                "id": p.id, "nombre": p.nombre, "ancla": lo_ancla, "combo_sombra": sombra,
                "por_que": ("es el producto sombra de un combo" if sombra
                            else "tiene historia que alguien registró: se conserva"),
            })
        elif borrar_huerfanos_vacios:
            borrados.append({"id": p.id, "nombre": p.nombre})

    if borrados:
        for h in borrados:
            # El casillero de stock vacío se va con el producto: es la fila que el
            # sistema le creó al darlo de alta, no un registro de nadie. Va al
            # audit igual, con su contenido completo.
            h["casilleros"] = [_snapshot(f) for f in casilleros_inertes(db, h["id"])]
            for f in casilleros_inertes(db, h["id"]):
                db.delete(f)
            db.flush()
            db.query(Producto).filter_by(id=h["id"]).delete(synchronize_session=False)
        audit.registrar(
            db, accion="borrar_huerfanos_vacios", tabla="productos",
            usuario_id=usuario_id, datos_antes={"borrados": borrados},
        )
        db.commit()

    return {
        "pares": resultados,
        "huerfanos_borrados": borrados,
        "huerfanos_conservados": conservados,
        "resumen": {
            "fusionados": sum(1 for r in resultados if r["ok"]),
            "fallidos": sum(1 for r in resultados if not r["ok"]),
            "filas_reapuntadas": sum(r.get("total_filas", 0) for r in resultados if r["ok"]),
            "huerfanos_borrados": len(borrados),
            "huerfanos_conservados": len(conservados),
        },
    }
