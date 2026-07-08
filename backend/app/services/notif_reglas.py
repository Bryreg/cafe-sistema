"""CRUD de reglas de notificación con siembra de defaults por tienda.

La metadata estática (label, descripcion, unidad) vive acá; los valores
configurables (umbral, activa, canal_bell, canal_push, nivel) viven en la fila
NotificacionRegla. get_reglas mergea ambos para la UI.
"""
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.models.models import NotificacionRegla


# Catálogo de reglas soportadas. `umbral/activa/canal_*/nivel` son los defaults
# con los que se siembra cada tienda la primera vez.
DEFAULTS = [
    {
        "tipo": "ventas_dia",
        "label": "Ventas del dia alcanzan un monto",
        "descripcion": "Avisa cuando las ventas acumuladas del dia superan el monto definido.",
        "unidad": "$",
        "umbral": 0,
        "activa": False,
        "canal_bell": True,
        "canal_push": True,
        "nivel": "info",
    },
    {
        "tipo": "stock_critico",
        "label": "Producto en nivel critico",
        "descripcion": "Avisa cuando un producto cae a nivel critico de stock.",
        "unidad": "",
        "umbral": 0,
        "activa": True,
        "canal_bell": True,
        "canal_push": True,
        "nivel": "advertencia",
    },
    {
        "tipo": "stock_agotado",
        "label": "Producto agotado",
        "descripcion": "Avisa cuando un producto queda en cero (agotado).",
        "unidad": "",
        "umbral": 0,
        "activa": True,
        "canal_bell": True,
        "canal_push": True,
        "nivel": "critico",
    },
    {
        "tipo": "descuadre_caja",
        "label": "Descuadre de caja al cierre",
        "descripcion": "Avisa cuando el cierre de caja tiene una diferencia mayor a la tolerancia.",
        "unidad": "$",
        "umbral": 0,  # tolerancia: solo avisa si |diferencia| supera este valor
        "activa": True,
        "canal_bell": True,
        "canal_push": True,
        "nivel": "advertencia",
    },
    {
        "tipo": "consignacion_pendiente",
        "label": "Consignacion pendiente al cierre",
        "descripcion": "Avisa cuando quedan consignaciones pendientes al cerrar el dia.",
        "unidad": "$",
        "umbral": 0,
        "activa": True,
        "canal_bell": True,
        "canal_push": False,
        "nivel": "advertencia",
    },
    {
        "tipo": "solicitud_barista",
        "label": "Solicitud de barista (pedido o sencilla)",
        "descripcion": "Avisa cuando una barista envia una solicitud de reposicion o de sencilla desde el kiosko.",
        "unidad": "",
        "umbral": 0,
        "activa": True,
        "canal_bell": True,
        "canal_push": True,
        "nivel": "info",
    },
    {
        "tipo": "preparacion_sin_registrar",
        "label": "Preparacion sin registrar (stock negativo)",
        "descripcion": "Avisa cuando un producto preparado (ej. mezcla de granizado) queda en negativo: se vendio sin registrar la preparacion.",
        "unidad": "",
        "umbral": 0,
        "activa": True,
        "canal_bell": True,
        "canal_push": True,
        "nivel": "advertencia",
    },
    {
        "tipo": "traslado_entrante",
        "label": "Traslado entrante por recibir",
        "descripcion": "Avisa a la sede destino cuando otra sede le envia un traslado de productos para recibir.",
        "unidad": "",
        "umbral": 0,
        "activa": True,
        "canal_bell": True,
        "canal_push": True,
        "nivel": "info",
    },
    {
        "tipo": "venta_sin_descuento",
        "label": "Venta que no descuenta inventario",
        "descripcion": "Avisa cuando se vende un producto sin receta y sin stock propio: la venta entra pero ningun insumo se descuenta (fuga de inventario).",
        "unidad": "",
        "umbral": 0,
        "activa": True,
        "canal_bell": True,
        "canal_push": False,
        "nivel": "advertencia",
    },
]

# Índice por tipo para mergear metadata estática rápido.
_META = {d["tipo"]: d for d in DEFAULTS}


def _a_dict(regla: NotificacionRegla) -> dict:
    """Mergea la metadata estática del tipo con los valores guardados en la fila."""
    meta = _META.get(regla.tipo, {})
    return {
        "id": regla.id,
        "tipo": regla.tipo,
        "label": meta.get("label", regla.tipo),
        "descripcion": meta.get("descripcion", ""),
        "unidad": meta.get("unidad", ""),
        "umbral": regla.umbral,
        "activa": regla.activa,
        "canal_bell": regla.canal_bell,
        "canal_push": regla.canal_push,
        "nivel": regla.nivel,
    }


def get_reglas(db: Session, tienda_id: int) -> list:
    """Devuelve todas las reglas de la tienda, sembrando los defaults faltantes."""
    existentes = {
        r.tipo: r
        for r in db.query(NotificacionRegla).filter(
            NotificacionRegla.tienda_id == tienda_id
        ).all()
    }
    creada = False
    for d in DEFAULTS:
        if d["tipo"] not in existentes:
            r = NotificacionRegla(
                tienda_id=tienda_id,
                tipo=d["tipo"],
                umbral=d["umbral"],
                activa=d["activa"],
                canal_bell=d["canal_bell"],
                canal_push=d["canal_push"],
                nivel=d["nivel"],
            )
            db.add(r)
            existentes[d["tipo"]] = r
            creada = True
    if creada:
        db.commit()

    # Orden estable según el catálogo.
    return [_a_dict(existentes[d["tipo"]]) for d in DEFAULTS if d["tipo"] in existentes]


def set_reglas(db: Session, tienda_id: int, payload: list) -> list:
    """Upsert de reglas desde un payload [{tipo, umbral, activa, canal_bell,
    canal_push, nivel?}]. Devuelve el estado final (get_reglas)."""
    # Asegura que existan los defaults antes de aplicar cambios.
    get_reglas(db, tienda_id)

    existentes = {
        r.tipo: r
        for r in db.query(NotificacionRegla).filter(
            NotificacionRegla.tienda_id == tienda_id
        ).all()
    }
    for item in payload or []:
        tipo = item.get("tipo") if isinstance(item, dict) else getattr(item, "tipo", None)
        if not tipo:
            continue
        r = existentes.get(tipo)
        if r is None:
            r = NotificacionRegla(tienda_id=tienda_id, tipo=tipo)
            db.add(r)
            existentes[tipo] = r

        def _get(key, default):
            if isinstance(item, dict):
                return item.get(key, default)
            return getattr(item, key, default)

        r.umbral = _get("umbral", r.umbral if r.umbral is not None else 0)
        r.activa = bool(_get("activa", r.activa))
        r.canal_bell = bool(_get("canal_bell", r.canal_bell))
        r.canal_push = bool(_get("canal_push", r.canal_push))
        nivel = _get("nivel", None)
        if nivel:
            r.nivel = nivel
    db.commit()
    return get_reglas(db, tienda_id)


def get_regla(db: Session, tienda_id: int, tipo: str):
    """Devuelve la fila NotificacionRegla(tienda_id, tipo) o None."""
    return db.query(NotificacionRegla).filter(
        NotificacionRegla.tienda_id == tienda_id,
        NotificacionRegla.tipo == tipo,
    ).first()


def get_regla_efectiva(db: Session, tienda_id: int, tipo: str):
    """Regla vigente para el MOTOR, sin escribir en la DB.

    Si la tienda todavía no tiene fila guardada (el admin nunca abrió el panel),
    cae a los DEFAULTS del catálogo. Así el motor funciona out-of-the-box (las
    reglas activas por default disparan desde la primera venta) SIN sembrar/commit
    a mitad de una transacción de venta. Devuelve None solo si el tipo no existe
    en el catálogo. El objeto expone .activa/.canal_bell/.canal_push/.umbral/.nivel
    igual que la fila ORM."""
    fila = get_regla(db, tienda_id, tipo)
    if fila is not None:
        return fila
    meta = _META.get(tipo)
    if meta is None:
        return None
    return SimpleNamespace(
        id=None,
        tienda_id=tienda_id,
        tipo=tipo,
        umbral=meta["umbral"],
        activa=meta["activa"],
        canal_bell=meta["canal_bell"],
        canal_push=meta["canal_push"],
        nivel=meta["nivel"],
    )
