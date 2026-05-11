"""Comunicados admin → barista."""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.deps import get_current_user, require_admin
from app.models.models import Comunicado, ComunicadoLeido, Usuario

router = APIRouter(prefix="/comunicados", tags=["comunicados"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class ComunicadoCreate(BaseModel):
    titulo:    Optional[str] = None
    mensaje:   str
    tienda_id: Optional[int] = None   # None = todas las tiendas
    urgente:   bool = False


class ComunicadoUpdate(BaseModel):
    activo: bool


# ── Helpers ───────────────────────────────────────────────────────────────────

def _serial(c: Comunicado, leido: bool = False) -> dict:
    return {
        "id":             c.id,
        "titulo":         c.titulo,
        "mensaje":        c.mensaje,
        "tienda_id":      c.tienda_id,
        "activo":         c.activo,
        "urgente":        c.urgente,
        "fecha_creacion": c.fecha_creacion.isoformat(),
        "creado_por":     c.creador.nombre if c.creador else None,
        "leido":          leido,
        "total_leidos":   len(c.leidos),
    }


# ── Admin: crear comunicado ────────────────────────────────────────────────────

@router.post("/", status_code=201)
def crear(
    data: ComunicadoCreate,
    db:   Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    c = Comunicado(
        titulo=data.titulo,
        mensaje=data.mensaje,
        tienda_id=data.tienda_id,
        urgente=data.urgente,
        creado_por=user.id,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return _serial(c)


# ── Admin: listar todos ────────────────────────────────────────────────────────

@router.get("/admin")
def listar_admin(
    db:   Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    todos = (
        db.query(Comunicado)
        .order_by(Comunicado.fecha_creacion.desc())
        .all()
    )
    return [_serial(c) for c in todos]


# ── Admin: activar / desactivar ───────────────────────────────────────────────

@router.patch("/{comunicado_id}")
def actualizar(
    comunicado_id: int,
    data: ComunicadoUpdate,
    db:   Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    c = db.query(Comunicado).filter_by(id=comunicado_id).first()
    if not c:
        raise HTTPException(404, "Comunicado no encontrado")
    c.activo = data.activo
    db.commit()
    return _serial(c)


# ── Admin: eliminar ───────────────────────────────────────────────────────────

@router.delete("/{comunicado_id}", status_code=204)
def eliminar(
    comunicado_id: int,
    db:   Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    c = db.query(Comunicado).filter_by(id=comunicado_id).first()
    if not c:
        raise HTTPException(404, "Comunicado no encontrado")
    db.delete(c)
    db.commit()


# ── Barista: obtener comunicados no leídos ────────────────────────────────────

@router.get("/mis-comunicados")
def mis_comunicados(
    db:   Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Devuelve comunicados activos que aplican a mi tienda y que NO he leído."""
    leidos_ids = {
        r.comunicado_id
        for r in db.query(ComunicadoLeido).filter_by(usuario_id=user.id).all()
    }
    comunicados = (
        db.query(Comunicado)
        .filter(
            Comunicado.activo == True,
            Comunicado.id.notin_(leidos_ids) if leidos_ids else True,
        )
        .filter(
            (Comunicado.tienda_id == None) |
            (Comunicado.tienda_id == user.tienda_id)
        )
        .order_by(Comunicado.urgente.desc(), Comunicado.fecha_creacion.desc())
        .all()
    )
    return [_serial(c, leido=False) for c in comunicados]


# ── Barista: marcar como leído ────────────────────────────────────────────────

@router.post("/{comunicado_id}/leer", status_code=201)
def marcar_leido(
    comunicado_id: int,
    db:   Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    ya = db.query(ComunicadoLeido).filter_by(
        comunicado_id=comunicado_id, usuario_id=user.id
    ).first()
    if not ya:
        db.add(ComunicadoLeido(comunicado_id=comunicado_id, usuario_id=user.id))
        db.commit()
    return {"ok": True}
