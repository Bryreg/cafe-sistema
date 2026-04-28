"""Etapa 4: Alertas inteligentes por tienda (solo admin)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.deps import require_admin, ensure_tienda_access
from app.models.models import Usuario
from app.services import alertas as svc

router = APIRouter(prefix="/alertas", tags=["alertas"])


@router.get("/{tienda_id}")
def get_alertas(
    tienda_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    return svc.get_alertas_inteligentes(db, tienda_id)
