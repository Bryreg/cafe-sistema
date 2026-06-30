"""Novedades — bitácora humana por turno, con arrastre entre turnos.

Una novedad con requiere_seguimiento sin resolver es el 'inbox de handoff': el
turno siguiente la ve hasta que alguien la resuelve. Reemplaza el WhatsApp.
"""
from datetime import datetime
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.models import Novedad
from app.services.caja import get_turno_activo
from app.services import notificaciones
import logging

logger = logging.getLogger(__name__)


def crear(db: Session, tienda_id: int, usuario_id: int, titulo: str,
          categoria: str = "otro", nivel: str = "info", descripcion: str | None = None,
          requiere_seguimiento: bool = False, imagen_url: str | None = None):
    turno = get_turno_activo(db, tienda_id)
    nov = Novedad(
        tienda_id=tienda_id,
        dia_operativo_id=(turno.dia_operativo_id if turno else None),
        turno_id=(turno.id if turno else None),
        categoria=categoria, nivel=nivel, titulo=titulo, descripcion=descripcion,
        requiere_seguimiento=requiere_seguimiento, usuario_id=usuario_id, imagen_url=imagen_url,
    )
    db.add(nov)
    if nivel == "urgente":
        notificaciones.crear(
            db, tienda_id=tienda_id, tipo="novedad_urgente", nivel="critico",
            mensaje=f"Novedad urgente: {titulo}", referencia_id=None,
        )
    db.commit()
    db.refresh(nov)
    logger.info("Novedad '%s' (%s) registrada en tienda %s", titulo, nivel, tienda_id)
    return nov


def get_pendientes(db: Session, tienda_id: int):
    """Novedades sin resolver que requieren seguimiento — el inbox de cambio de turno."""
    return db.query(Novedad).filter(
        Novedad.tienda_id == tienda_id,
        Novedad.requiere_seguimiento == True,
        Novedad.resuelta == False,
    ).order_by(Novedad.fecha.desc()).all()


def resolver(db: Session, novedad_id: int, usuario_id: int):
    nov = db.query(Novedad).filter(Novedad.id == novedad_id).first()
    if not nov:
        raise HTTPException(status_code=404, detail="Novedad no encontrada")
    nov.resuelta = True
    nov.resuelta_por_id = usuario_id
    nov.fecha_resuelta = datetime.utcnow()
    db.commit()
    db.refresh(nov)
    return nov


def listar(db: Session, tienda_id: int, dia_operativo_id: int | None = None):
    q = db.query(Novedad).filter(Novedad.tienda_id == tienda_id)
    if dia_operativo_id:
        q = q.filter(Novedad.dia_operativo_id == dia_operativo_id)
    return q.order_by(Novedad.fecha.desc()).all()
