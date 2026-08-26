from datetime import date
from typing import List

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.deps import require_admin, ensure_tienda_access
from app.core.tz import fin_dia_col_utc, inicio_dia_col_utc
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


# ─── El pedido que el dueño manda queda escrito ───────────────────────────────

class PedidoItemIn(BaseModel):
    producto_id: int
    cantidad: float
    # La unidad en la que se pidió. La pantalla manda la del producto: es la
    # única en la que «pedí» y «llegó» son restables. Si no viene, el servicio
    # cae a la del producto.
    unidad: str | None = None


class RegistrarPedidoIn(BaseModel):
    tienda_id: int
    proveedor: str
    items: List[PedidoItemIn]
    nota: str | None = None


@router.post("/registrar")
def registrar(
    data: RegistrarPedidoIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    """Deja constancia del pedido que el dueño acaba de mandarle a un proveedor.

    NO manda el WhatsApp —eso lo sigue haciendo él, desde su teléfono— y no crea
    nada que haya que aprobar. Es exactamente lo que faltaba para que la ficha
    del insumo pueda contestar «¿trajeron lo que pedí?».
    """
    ensure_tienda_access(user, data.tienda_id)
    return svc.registrar_pedido(
        db, data.tienda_id, data.proveedor,
        [{"producto_id": i.producto_id, "cantidad": i.cantidad, "unidad": i.unidad}
         for i in data.items],
        user.id, data.nota,
    )


@router.get("/registrados")
def registrados(
    tienda_id: int = Query(...),
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    """Los pedidos ya mandados, del más reciente al más viejo. Sin rango, todos."""
    ensure_tienda_access(user, tienda_id)
    return svc.pedidos_registrados(
        db, tienda_id,
        inicio_dia_col_utc(desde) if desde else None,
        fin_dia_col_utc(hasta) if hasta else None,
    )


@router.delete("/registrado/{pedido_id}")
def anular(
    pedido_id: int,
    tienda_id: int = Query(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    """Borra un pedido registrado por error. Solo los del dueño: una solicitud del
    kiosko se aprueba o se rechaza, y ese camino sí deja rastro de quién decidió."""
    ensure_tienda_access(user, tienda_id)
    return svc.anular_pedido(db, pedido_id, tienda_id)
