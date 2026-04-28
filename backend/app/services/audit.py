"""Etapa 1: Servicio de auditoría — registra acciones críticas sin commit propio."""
import json
import logging
from sqlalchemy.orm import Session
from app.models.models import AuditLog

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
