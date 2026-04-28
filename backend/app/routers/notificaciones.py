"""Etapa 7: Notificaciones operativas (solo admin)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.deps import require_admin, ensure_tienda_access
from app.models.models import Usuario
from app.services import notificaciones as svc

router = APIRouter(prefix="/notificaciones", tags=["notificaciones"])


@router.get("/{tienda_id}")
def get_notificaciones(
    tienda_id: int,
    solo_no_leidas: bool = Query(False),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    notifs = svc.get_todas(db, tienda_id, solo_no_leidas=solo_no_leidas)
    return [
        {
            "id": n.id, "tipo": n.tipo, "mensaje": n.mensaje,
            "nivel": n.nivel, "leida": n.leida,
            "fecha": n.fecha, "referencia_id": n.referencia_id,
        }
        for n in notifs
    ]


@router.patch("/{tienda_id}/{notif_id}/leer")
def marcar_leida(
    tienda_id: int,
    notif_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    ok = svc.marcar_leida(db, notif_id, tienda_id)
    return {"ok": ok}


@router.patch("/{tienda_id}/leer-todas")
def marcar_todas_leidas(
    tienda_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    n = svc.marcar_todas_leidas(db, tienda_id)
    return {"ok": True, "marcadas": n}
