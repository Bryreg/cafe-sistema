from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.core.deps import ensure_tienda_access, get_current_user, require_barista_en_turno, require_admin
from app.models.models import Usuario, Tienda
from app.schemas.mermas import RegistrarMermaRequest, AdminTrasladoRequest, MermaOut
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
              barista: tuple = Depends(require_barista_en_turno)):
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


@router.delete("/{merma_id}/anular")
def anular(merma_id: int, db: Session = Depends(get_db),
           admin: Usuario = Depends(require_admin)):
    """Admin: anula una merma devolviendo lo que descontó y borra el registro.

    Sirve para las tres: un traslado revierte su efecto en ambas sedes, y un
    consumo o un daño devuelven los movimientos exactos que dejaron en el libro
    (ver `svc.anular_merma`). Es la salida para el doble toque en el formulario,
    que antes quedaba descontado sin forma de deshacerlo.
    """
    ensure_tienda_access(admin, svc.tienda_de(db, merma_id))
    return svc.anular_merma(db, merma_id, admin.id)


@router.post("/admin/traslado")
def admin_registrar_traslado(data: AdminTrasladoRequest, db: Session = Depends(get_db),
                             admin: Usuario = Depends(require_admin)):
    """Admin: registra un traslado ya realizado (reparación). Descuenta el origen
    aunque quede negativo y lo recibe en el destino de una vez."""
    if data.tienda_origen_id == data.tienda_destino_id:
        raise HTTPException(400, "El origen y el destino deben ser distintos")
    merma = svc.registrar_merma(
        db, data.tienda_origen_id, data.producto_id, data.cantidad,
        data.motivo or "Traslado registrado por admin", admin.id,
        tipo="traslado", tienda_destino_id=data.tienda_destino_id,
        confirmar=True, permitir_negativo=True,
    )
    recibido = False
    if data.recibir:
        r = svc.recibir_traslado(db, merma.id, data.tienda_destino_id, admin.id)
        recibido = r.recibido
    return {"merma_id": merma.id, "recibido": recibido}
