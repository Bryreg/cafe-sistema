from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.deps import get_current_user, require_admin, ensure_tienda_access
from app.models.models import Usuario
from app.schemas.pos import (
    TicketCreate, PrecioUpdate, ProductoPOSOut, TicketOut,
)
from app.services import pos as svc

router = APIRouter(prefix="/pos", tags=["pos"])


@router.get("/productos", response_model=List[ProductoPOSOut])
def productos(categoria: Optional[str] = None, db: Session = Depends(get_db),
              user: Usuario = Depends(get_current_user)):
    return svc.get_productos_pos(db, categoria)


@router.post("/ticket", response_model=TicketOut, status_code=201)
def crear_ticket(data: TicketCreate, db: Session = Depends(get_db),
                 user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, data.tienda_id)
    ticket = svc.crear_ticket(
        db,
        tienda_id=data.tienda_id,
        usuario_id=user.id,
        items=[i.dict() for i in data.items],
        metodo_pago=data.metodo_pago,
        efectivo_recibido=data.efectivo_recibido,
        monto_efectivo=data.monto_efectivo,
        monto_tarjeta=data.monto_tarjeta,
    )
    return ticket


@router.get("/ticket/{ticket_id}", response_model=TicketOut)
def get_ticket(ticket_id: int, db: Session = Depends(get_db),
               user: Usuario = Depends(get_current_user)):
    ticket = svc.get_ticket(db, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    ensure_tienda_access(user, ticket.tienda_id)
    return ticket


@router.get("/tickets", response_model=List[TicketOut])
def tickets_turno(turno_id: int, db: Session = Depends(get_db),
                  user: Usuario = Depends(get_current_user)):
    return svc.get_tickets_turno(db, turno_id)


@router.patch("/productos/{producto_id}/precio", response_model=ProductoPOSOut)
def set_precio(producto_id: int, data: PrecioUpdate, db: Session = Depends(get_db),
               user: Usuario = Depends(require_admin)):
    prod = svc.set_precio(db, producto_id, data.precio_venta)
    return ProductoPOSOut(
        id=prod.id,
        nombre=prod.nombre,
        categoria=prod.categoria.value,
        precio_venta=prod.precio_venta or 0.0,
        controla_stock=prod.controla_stock,
        unidad_medida=prod.unidad_medida,
    )
