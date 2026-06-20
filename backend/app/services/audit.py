"""Etapa 1: Servicio de auditoría — registra acciones críticas sin commit propio."""
import json
import logging
from sqlalchemy.orm import Session
from app.models.models import AuditLog, AuditEvent

logger = logging.getLogger(__name__)


def registrar(db: Session, accion: str, tabla: str,
              registro_id: int | None = None,
              usuario_id: int | None = None,
              tienda_id: int | None = None,
              datos_antes: dict | None = None,
              datos_despues: dict | None = None):
    """
    Agrega un AuditLog a la sesión actual. NO hace commit.
    El caller es responsable del commit (dentro de su transacción normal).
    Falla silenciosamente para no bloquear el flujo operativo.
    """
    try:
        log = AuditLog(
            accion=accion,
            tabla_afectada=tabla,
            registro_id=registro_id,
            usuario_id=usuario_id,
            tienda_id=tienda_id,
            datos_antes=json.dumps(datos_antes, default=str) if datos_antes else None,
            datos_despues=json.dumps(datos_despues, default=str) if datos_despues else None,
        )
        db.add(log)
    except Exception as e:
        logger.warning(f"audit.registrar falló silenciosamente: {e}")


def evento(db: Session, categoria: str, accion: str,
           tienda_id: int | None = None, dia_operativo_id: int | None = None,
           turno_id: int | None = None, usuario_id: int | None = None,
           entidad: str | None = None, entidad_id: int | None = None,
           payload: dict | None = None):
    """Agrega un AuditEvent (bitácora operativa estructurada) a la sesión. NO hace commit.

    Distinta de registrar(): esto es el stream operativo consultable para dashboards
    y alertas, no el diff forense. Falla silenciosamente para no bloquear la operación.
    """
    try:
        ev = AuditEvent(
            categoria=categoria, accion=accion, tienda_id=tienda_id,
            dia_operativo_id=dia_operativo_id, turno_id=turno_id, usuario_id=usuario_id,
            entidad=entidad, entidad_id=entidad_id,
            payload=json.dumps(payload, default=str) if payload else None,
        )
        db.add(ev)
    except Exception as e:
        logger.warning(f"audit.evento falló silenciosamente: {e}")
