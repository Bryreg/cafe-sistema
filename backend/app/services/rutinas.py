"""Motor de Rutinas — recurrentes como EVENTOS (no checklists).

Dos piezas: RutinaPlantilla (la regla/expectativa) y RutinaEvento (el hecho).
El cumplimiento NO es un booleano: es la comparación derivada entre lo esperado
(plantilla.esperadas_por_periodo) y lo realizado (COUNT de eventos). Sin scheduler:
la verdad son los eventos; el cumplimiento se calcula al leer.
"""
from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi import HTTPException
from app.models.models import RutinaPlantilla, RutinaEvento
from app.services.caja import get_turno_activo
import logging

logger = logging.getLogger(__name__)


def _plantillas_aplicables(db: Session, tienda_id: int):
    """Plantillas activas de la sede + las globales (tienda_id NULL = todas las sedes)."""
    return (
        db.query(RutinaPlantilla)
        .filter(
            RutinaPlantilla.activa == True,
            (RutinaPlantilla.tienda_id == tienda_id) | (RutinaPlantilla.tienda_id.is_(None)),
        )
        .order_by(RutinaPlantilla.categoria, RutinaPlantilla.nombre)
        .all()
    )


def get_pendientes(db: Session, tienda_id: int):
    """Rutinas esperadas en el turno actual menos las ya registradas en este turno."""
    turno = get_turno_activo(db, tienda_id)
    out = []
    for p in _plantillas_aplicables(db, tienda_id):
        hechas = 0
        if turno:
            hechas = db.query(func.count(RutinaEvento.id)).filter(
                RutinaEvento.plantilla_id == p.id,
                RutinaEvento.turno_id == turno.id,
            ).scalar() or 0
        esperadas = p.esperadas_por_periodo or 1
        out.append({
            "plantilla_id": p.id,
            "clave": p.clave,
            "nombre": p.nombre,
            "categoria": p.categoria.value,
            "frecuencia": p.frecuencia.value,
            "esperadas": esperadas,
            "hechas": int(hechas),
            "pendientes": max(esperadas - int(hechas), 0),
            "requiere_evidencia": p.requiere_evidencia,
            "requiere_valor": p.requiere_valor,
        })
    return out


def registrar_evento(db: Session, tienda_id: int, plantilla_id: int, usuario_id: int,
                     valor: float | None = None, nota: str | None = None,
                     imagen_url: str | None = None):
    """Registra la ejecución de una rutina como un evento (fecha/usuario/turno)."""
    plantilla = db.query(RutinaPlantilla).filter(RutinaPlantilla.id == plantilla_id).first()
    if not plantilla:
        raise HTTPException(status_code=404, detail="Rutina no encontrada")
    if plantilla.requiere_valor and valor is None:
        raise HTTPException(status_code=400, detail="Esta rutina requiere un valor (ej. temperatura)")
    if plantilla.requiere_evidencia and not imagen_url:
        raise HTTPException(status_code=400, detail="Esta rutina requiere evidencia fotográfica")

    turno = get_turno_activo(db, tienda_id)
    ev = RutinaEvento(
        plantilla_id=plantilla_id,
        tienda_id=tienda_id,
        dia_operativo_id=(turno.dia_operativo_id if turno else None),
        turno_id=(turno.id if turno else None),
        usuario_id=usuario_id,
        valor=valor,
        nota=nota,
        imagen_url=imagen_url,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    logger.info("Rutina '%s' registrada (evento %s) en tienda %s", plantilla.clave, ev.id, tienda_id)
    return ev


def get_cumplimiento(db: Session, tienda_id: int, dia_operativo_id: int | None = None):
    """Esperado vs realizado por plantilla. Acotado al día si se pasa dia_operativo_id."""
    out = []
    for p in _plantillas_aplicables(db, tienda_id):
        q = db.query(func.count(RutinaEvento.id)).filter(RutinaEvento.plantilla_id == p.id)
        if dia_operativo_id:
            q = q.filter(RutinaEvento.dia_operativo_id == dia_operativo_id)
        else:
            q = q.filter(RutinaEvento.tienda_id == tienda_id)
        hechas = int(q.scalar() or 0)
        out.append({
            "plantilla_id": p.id,
            "clave": p.clave,
            "nombre": p.nombre,
            "categoria": p.categoria.value,
            "esperadas": p.esperadas_por_periodo or 1,
            "hechas": hechas,
        })
    return out


def listar_plantillas(db: Session, tienda_id: int | None = None):
    q = db.query(RutinaPlantilla)
    if tienda_id is not None:
        q = q.filter((RutinaPlantilla.tienda_id == tienda_id) | (RutinaPlantilla.tienda_id.is_(None)))
    return q.order_by(RutinaPlantilla.categoria, RutinaPlantilla.nombre).all()


def crear_plantilla(db: Session, data: dict):
    p = RutinaPlantilla(**data)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p
