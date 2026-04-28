"""Etapa 1: Endpoint de consulta del audit log (solo admin)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from datetime import date, datetime
from typing import Optional
from app.database import get_db
from app.core.deps import require_admin, ensure_tienda_access
from app.models.models import Usuario, AuditLog

router = APIRouter(prefix="/audit-log", tags=["audit"])


@router.get("/{tienda_id}")
def get_audit_log(
    tienda_id: int,
    fecha_desde: Optional[date] = Query(None),
    fecha_hasta: Optional[date] = Query(None),
    usuario_id: Optional[int] = Query(None),
    tabla: Optional[str] = Query(None),
    accion: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    q = db.query(AuditLog).filter(AuditLog.tienda_id == tienda_id)
    if fecha_desde:
        q = q.filter(AuditLog.fecha >= datetime.combine(fecha_desde, datetime.min.time()))
    if fecha_hasta:
        q = q.filter(AuditLog.fecha <= datetime.combine(fecha_hasta, datetime.max.time()))
    if usuario_id:
        q = q.filter(AuditLog.usuario_id == usuario_id)
    if tabla:
        q = q.filter(AuditLog.tabla_afectada == tabla)
    if accion:
        q = q.filter(AuditLog.accion == accion)
    logs = q.order_by(AuditLog.fecha.desc()).limit(limit).all()
    return [
        {
            "id": l.id,
            "fecha": l.fecha,
            "accion": l.accion,
            "tabla_afectada": l.tabla_afectada,
            "registro_id": l.registro_id,
            "usuario_id": l.usuario_id,
            "usuario": l.usuario.nombre if l.usuario else None,
            "datos_antes": l.datos_antes,
            "datos_despues": l.datos_despues,
        }
        for l in logs
    ]
