"""Etapa 7: Notificaciones operativas (solo admin)."""
from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.deps import get_current_user, require_admin, ensure_tienda_access
from app.models.models import Usuario
from app.services import notificaciones as svc
from app.services import notif_reglas, push

router = APIRouter(prefix="/notificaciones", tags=["notificaciones"])


# ---------------------------------------------------------------------------
# Motor de reglas (admin). Rutas estáticas declaradas ANTES de /{tienda_id}.
# ---------------------------------------------------------------------------

@router.get("/reglas/{tienda_id}")
def get_reglas(
    tienda_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    return notif_reglas.get_reglas(db, tienda_id)


@router.put("/reglas/{tienda_id}")
def set_reglas(
    tienda_id: int,
    payload: list = Body(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    return notif_reglas.set_reglas(db, tienda_id, payload)


# ---------------------------------------------------------------------------
# Canal Web Push (PWA)
# ---------------------------------------------------------------------------

@router.get("/push/public-key")
def get_push_public_key():
    """Clave pública VAPID — abierta (no es secreta, la usa el navegador)."""
    return {"public_key": push.public_key()}


@router.post("/push/subscribe")
def push_subscribe(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    # Seguridad: no confiamos en el tienda_id del cliente para no suscribirse a
    # los push de otra tienda. Si el usuario pertenece a una tienda, se fuerza
    # esa; si es multi-sede (tienda_id None) se respeta el pedido validando acceso.
    subscription = payload.get("subscription") or {}
    if user.tienda_id is not None:
        tienda_id = user.tienda_id
    else:
        tienda_id = payload.get("tienda_id")
        if tienda_id is not None:
            ensure_tienda_access(user, tienda_id)
    push.guardar_subscription(db, tienda_id, user.id, subscription)
    return {"ok": True}


@router.delete("/push/unsubscribe")
def push_unsubscribe(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    endpoint = payload.get("endpoint")
    ok = push.borrar_subscription(db, endpoint) if endpoint else False
    return {"ok": ok}


@router.post("/push/test/{tienda_id}")
def push_test(
    tienda_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    n = push.enviar(db, tienda_id, "Prueba",
                    "Notificacion de prueba de Sistema Cafe", "/dashboard")
    return {"ok": True, "enviados": n}


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
