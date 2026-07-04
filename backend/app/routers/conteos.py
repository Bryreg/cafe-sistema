from fastapi import APIRouter, Depends, Query, Form
from sqlalchemy.orm import Session
from datetime import date
from app.database import get_db
from app.core.deps import (ensure_turno_access, ensure_tienda_access, get_current_user,
                           get_barista_actor, require_admin)
from app.models.models import Usuario
from app.schemas.conteos import (RegistrarConteoRequest, ConteoFisicoOut,
                                 SolicitarVerificacionRequest, ResolverVerificacionRequest)
from app.services import conteos as svc
from typing import List, Optional

router = APIRouter(prefix="/conteos", tags=["conteos"])


@router.get("/conciliacion-diaria/{tienda_id}")
def conciliacion_diaria(tienda_id: int, fecha: Optional[date] = Query(None),
                        db: Session = Depends(get_db),
                        user: Usuario = Depends(require_admin)):
    """Doble inventario de un día: sistema vs conteo de apertura, entradas del día
    y conteo de cierre, por producto del conteo diario."""
    ensure_tienda_access(user, tienda_id)
    return svc.get_conciliacion_diaria(db, tienda_id, fecha)


@router.post("/", response_model=ConteoFisicoOut)
def registrar(data: RegistrarConteoRequest, db: Session = Depends(get_db),
              user: Usuario = Depends(get_current_user),
              barista: tuple = Depends(get_barista_actor)):
    ensure_tienda_access(user, data.tienda_id)
    items = [{"producto_id": i.producto_id, "cantidad_real": i.cantidad_real}
             for i in data.items]
    return svc.registrar_conteo(db, data.tienda_id, data.tipo, items, user.id,
                                barista_id=barista[0], barista_nombre=barista[1])


@router.get("/turno/{turno_id}", response_model=List[ConteoFisicoOut])
def conteos_turno(turno_id: int, db: Session = Depends(get_db),
                  user: Usuario = Depends(get_current_user)):
    ensure_turno_access(db, user, turno_id)
    return svc.get_conteos_turno(db, turno_id)


@router.post("/verificaciones")
def solicitar_verificacion(data: SolicitarVerificacionRequest, db: Session = Depends(get_db),
                           user: Usuario = Depends(require_admin)):
    """Admin: pide recontar un producto con diferencia en un conteo."""
    return svc.solicitar_verificacion(db, data.conteo_id, data.producto_id, user.id)


@router.get("/verificaciones/{tienda_id}")
def listar_verificaciones(tienda_id: int, estado: Optional[str] = Query(None),
                          db: Session = Depends(get_db),
                          user: Usuario = Depends(get_current_user)):
    """Verificaciones de conteo de la tienda (kiosko lee pendientes, admin todas)."""
    ensure_tienda_access(user, tienda_id)
    return svc.get_verificaciones(db, tienda_id, estado)


@router.post("/verificaciones/{verificacion_id}/responder")
async def responder_verificacion(verificacion_id: int,
                                 cantidad: float = Form(...),
                                 nota: Optional[str] = Form(None),
                                 db: Session = Depends(get_db),
                                 user: Usuario = Depends(get_current_user),
                                 barista: tuple = Depends(get_barista_actor)):
    """Barista (kiosko): responde el recuento físico solicitado."""
    return svc.responder_verificacion(db, verificacion_id, cantidad, nota, user.id,
                                      barista_id=barista[0], barista_nombre=barista[1])


@router.post("/verificaciones/{verificacion_id}/resolver")
def resolver_verificacion(verificacion_id: int, data: ResolverVerificacionRequest,
                          db: Session = Depends(get_db),
                          user: Usuario = Depends(require_admin)):
    """Admin: aprueba (ajusta stock al recuento verificado si difiere) o rechaza."""
    return svc.resolver_verificacion(db, verificacion_id, data.aprobar, user.id, data.nota)


@router.post("/desechables/solicitar")
def solicitar_desechables(tienda_id: int = Form(...), db: Session = Depends(get_db),
                          user: Usuario = Depends(require_admin)):
    """Admin: pide el formato de desechables a la sede."""
    return svc.solicitar_conteo_desechables(db, tienda_id, user.id)


@router.get("/desechables/pendiente/{tienda_id}")
def desechables_pendiente(tienda_id: int, db: Session = Depends(get_db),
                          user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_solicitud_desechables(db, tienda_id)


@router.post("/desechables", response_model=ConteoFisicoOut)
def registrar_desechables(data: RegistrarConteoRequest, db: Session = Depends(get_db),
                          user: Usuario = Depends(get_current_user),
                          barista: tuple = Depends(get_barista_actor)):
    """Barista: llena el formato de desechables solicitado por el admin."""
    ensure_tienda_access(user, data.tienda_id)
    items = [{"producto_id": i.producto_id, "cantidad_real": i.cantidad_real}
             for i in data.items]
    return svc.registrar_conteo_desechables(db, data.tienda_id, items, user.id,
                                            barista_id=barista[0], barista_nombre=barista[1])


@router.post("/{conteo_id}/aplicar")
def aplicar_conteo(conteo_id: int, db: Session = Depends(get_db),
                   user: Usuario = Depends(require_admin)):
    """Admin: promueve un conteo físico a verdad del inventario (ajustes masivos).
    Pensado para el conteo de fin de mes o la primera operación de una sede."""
    return svc.aplicar_conteo_inventario(db, conteo_id, user.id)


@router.get("/tienda/{tienda_id}")
def conteos_tienda(tienda_id: int,
                   fecha_desde: Optional[date] = Query(None),
                   fecha_hasta: Optional[date] = Query(None),
                   db: Session = Depends(get_db),
                   user: Usuario = Depends(get_current_user)):
    """Monitor de conteos físicos (hub admin): rango de días Colombia, items con diferencias."""
    ensure_tienda_access(user, tienda_id)
    return svc.get_conteos_tienda(db, tienda_id, fecha_desde, fecha_hasta)
