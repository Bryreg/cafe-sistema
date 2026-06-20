"""Control de temperaturas (cadena de frío). Lectura manual; el equipo define el rango.

fuera_de_rango se computa una vez al guardar. Una lectura fuera de rango dispara
una Notificacion crítica al admin (alimenta el sistema de alertas existente).
"""
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.models import EquipoFrio, LecturaTemperatura
from app.services.caja import get_turno_activo
from app.services import notificaciones
import logging

logger = logging.getLogger(__name__)


def listar_equipos(db: Session, tienda_id: int):
    return (
        db.query(EquipoFrio)
        .filter(EquipoFrio.tienda_id == tienda_id, EquipoFrio.activo == True)
        .order_by(EquipoFrio.nombre)
        .all()
    )


def crear_equipo(db: Session, tienda_id: int, nombre: str, tipo: str,
                 temp_min: float, temp_max: float):
    if temp_min >= temp_max:
        raise HTTPException(status_code=400, detail="temp_min debe ser menor que temp_max")
    eq = EquipoFrio(tienda_id=tienda_id, nombre=nombre, tipo=tipo,
                    temp_min=temp_min, temp_max=temp_max, activo=True)
    db.add(eq)
    db.commit()
    db.refresh(eq)
    return eq


def registrar_lectura(db: Session, tienda_id: int, equipo_id: int, valor: float,
                      usuario_id: int, observacion: str | None = None):
    eq = db.query(EquipoFrio).filter(
        EquipoFrio.id == equipo_id, EquipoFrio.tienda_id == tienda_id
    ).first()
    if not eq:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")
    fuera = valor < eq.temp_min or valor > eq.temp_max
    turno = get_turno_activo(db, tienda_id)
    lec = LecturaTemperatura(
        equipo_id=equipo_id, tienda_id=tienda_id,
        dia_operativo_id=(turno.dia_operativo_id if turno else None),
        turno_id=(turno.id if turno else None),
        valor=valor, fuera_de_rango=fuera, usuario_id=usuario_id, observacion=observacion,
    )
    db.add(lec)
    if fuera:
        notificaciones.crear(
            db, tienda_id=tienda_id, tipo="temperatura_fuera_rango", nivel="critico",
            mensaje=f"{eq.nombre}: {valor}° fuera de rango ({eq.temp_min}–{eq.temp_max}°)",
            referencia_id=equipo_id,
        )
    db.commit()
    db.refresh(lec)
    return lec


def get_lecturas(db: Session, tienda_id: int, equipo_id: int | None = None, limit: int = 100):
    q = db.query(LecturaTemperatura).filter(LecturaTemperatura.tienda_id == tienda_id)
    if equipo_id:
        q = q.filter(LecturaTemperatura.equipo_id == equipo_id)
    return q.order_by(LecturaTemperatura.fecha.desc()).limit(limit).all()
