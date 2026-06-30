from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.core.deps import get_current_user, require_admin, ensure_tienda_access
from app.core.storage import upload_imagen
from app.models.models import Usuario, ConfigTicket, Tienda

router = APIRouter(prefix="/config-ticket", tags=["config-ticket"])


def _get_or_create(db: Session, tienda_id: int) -> ConfigTicket:
    cfg = db.query(ConfigTicket).filter_by(tienda_id=tienda_id).first()
    if cfg:
        return cfg
    tienda = db.query(Tienda).filter_by(id=tienda_id).first()
    cfg = ConfigTicket(
        tienda_id=tienda_id,
        nombre_negocio=tienda.nombre if tienda else "AZ CAFE",
        nit=None,
        telefono=None,
        direccion=tienda.direccion if tienda else None,
        logo_url=None,
        mensaje_footer="¡Gracias por tu compra!",
        ancho_papel_mm=80,
        escala_fuente="normal",
    )
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg


def _serialize(cfg: ConfigTicket) -> dict:
    return {
        "tienda_id":      cfg.tienda_id,
        "nombre_negocio": cfg.nombre_negocio,
        "nit":            cfg.nit,
        "telefono":       cfg.telefono,
        "direccion":      cfg.direccion,
        "logo_url":       cfg.logo_url,
        "mensaje_footer": cfg.mensaje_footer,
        "ancho_papel_mm": cfg.ancho_papel_mm or 80,
        "escala_fuente":  cfg.escala_fuente  or "normal",
    }


@router.get("/{tienda_id}")
def get_config(
    tienda_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    ensure_tienda_access(user, tienda_id)
    return _serialize(_get_or_create(db, tienda_id))


class ConfigTicketUpdate(BaseModel):
    nombre_negocio: Optional[str] = None
    nit:            Optional[str] = None
    telefono:       Optional[str] = None
    direccion:      Optional[str] = None
    mensaje_footer: Optional[str] = None
    ancho_papel_mm: Optional[int] = None
    escala_fuente:  Optional[str] = None


@router.put("/{tienda_id}")
def update_config(
    tienda_id: int,
    body: ConfigTicketUpdate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    cfg = _get_or_create(db, tienda_id)
    if body.nombre_negocio is not None:
        cfg.nombre_negocio = body.nombre_negocio.strip() or cfg.nombre_negocio
    if body.nit            is not None: cfg.nit            = body.nit.strip()            or None
    if body.telefono       is not None: cfg.telefono       = body.telefono.strip()       or None
    if body.direccion      is not None: cfg.direccion      = body.direccion.strip()      or None
    if body.mensaje_footer is not None: cfg.mensaje_footer = body.mensaje_footer.strip() or None
    if body.ancho_papel_mm is not None and body.ancho_papel_mm in (58, 72, 80):
        cfg.ancho_papel_mm = body.ancho_papel_mm
    if body.escala_fuente  is not None and body.escala_fuente in ("small", "normal", "large"):
        cfg.escala_fuente  = body.escala_fuente
    db.commit()
    return _serialize(cfg)


@router.post("/{tienda_id}/logo")
async def upload_logo(
    tienda_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    url = await upload_imagen(file, max_side=400, quality=90)
    if not url:
        raise HTTPException(400, "No se pudo procesar la imagen")
    cfg = _get_or_create(db, tienda_id)
    cfg.logo_url = url
    db.commit()
    return {"logo_url": url}


@router.delete("/{tienda_id}/logo", status_code=204)
def delete_logo(
    tienda_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    cfg = _get_or_create(db, tienda_id)
    cfg.logo_url = None
    db.commit()
