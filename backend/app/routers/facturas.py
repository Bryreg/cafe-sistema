import json
from datetime import date, datetime, time
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.core.deps import ensure_tienda_access, get_current_user, require_admin, require_barista_en_turno
from app.models.models import Producto, Usuario
from app.schemas.facturas import FacturaCreate
from app.services import facturas as svc
from app.services import factura_ocr
from app.core.storage import upload_imagen
from app.core.tz import inicio_dia_col_utc, fin_dia_col_utc

router = APIRouter(prefix="/facturas", tags=["facturas"])


@router.post("/")
async def crear_factura(
    data: str = Form(...),
    imagen: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    barista: tuple = Depends(require_barista_en_turno),
):
    try:
        payload = FacturaCreate(**json.loads(data))
    except Exception as e:
        raise HTTPException(422, f"Datos inválidos: {e}")

    ensure_tienda_access(user, payload.tienda_id)

    imagen_url = await upload_imagen(imagen, max_side=1600, quality=85)
    # En threadpool (mismo patrón de /analizar-foto): crear_factura hace commits
    # por-item del aprendizaje de aliases — eso no puede bloquear el event loop.
    return await run_in_threadpool(
        svc.crear_factura, db, payload, imagen_url, user.id,
        barista_id=barista[0], barista_nombre=barista[1])


_MAX_FOTO_BYTES = 15 * 1024 * 1024


@router.post("/analizar-foto")
async def analizar_foto(
    tienda_id: int = Form(...),
    imagen: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Lee una foto de factura con Claude vision y devuelve los datos extraídos
    ya cruzados con el catálogo, listos para prellenar el form de Ingresos.
    No modifica nada: el registro sigue pasando por POST /facturas/."""
    ensure_tienda_access(user, tienda_id)
    # Leer con tope de tamaño: sin esto un upload gigante se carga entero en RAM.
    data = bytearray()
    while chunk := await imagen.read(1024 * 1024):
        data.extend(chunk)
        if len(data) > _MAX_FOTO_BYTES:
            raise HTTPException(413, "La foto pesa demasiado (máx. 15 MB) — sacala de nuevo.")
    # La llamada al modelo tarda varios segundos: correrla en threadpool para
    # no bloquear el event loop del server.
    return await run_in_threadpool(
        factura_ocr.analizar_factura_foto, db, tienda_id, bytes(data), user.id)


class ConvertirCantidadBody(BaseModel):
    producto_id: int
    cantidad: Optional[float] = None
    unidad: Optional[str] = None


@router.post("/convertir-cantidad")
def convertir_cantidad(
    body: ConvertirCantidadBody,
    db: Session = Depends(get_db),
    barista: tuple = Depends(require_barista_en_turno),
):
    """Convierte una cantidad en la unidad de la FACTURA (kg/lt/caja…) a la
    unidad del inventario del producto, para los renglones PENDIENTES del
    escaneo (sin match) a los que la barista les asigna producto en el form.

    NADA de lógica nueva: expone la MISMA función pura _convertir_cantidad que
    ya usan los renglones matcheados (factura_ocr.mapear_items). Regla de oro:
    nunca se adivina una cantidad — lo dudoso sale como cantidad null +
    advertencia y la barista la digita."""
    prod = db.query(Producto).filter(Producto.id == body.producto_id).first()
    if prod is None:
        raise HTTPException(404, "Producto no encontrado")
    cantidad, en_empaques, _factor, advertencia = factura_ocr._convertir_cantidad(
        prod, body.cantidad, body.unidad)
    return {"cantidad": cantidad, "en_empaques": en_empaques,
            "advertencia": advertencia}


# Must be before /{factura_id} to avoid route conflict
@router.get("/proveedores/{tienda_id}")
def listar_proveedores(
    tienda_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    ensure_tienda_access(user, tienda_id)
    return svc.get_proveedores_tienda(db, tienda_id)


@router.get("/tienda/{tienda_id}")
def listar_facturas(
    tienda_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    ensure_tienda_access(user, tienda_id)
    return svc.get_facturas_tienda(db, tienda_id)


# Before /{factura_id} para evitar conflicto de ruta.
@router.get("/dashboard")
def dashboard_pagos(
    tienda_id: Optional[int] = Query(None),
    desde: Optional[date] = Query(None),
    hasta: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    """Pagos a proveedores: totales, ranking por proveedor, por mes, por sede + facturas."""
    d = inicio_dia_col_utc(desde) if desde else None
    h = fin_dia_col_utc(hasta) if hasta else None
    return svc.get_dashboard_pagos(db, tienda_id, d, h)


@router.delete("/{factura_id}")
def eliminar(factura_id: int, db: Session = Depends(get_db),
             user: Usuario = Depends(require_admin)):
    """Elimina una factura errónea/de prueba revirtiendo inventario, lotes y egresos de caja."""
    return svc.eliminar_factura(db, factura_id, user.id)


class FacturaEditItem(BaseModel):
    id: int
    cantidad: Optional[float] = None
    precio_unitario: Optional[float] = None


class FacturaEditRequest(BaseModel):
    valor_total: Optional[float] = None
    valor_pagado: Optional[float] = None
    numero_factura: Optional[str] = None
    proveedor: Optional[str] = None
    fecha_recibido: Optional[date] = None
    tipo_pago: Optional[str] = None
    forma_pago_real: Optional[str] = None
    items: Optional[list[FacturaEditItem]] = None
    # Vencimiento (Fase 2 de Costos): mandarlos en null los BORRA (ver abajo).
    fecha_vencimiento: Optional[date] = None
    plazo_dias: Optional[int] = None
    fecha_programada: Optional[date] = None


_CAMPOS_VENCIMIENTO = ("fecha_vencimiento", "plazo_dias", "fecha_programada")


@router.patch("/{factura_id}")
def editar(factura_id: int, body: FacturaEditRequest, db: Session = Depends(get_db),
           user: Usuario = Depends(require_admin)):
    """Editor completo de una factura (metadata, montos, productos y vencimiento)."""
    items = ([{"id": i.id, "cantidad": i.cantidad, "precio_unitario": i.precio_unitario}
              for i in body.items] if body.items is not None else None)
    # Los campos de vencimiento se pasan SOLO si vinieron en el payload: con
    # Optional a secas, "no lo mandé" y "borralo" son el mismo None y una
    # fecha_programada equivocada quedaría imborrable (y manda sobre todo lo demás).
    enviados = body.model_dump(exclude_unset=True)
    vencimiento = {c: enviados[c] for c in _CAMPOS_VENCIMIENTO if c in enviados}
    return svc.editar_factura(
        db, factura_id, user.id,
        valor_total=body.valor_total, valor_pagado=body.valor_pagado,
        numero_factura=body.numero_factura, proveedor=body.proveedor,
        fecha_recibido=body.fecha_recibido, tipo_pago=body.tipo_pago,
        forma_pago_real=body.forma_pago_real, items=items,
        **vencimiento,
    )


@router.patch("/{factura_id}/pago")
async def registrar_pago(
    factura_id: int,
    monto: float = Form(...),
    forma_pago: Optional[str] = Form(None),
    imagen: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    """Registra un pago (total/parcial) a un proveedor + foto del soporte de pago."""
    soporte_url = await upload_imagen(imagen, max_side=1600, quality=85)
    return svc.registrar_pago(db, factura_id, monto, forma_pago, soporte_url, user.id)


@router.get("/{factura_id}")
def detalle_factura(
    factura_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    factura = svc.get_factura(db, factura_id)
    ensure_tienda_access(user, factura["tienda_id"])
    return factura
