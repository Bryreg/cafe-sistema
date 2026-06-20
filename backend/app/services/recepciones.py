"""Recepción de mercancía. Al confirmar, escribe inventario reutilizando la
maquinaria FIFO existente: por ítem crea un lote y una entrada, y la suma sobre
stock_actual SANA el stock negativo (si estaba en -4 y se reciben 20, queda en 16).
"""
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException
from app.models.models import Recepcion, RecepcionItem, Inventario, EstadoRecepcionEnum
from app.services.caja import get_turno_activo
from app.services import inventario as inv_svc
import logging

logger = logging.getLogger(__name__)


def crear(db: Session, tienda_id: int, usuario_id: int,
          proveedor: str | None = None, nota: str | None = None):
    turno = get_turno_activo(db, tienda_id)
    r = Recepcion(
        tienda_id=tienda_id,
        dia_operativo_id=(turno.dia_operativo_id if turno else None),
        turno_id=(turno.id if turno else None),
        proveedor=proveedor, usuario_id=usuario_id,
        estado=EstadoRecepcionEnum.borrador, nota=nota,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def agregar_item(db: Session, recepcion_id: int, producto_id: int, cantidad_recibida: float,
                 cantidad_factura: float | None = None, numero_lote: str | None = None,
                 fecha_vencimiento=None, precio_unitario: float | None = None):
    r = db.query(Recepcion).filter(Recepcion.id == recepcion_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Recepción no encontrada")
    if r.estado != EstadoRecepcionEnum.borrador:
        raise HTTPException(status_code=400, detail="La recepción ya fue confirmada")
    if cantidad_recibida <= 0:
        raise HTTPException(status_code=400, detail="cantidad_recibida debe ser mayor a 0")
    it = RecepcionItem(
        recepcion_id=recepcion_id, producto_id=producto_id,
        cantidad_recibida=cantidad_recibida, cantidad_factura=cantidad_factura,
        numero_lote=numero_lote, fecha_vencimiento=fecha_vencimiento, precio_unitario=precio_unitario,
    )
    db.add(it)
    db.commit()
    db.refresh(it)
    return it


def confirmar(db: Session, recepcion_id: int, usuario_id: int):
    """Confirma la recepción: escribe inventario (entrada + lote) por cada ítem.
    Atómico: si algo falla, no se persiste nada."""
    r = (
        db.query(Recepcion)
        .options(joinedload(Recepcion.items))
        .filter(Recepcion.id == recepcion_id)
        .first()
    )
    if not r:
        raise HTTPException(status_code=404, detail="Recepción no encontrada")
    if r.estado == EstadoRecepcionEnum.confirmada:
        raise HTTPException(status_code=400, detail="La recepción ya fue confirmada")
    if not r.items:
        raise HTTPException(status_code=400, detail="La recepción no tiene items")

    try:
        for it in r.items:
            # Asegurar fila de inventario (puede no existir, o estar negativa por venta sin stock)
            inv = db.query(Inventario).filter(
                Inventario.producto_id == it.producto_id, Inventario.tienda_id == r.tienda_id
            ).first()
            if not inv:
                inv = Inventario(producto_id=it.producto_id, tienda_id=r.tienda_id,
                                 stock_actual=0.0, stock_minimo=0.0)
                db.add(inv)
                db.flush()
            # entrada: incrementa stock (sana el negativo) + crea lote FIFO
            inv_svc.registrar_movimiento(
                db, producto_id=it.producto_id, tienda_id=r.tienda_id, tipo="entrada",
                cantidad=it.cantidad_recibida, motivo=f"Recepción #{r.id}",
                usuario_id=usuario_id, fecha_vencimiento=it.fecha_vencimiento, commit=False,
            )
        r.estado = EstadoRecepcionEnum.confirmada
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    db.refresh(r)
    logger.info("Recepción %s confirmada (%s items) en tienda %s", r.id, len(r.items), r.tienda_id)
    return r


def listar(db: Session, tienda_id: int, limit: int = 50):
    return (
        db.query(Recepcion)
        .filter(Recepcion.tienda_id == tienda_id)
        .order_by(Recepcion.fecha.desc())
        .limit(limit)
        .all()
    )


def sugerencias(db: Session, tienda_id: int):
    """Productos bajo mínimo o negativos — para precargar la recepción."""
    return inv_svc.get_alertas(db, tienda_id)
