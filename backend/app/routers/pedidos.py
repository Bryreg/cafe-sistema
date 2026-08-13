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


@router.get("/proveedores")
def proveedores(
    tienda_id: int = Query(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    """El catálogo APRENDIDO: quién trae qué, a cuánto y cada cuánto — armado de
    las facturas que ya se escanearon, con la asignación manual mandando encima.
    Es la fuente de la pantalla «Armar pedido»."""
    ensure_tienda_access(user, tienda_id)
    return svc.catalogo_proveedores(db, tienda_id)
