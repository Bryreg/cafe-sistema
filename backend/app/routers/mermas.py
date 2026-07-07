from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.core.deps import ensure_tienda_access, get_current_user, get_barista_actor
from app.models.models import Usuario, Tienda
from app.schemas.mermas import RegistrarMermaRequest, MermaOut
from app.services import mermas as svc

router = APIRouter(prefix="/mermas", tags=["mermas"])


@router.get("/sedes")
def listar_sedes(db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    """Todas las sedes disponibles (para selector de destino en traslado)."""
    tiendas = db.query(Tienda).all()
    return [{"id": t.id, "nombre": t.nombre} for t in tiendas]


@router.post("/", response_model=MermaOut)
def registrar(data: RegistrarMermaRequest, db: Session = Depends(get_db),
              user: Usuario = Depends(get_current_user),
              barista: tuple = Depends(get_barista_actor)):
    ensure_tienda_access(user, data.tienda_id)
    return svc.registrar_merma(
        db, data.tienda_id, data.producto_id, data.cantidad, data.motivo,
        user.id, data.tipo, data.tienda_destino_id,
        barista_id=barista[0], barista_nombre=barista[1],
        quien=data.quien, confirmar=data.confirmar,
    )


@router.get("/tienda/{tienda_id}", response_model=List[MermaOut])
def listar(tienda_id: int, db: Session = Depends(get_db),
           user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    rows = svc.get_mermas_tienda(db, tienda_id)
    out = []
    for m in rows:
        d = MermaOut.model_validate(m)
        d.producto_nombre = m.producto.nombre if m.producto else None
        d.unidad_medida = m.producto.unidad_medida if m.producto else None
        out.append(d)
    return out


@router.get("/traslados/pendientes/{tienda_id}")
def traslados_pendientes(tienda_id: int, db: Session = Depends(get_db),
                         user: Usuario = Depends(get_current_user)):
    """Traslados que vienen hacia esta tienda sin confirmar."""
    ensure_tienda_access(user, tienda_id)
    registros = svc.get_traslados_pendientes(db, tienda_id)
    return [
        {
            "id": r.id,
            "producto_id": r.producto_id,
            "producto_nombre": r.producto.nombre if r.producto else str(r.producto_id),
            "unidad_medida": r.producto.unidad_medida if r.producto else "",
            "cantidad": r.cantidad,
            "tienda_origen_id": r.tienda_id,
            "tienda_origen_nombre": r.tienda.nombre if r.tienda else str(r.tienda_id),
            "fecha_registro": r.fecha_registro.isoformat(),
            "motivo": r.motivo,
        }
        for r in registros
    ]


@router.patch("/{merma_id}/recibir", response_model=MermaOut)
def confirmar_recibo(merma_id: int, db: Session = Depends(get_db),
                     user: Usuario = Depends(get_current_user)):
    """Barista en sede destino confirma el traslado → entra al inventario."""
    if not user.tienda_id:
        raise HTTPException(400, "Usuario sin tienda asignada")
    return svc.recibir_traslado(db, merma_id, user.tienda_id, user.id)
