from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.deps import require_admin, ensure_tienda_access
from app.models.models import Usuario
from app.services import pedidos as svc

router = APIRouter(prefix="/pedidos", tags=["pedidos"])


@router.get("/sugerencia")
def sugerencia(
    tienda_id: int = Query(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    return svc.sugerencia_pedido(db, tienda_id)
