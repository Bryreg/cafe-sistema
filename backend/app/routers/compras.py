from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.deps import ensure_tienda_access, get_current_user, require_admin
from app.models.models import Usuario
from app.schemas.compras import ConteoComprasCreate
from app.services import compras as svc

router = APIRouter(prefix="/compras", tags=["compras"])


@router.post("/conteo")
def crear_conteo(
    data: ConteoComprasCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    ensure_tienda_access(user, data.tienda_id)
    return svc.crear_conteo(db, data, user.id)


@router.post("/conteo/{conteo_id}/ajustar")
def ajustar_stock(
    conteo_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    return svc.ajustar_stock(db, conteo_id, user.id)


@router.get("/conteo/tienda/{tienda_id}")
def listar_conteos(
    tienda_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    ensure_tienda_access(user, tienda_id)
    return svc.get_conteos_tienda(db, tienda_id)


@router.get("/conteo/pendientes")
def conteos_pendientes(
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    return svc.get_conteos_pendientes(db)


@router.get("/panel/{tienda_id}")
def panel_pedido(
    tienda_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    ensure_tienda_access(user, tienda_id)
    return svc.get_panel_pedido(db, tienda_id)
