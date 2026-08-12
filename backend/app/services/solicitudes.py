from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.models import (SolicitudPedido, SolicitudPedidoItem,
                                SolicitudSencilla, EstadoSolicitudEnum)
from app.services import notificaciones
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def crear_pedido(db: Session, tienda_id: int, nota: str | None,
                 items: list[dict], usuario_id: int):
    if not items:
        raise HTTPException(status_code=400, detail="Debe incluir al menos un producto")
    for item in items:
        if item.get("cantidad_solicitada", 0) <= 0:
            raise HTTPException(status_code=400, detail="cantidad_solicitada debe ser mayor a 0")

    solicitud = SolicitudPedido(
        tienda_id=tienda_id,
        nota=nota,
        usuario_id=usuario_id,
    )
    db.add(solicitud)
    db.flush()

    for item in items:
        db.add(SolicitudPedidoItem(
            solicitud_id=solicitud.id,
            producto_id=item["producto_id"],
            cantidad_solicitada=item["cantidad_solicitada"],
            unidad_solicitada=item.get("unidad_solicitada"),
        ))

    # Avisar al admin (campana + push, regla solicitud_barista): sin esto la
    # solicitud quedaba muda esperando que alguien abriera la Bandeja.
    n = len(items)
    msg = f"Pedido de reposición desde el kiosko: {n} producto{'s' if n != 1 else ''}"
    if nota:
        msg += f" — {nota[:80]}"
    notificaciones.disparar(
        db, tienda_id=tienda_id, tipo="solicitud_barista",
        mensaje=msg, nivel="info", referencia_id=solicitud.id,
        push_titulo="Solicitud de pedido", push_cuerpo=msg,
    )

    db.commit()
    db.refresh(solicitud)
    logger.info(f"Solicitud pedido {solicitud.id} creada en tienda {tienda_id}")
    # La respuesta viaja con `accion` igual que los listados: hoy ninguna pantalla
    # la lee (el front recarga), pero una API que dice "comprar" sobre un
    # preparable es una mentira esperando a su próximo consumidor.
    return _marcar_accion(db, [solicitud])[0]


def aprobar_pedido(db: Session, solicitud_id: int, usuario_id: int):
    s = db.query(SolicitudPedido).filter(SolicitudPedido.id == solicitud_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if s.estado != EstadoSolicitudEnum.pendiente:
        raise HTTPException(status_code=400, detail="La solicitud ya fue procesada")
    s.estado = EstadoSolicitudEnum.aprobada
    s.usuario_aprobacion_id = usuario_id
    s.fecha_aprobacion = datetime.utcnow()
    db.commit()
    db.refresh(s)
    return _marcar_accion(db, [s])[0]


def rechazar_pedido(db: Session, solicitud_id: int, usuario_id: int):
    s = db.query(SolicitudPedido).filter(SolicitudPedido.id == solicitud_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if s.estado != EstadoSolicitudEnum.pendiente:
        raise HTTPException(status_code=400, detail="La solicitud ya fue procesada")
    s.estado = EstadoSolicitudEnum.rechazada
    s.usuario_aprobacion_id = usuario_id
    s.fecha_aprobacion = datetime.utcnow()
    db.commit()
    db.refresh(s)
    return _marcar_accion(db, [s])[0]


def _marcar_accion(db: Session, solicitudes: list) -> list:
    """Le pega a cada ítem si se COMPRA o se PREPARA (`services/preparables.py`).

    La barista puede —y debe— avisar que falta mezcla de granizado. El problema
    era del otro lado: el admin agrupa la solicitud POR PROVEEDOR y de ahí sale
    un texto de pedido para WhatsApp, así que sin esta marca la mezcla viajaba
    dentro de una compra a alguien que no la vende.

    Se resuelve una sola vez para todas las solicitudes: es una propiedad del
    catálogo, no del ítem, y como `@property` del modelo sería una consulta por
    fila.
    """
    from app.services import preparables as preparables_svc
    prep_ids = preparables_svc.ids_preparables(db)
    for s in solicitudes:
        for item in s.items:
            item.accion = "preparar" if item.producto_id in prep_ids else "comprar"
    return solicitudes


def get_pedidos_tienda(db: Session, tienda_id: int):
    return _marcar_accion(db, db.query(SolicitudPedido).filter(
        SolicitudPedido.tienda_id == tienda_id
    ).order_by(SolicitudPedido.fecha_solicitud.desc()).all())


def crear_sencilla(db: Session, tienda_id: int, monto_solicitado: float,
                   motivo: str, usuario_id: int, detalle: str | None = None):
    if monto_solicitado <= 0:
        raise HTTPException(status_code=400, detail="monto_solicitado debe ser mayor a 0")
    if not motivo.strip():
        raise HTTPException(status_code=400, detail="motivo es obligatorio")
    s = SolicitudSencilla(
        tienda_id=tienda_id,
        monto_solicitado=monto_solicitado,
        motivo=motivo,
        usuario_id=usuario_id,
        detalle=detalle,
    )
    db.add(s)
    db.flush()
    msg = f"Solicitud de sencilla: ${monto_solicitado:,.0f} — {motivo[:80]}"
    notificaciones.disparar(
        db, tienda_id=tienda_id, tipo="solicitud_barista",
        mensaje=msg, nivel="info", referencia_id=s.id,
        push_titulo="Solicitud de sencilla", push_cuerpo=msg,
    )
    db.commit()
    db.refresh(s)
    return s


def aprobar_sencilla(db: Session, solicitud_id: int, usuario_id: int,
                     detalle: str | None = None, monto_solicitado: float | None = None):
    s = db.query(SolicitudSencilla).filter(SolicitudSencilla.id == solicitud_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if s.estado != EstadoSolicitudEnum.pendiente:
        raise HTTPException(status_code=400, detail="La solicitud ya fue procesada")
    s.estado = EstadoSolicitudEnum.aprobada
    s.usuario_aprobacion_id = usuario_id
    if detalle is not None:
        s.detalle = detalle
    if monto_solicitado is not None:
        s.monto_solicitado = monto_solicitado
    s.fecha_aprobacion = datetime.utcnow()
    db.commit()
    db.refresh(s)
    return s


def rechazar_sencilla(db: Session, solicitud_id: int, usuario_id: int):
    s = db.query(SolicitudSencilla).filter(SolicitudSencilla.id == solicitud_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if s.estado != EstadoSolicitudEnum.pendiente:
        raise HTTPException(status_code=400, detail="La solicitud ya fue procesada")
    s.estado = EstadoSolicitudEnum.rechazada
    s.usuario_aprobacion_id = usuario_id
    s.fecha_aprobacion = datetime.utcnow()
    db.commit()
    db.refresh(s)
    return s


def get_sencillas_tienda(db: Session, tienda_id: int):
    return db.query(SolicitudSencilla).filter(
        SolicitudSencilla.tienda_id == tienda_id
    ).order_by(SolicitudSencilla.fecha_solicitud.desc()).all()


def get_pedidos_todas(db: Session):
    rows = db.query(SolicitudPedido).order_by(SolicitudPedido.fecha_solicitud.desc()).limit(100).all()
    for r in rows:
        r.tienda_nombre = r.tienda.nombre if r.tienda else None
    return _marcar_accion(db, rows)


def get_sencillas_todas(db: Session):
    rows = db.query(SolicitudSencilla).order_by(SolicitudSencilla.fecha_solicitud.desc()).limit(100).all()
    for r in rows:
        r.tienda_nombre = r.tienda.nombre if r.tienda else None
    return rows


def get_bandeja_pendientes(db: Session, tienda_id: int):
    pedidos = db.query(SolicitudPedido).filter(
        SolicitudPedido.tienda_id == tienda_id,
        SolicitudPedido.estado == EstadoSolicitudEnum.pendiente
    ).all()
    sencillas = db.query(SolicitudSencilla).filter(
        SolicitudSencilla.tienda_id == tienda_id,
        SolicitudSencilla.estado == EstadoSolicitudEnum.pendiente
    ).all()
    _marcar_accion(db, pedidos)
    return {"pedidos": pedidos, "sencillas": sencillas,
            "total": len(pedidos) + len(sencillas)}
