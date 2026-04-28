from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.models import (SolicitudPedido, SolicitudPedidoItem,
                                SolicitudSencilla, EstadoSolicitudEnum)
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
        ))

    db.commit()
    db.refresh(solicitud)
    logger.info(f"Solicitud pedido {solicitud.id} creada en tienda {tienda_id}")
    return solicitud


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
    return s


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
    return s


def get_pedidos_tienda(db: Session, tienda_id: int):
    return db.query(SolicitudPedido).filter(
        SolicitudPedido.tienda_id == tienda_id
    ).order_by(SolicitudPedido.fecha_solicitud.desc()).limit(30).all()


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
    ).order_by(SolicitudSencilla.fecha_solicitud.desc()).limit(30).all()


def get_bandeja_pendientes(db: Session, tienda_id: int):
    pedidos = db.query(SolicitudPedido).filter(
        SolicitudPedido.tienda_id == tienda_id,
        SolicitudPedido.estado == EstadoSolicitudEnum.pendiente
    ).all()
    sencillas = db.query(SolicitudSencilla).filter(
        SolicitudSencilla.tienda_id == tienda_id,
        SolicitudSencilla.estado == EstadoSolicitudEnum.pendiente
    ).all()
    return {"pedidos": pedidos, "sencillas": sencillas,
            "total": len(pedidos) + len(sencillas)}
