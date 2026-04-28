from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.deps import ensure_tienda_access, get_current_user, require_admin
from app.models.models import Usuario
from app.schemas.solicitudes import (
    CrearSolicitudPedidoRequest, SolicitudPedidoOut,
    CrearSolicitudSencillaRequest, SolicitudSencillaOut,
    AprobarSencillaRequest
)
from app.services import solicitudes as svc
from typing import List

router = APIRouter(prefix="/solicitudes", tags=["solicitudes"])


# --- Pedidos ---

@router.post("/pedido", response_model=SolicitudPedidoOut)
def crear_pedido(data: CrearSolicitudPedidoRequest, db: Session = Depends(get_db),
                 user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, data.tienda_id)
    items = [{"producto_id": i.producto_id, "cantidad_solicitada": i.cantidad_solicitada}
             for i in data.items]
    return svc.crear_pedido(db, data.tienda_id, data.nota, items, user.id)


@router.get("/pedido/tienda/{tienda_id}", response_model=List[SolicitudPedidoOut])
def listar_pedidos(tienda_id: int, db: Session = Depends(get_db),
                   user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_pedidos_tienda(db, tienda_id)


@router.patch("/pedido/{solicitud_id}/aprobar", response_model=SolicitudPedidoOut)
def aprobar_pedido(solicitud_id: int, db: Session = Depends(get_db),
                   user: Usuario = Depends(require_admin)):
    return svc.aprobar_pedido(db, solicitud_id, user.id)


@router.patch("/pedido/{solicitud_id}/rechazar", response_model=SolicitudPedidoOut)
def rechazar_pedido(solicitud_id: int, db: Session = Depends(get_db),
                    user: Usuario = Depends(require_admin)):
    return svc.rechazar_pedido(db, solicitud_id, user.id)


# --- Sencilla ---

@router.post("/sencilla", response_model=SolicitudSencillaOut)
def crear_sencilla(data: CrearSolicitudSencillaRequest, db: Session = Depends(get_db),
                   user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, data.tienda_id)
    return svc.crear_sencilla(db, data.tienda_id, data.monto_solicitado, data.motivo, user.id, data.detalle)


@router.get("/sencilla/tienda/{tienda_id}", response_model=List[SolicitudSencillaOut])
def listar_sencillas(tienda_id: int, db: Session = Depends(get_db),
                     user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_sencillas_tienda(db, tienda_id)


@router.patch("/sencilla/{solicitud_id}/aprobar", response_model=SolicitudSencillaOut)
def aprobar_sencilla(solicitud_id: int, data: AprobarSencillaRequest = AprobarSencillaRequest(),
                     db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    return svc.aprobar_sencilla(db, solicitud_id, user.id, data.detalle, data.monto_solicitado)


@router.patch("/sencilla/{solicitud_id}/rechazar", response_model=SolicitudSencillaOut)
def rechazar_sencilla(solicitud_id: int, db: Session = Depends(get_db),
                      user: Usuario = Depends(require_admin)):
    return svc.rechazar_sencilla(db, solicitud_id, user.id)


# --- Bandeja ---

@router.get("/bandeja/{tienda_id}")
def bandeja(tienda_id: int, db: Session = Depends(get_db),
            user: Usuario = Depends(require_admin)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_bandeja_pendientes(db, tienda_id)
