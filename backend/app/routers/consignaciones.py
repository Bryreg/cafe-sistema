import json
import math

from fastapi import APIRouter, Depends, UploadFile, File, Form, Query, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date
from app.core.tz import hoy_col
from app.services.costos import arrastre_al_mover_desde, desde_recogidas
from app.database import get_db
from app.core.deps import ensure_tienda_access, get_current_user, require_admin, get_barista_actor
from app.models.models import Tienda, Usuario
from app.schemas.consignaciones import RecogidaCreate
from app.services import consignaciones as svc
from app.core.storage import upload_imagen

# Tope del monto de una recogida. No es una regla de negocio inventada: la columna
# es Numeric(12,2), o sea 10 dígitos enteros, y un monto más grande revienta el
# INSERT en Postgres con un error que no dice nada. Mil millones de pesos en
# efectivo desde una cafetería es un cero de más tecleado, no una pasada.
MONTO_RECOGIDA_MAX = 1e9

router = APIRouter(prefix="/consignaciones", tags=["consignaciones"])

@router.post("/")
async def registrar(
    tienda_id: int = Form(...),
    valor: float = Form(...),
    turno_id: Optional[int] = Form(None),
    imagen: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    barista: tuple = Depends(get_barista_actor),
):
    ensure_tienda_access(user, tienda_id)
    imagen_url = await upload_imagen(imagen)
    return svc.registrar(db, tienda_id, valor, imagen_url, user.id, turno_id=turno_id,
                         barista_id=barista[0], barista_nombre=barista[1])

@router.get("/pendiente/{tienda_id}")
def pendiente(tienda_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_pendiente(db, tienda_id)


@router.get("/tienda/{tienda_id}")
def listar(tienda_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_por_tienda(db, tienda_id)

@router.get("/resumen-admin")
def resumen_admin(
    tienda_id: int | None = Query(None),
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    if tienda_id:
        ensure_tienda_access(user, tienda_id)
    return svc.get_resumen_admin(db, tienda_id, desde=desde, hasta=hasta)


@router.patch("/{consignacion_id}")
async def editar(
    consignacion_id: int,
    valor: Optional[float] = Form(None),
    turno_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    """Corrige el valor y/o el día (turno) de una consignación mal registrada."""
    return svc.editar(db, consignacion_id, user.id, valor=valor, turno_id=turno_id)


@router.post("/recoger")
def recoger(
    tienda_id: int = Form(...),
    turno_ids: str = Form(...),          # JSON: [turno_id, ...] — los días recogidos
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    """El admin recogió el efectivo en la tienda: salda esos días sin comprobante."""
    ensure_tienda_access(user, tienda_id)
    try:
        parsed = json.loads(turno_ids)
        if not isinstance(parsed, list):
            raise ValueError
        ids = [int(x) for x in parsed]
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="turno_ids debe ser una lista JSON de ids")
    return svc.recoger(db, tienda_id, ids, user.id)


@router.patch("/{consignacion_id}/confirmar")
def confirmar(consignacion_id: int, db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    return svc.confirmar(db, consignacion_id)


# ── Recogidas de efectivo ───────────────────────────────────────────────────
#
# Co-locadas con las consignaciones porque son la ACCIÓN ESPEJO: las dos sacan
# efectivo del cajón. La consignación lo deja en el BANCO; la recogida lo deja en
# la MANO DEL DUEÑO, que es el tercer lugar donde vive la plata desde agosto y el
# único que el sistema no conocía.
#
# Todas `require_admin`: la recogida la hace el dueño, no la barista.
#
# Las validaciones van ACÁ y no en el schema. El `detail` de un 422 de pydantic es
# una LISTA de errores y el cliente solo sabe renderizar strings, así que una regla
# violada le llegaba al dueño como "Reintenta" en vez del motivo. Con
# HTTPException(400, "...") el mensaje viaja tal cual y él sabe qué corregir.


@router.post("/recogidas", status_code=201)
def registrar_recogida(
    data: RecogidaCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    """Registra que el dueño pasó por una sede y se llevó el efectivo.

    NO confundir con POST /consignaciones/recoger (el flujo viejo): aquel salda
    turnos creando consignaciones, o sea afirma que la plata llegó al banco.
    Registrar la misma pasada por los dos caminos descuenta el cajón dos veces.
    """
    if not math.isfinite(data.monto):
        raise HTTPException(400, "El monto de la recogida debe ser un número válido.")
    if data.monto <= 0:
        raise HTTPException(400, "El monto de la recogida va en positivo.")
    if data.monto > MONTO_RECOGIDA_MAX:
        raise HTTPException(400, "El monto de la recogida es demasiado grande.")
    # Contra hoy_col() y no contra date.today(): el servidor corre en UTC y en
    # Colombia son 5 horas menos, así que entre las 19:00 y la medianoche local
    # date.today() ya pasó de día y rechazaría la pasada de ESTA tarde.
    if data.fecha > hoy_col():
        raise HTTPException(400, "No podés registrar una recogida de un día que todavía no llegó.")
    if data.nota is not None and len(data.nota) > 300:
        raise HTTPException(400, "La nota de la recogida no puede pasar de 300 caracteres.")

    # UNA RECOGIDA MÁS VIEJA QUE EL RÉGIMEN CORRE LA VENTANA HACIA ATRÁS, y con
    # ella entran a la cuenta los pagos y consignaciones de ese tramo. Cargar hoy
    # la pasada de ayer es normal y no arrastra nada; una fecha mal tecleada meses
    # atrás arrastra los pagos del MUNDO VIEJO —cuando la barista consignaba y
    # esta bolsa no existía—. Así que no se mira la fecha: se mira QUÉ ENTRARÍA.
    # Medido: una recogida de $10.000 fechada seis meses atrás metía un pago de
    # $2.000.000 y hundía la mano en −$990.000.
    desde = desde_recogidas(db)
    if desde is not None and data.fecha < desde:
        arrastre = arrastre_al_mover_desde(db, data.fecha, desde)
        if arrastre["n"]:
            raise HTTPException(
                400,
                f"Esa fecha corre el arranque de la cuenta al {data.fecha.isoformat()} "
                f"(hoy arranca el {desde.isoformat()}) y mete {arrastre['n']} "
                f"movimiento(s) por ${arrastre['monto']:,.0f} que son de antes de que "
                "empezaras a recoger. Revisá la fecha.")

    tienda = db.query(Tienda).filter(Tienda.id == data.tienda_id).first()
    if tienda is None:
        raise HTTPException(400, "Esa sede no existe.")
    if not tienda.activa:
        raise HTTPException(400, "Esa sede está inactiva.")
    ensure_tienda_access(user, data.tienda_id)

    return svc.registrar_recogida(db, data.tienda_id, data.fecha, data.monto,
                                  user.id, nota=data.nota)


@router.get("/recogidas")
def listar_recogidas(
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    tienda_id: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    """Las pasadas del dueño en un rango, con su total. Filtra por el DÍA EN QUE
    RECOGIÓ, no por el día en que lo tecleó."""
    if tienda_id is not None:
        ensure_tienda_access(user, tienda_id)
    if desde is not None and hasta is not None and desde > hasta:
        raise HTTPException(400, "El rango de fechas está al revés: 'desde' es posterior a 'hasta'.")
    return svc.listar_recogidas(db, desde=desde, hasta=hasta, tienda_id=tienda_id)


@router.delete("/recogidas/{recogida_id}")
def eliminar_recogida(recogida_id: int, db: Session = Depends(get_db),
                      user: Usuario = Depends(require_admin)):
    """Revierte una recogida registrada por error."""
    return svc.eliminar_recogida(db, recogida_id, user.id)


@router.delete("/{consignacion_id}")
def eliminar(consignacion_id: int, db: Session = Depends(get_db),
             user: Usuario = Depends(require_admin)):
    """Revierte una consignación registrada por error."""
    return svc.eliminar(db, consignacion_id, user.id)
