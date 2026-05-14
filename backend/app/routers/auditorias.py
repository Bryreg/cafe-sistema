from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from app.database import get_db
from app.core.deps import require_admin, ensure_tienda_access
from app.models.models import Usuario
from app.services import auditorias as svc

router = APIRouter(prefix="/auditorias", tags=["auditorias"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class ItemInv(BaseModel):
    producto_id: int
    cantidad_real: float
    observacion: Optional[str] = None

class CrearAuditoriaInv(BaseModel):
    tienda_id: int
    fecha: datetime
    descripcion: str
    causa: Optional[str] = None
    observaciones: Optional[str] = None
    items: list[ItemInv]

class CerrarAuditoriaInv(BaseModel):
    causa: Optional[str] = None
    acciones_tomadas: Optional[str] = None

class ItemLimp(BaseModel):
    tarea_key: str
    realizado: bool = False
    realizado_por: Optional[str] = None

class CrearAuditoriaLimp(BaseModel):
    tienda_id: int
    semana: str           # "2026-W07"
    fecha_inicio: datetime
    observaciones: Optional[str] = None
    items: list[ItemLimp]

class ActualizarAuditoriaLimp(BaseModel):
    observaciones: Optional[str] = None
    items: list[ItemLimp]


# ─── Inventario ───────────────────────────────────────────────────────────────

@router.post("/inventario")
def crear_inv(body: CrearAuditoriaInv, db: Session = Depends(get_db),
              user: Usuario = Depends(require_admin)):
    ensure_tienda_access(user, body.tienda_id)
    return svc.crear_auditoria_inv(
        db, tienda_id=body.tienda_id, usuario_id=user.id,
        fecha=body.fecha, descripcion=body.descripcion,
        items=[it.dict() for it in body.items],
        causa=body.causa, observaciones=body.observaciones,
    )

@router.get("/inventario")
def listar_inv(tienda_id: int = Query(...), db: Session = Depends(get_db),
               user: Usuario = Depends(require_admin)):
    ensure_tienda_access(user, tienda_id)
    return svc.listar_auditorias_inv(db, tienda_id)

@router.patch("/inventario/{auditoria_id}/cerrar")
def cerrar_inv(auditoria_id: int, body: CerrarAuditoriaInv,
               tienda_id: int = Query(...),
               db: Session = Depends(get_db),
               user: Usuario = Depends(require_admin)):
    ensure_tienda_access(user, tienda_id)
    return svc.cerrar_auditoria_inv(db, auditoria_id, tienda_id,
                                    body.acciones_tomadas, body.causa)

@router.delete("/inventario/{auditoria_id}")
def eliminar_inv(auditoria_id: int, tienda_id: int = Query(...),
                 db: Session = Depends(get_db),
                 user: Usuario = Depends(require_admin)):
    ensure_tienda_access(user, tienda_id)
    return svc.eliminar_auditoria_inv(db, auditoria_id, tienda_id)


# ─── Limpieza ─────────────────────────────────────────────────────────────────

@router.get("/limpieza/tareas")
def tareas(_: Usuario = Depends(require_admin)):
    return svc.get_tareas()

@router.post("/limpieza")
def crear_limp(body: CrearAuditoriaLimp, db: Session = Depends(get_db),
               user: Usuario = Depends(require_admin)):
    ensure_tienda_access(user, body.tienda_id)
    return svc.crear_auditoria_limp(
        db, tienda_id=body.tienda_id, usuario_id=user.id,
        semana=body.semana, fecha_inicio=body.fecha_inicio,
        items=[it.dict() for it in body.items],
        observaciones=body.observaciones,
    )

@router.get("/limpieza")
def listar_limp(tienda_id: int = Query(...), db: Session = Depends(get_db),
                user: Usuario = Depends(require_admin)):
    ensure_tienda_access(user, tienda_id)
    return svc.listar_auditorias_limp(db, tienda_id)

@router.patch("/limpieza/{auditoria_id}")
def actualizar_limp(auditoria_id: int, body: ActualizarAuditoriaLimp,
                    tienda_id: int = Query(...),
                    db: Session = Depends(get_db),
                    user: Usuario = Depends(require_admin)):
    ensure_tienda_access(user, tienda_id)
    return svc.actualizar_auditoria_limp(
        db, auditoria_id, tienda_id,
        [it.dict() for it in body.items], body.observaciones,
    )

@router.patch("/limpieza/{auditoria_id}/vobo")
def vobo_limp(auditoria_id: int, tienda_id: int = Query(...),
              db: Session = Depends(get_db),
              user: Usuario = Depends(require_admin)):
    ensure_tienda_access(user, tienda_id)
    return svc.vobo_auditoria_limp(db, auditoria_id, tienda_id, user.id)

@router.delete("/limpieza/{auditoria_id}")
def eliminar_limp(auditoria_id: int, tienda_id: int = Query(...),
                  db: Session = Depends(get_db),
                  user: Usuario = Depends(require_admin)):
    ensure_tienda_access(user, tienda_id)
    return svc.eliminar_auditoria_limp(db, auditoria_id, tienda_id)
