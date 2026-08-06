from typing import Optional
from fastapi import APIRouter, Depends, Body, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.deps import get_current_user, require_admin, get_barista_actor, ensure_tienda_access
from app.models.models import Usuario
from app.services import inventario_mensual as svc

router = APIRouter(prefix="/inventario-mensual", tags=["inventario-mensual"])


@router.post("/iniciar")
def iniciar(
    tienda_id: int = Query(...), anio: int = Query(...), mes: int = Query(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    barista: tuple = Depends(get_barista_actor),
):
    """Inicia (o recupera) el conteo físico mensual de la sede, pre-poblado con la
    existencia teórica de cada producto que controla stock."""
    ensure_tienda_access(user, tienda_id)
    return svc.iniciar(db, tienda_id, anio, mes, user.id, barista[0], barista[1])


@router.post("/reiniciar")
def reiniciar(
    tienda_id: int = Query(...), anio: int = Query(...), mes: int = Query(...),
    db: Session = Depends(get_db), user: Usuario = Depends(require_admin),
):
    """Admin: borra el conteo mensual EN PROCESO y lo re-siembra con el conteo del
    sistema actual (p.ej. tras la conversión a gramos). Los cerrados no se tocan."""
    return svc.reiniciar(db, tienda_id, anio, mes, user.id)


class CorregirItemBody(BaseModel):
    cantidad_real: float


@router.get("/{inv_id}/previsualizar-aplicacion")
def previsualizar_aplicacion(
    inv_id: int,
    db: Session = Depends(get_db), user: Usuario = Depends(require_admin),
):
    """Admin: qué pasaría al aplicar este conteo, SIN tocar nada. Producto por
    producto, en qué stock queda; cuántos caen en 0, cuántos se irían a negativo
    (eso bloquea la aplicación) y el impacto en pesos.

    Aplicar es irreversible y usa una diferencia congelada en el cierre contra el
    stock de hoy: nadie debería apretar ese botón sin haber visto este número."""
    return svc.aplicar(db, inv_id, user.id, dry_run=True)


@router.post("/{inv_id}/aplicar")
def aplicar(
    inv_id: int,
    omitir_negativos: bool = Query(False),
    db: Session = Depends(get_db), user: Usuario = Depends(require_admin),
):
    """Admin: aplica el conteo mensual CERRADO al inventario — stock_actual +=
    diferencia por producto, con movimiento de ajuste. Una sola vez por mes.

    400 si algún producto quedaría en negativo: la foto del cierre ya no calza
    con el stock actual y aplicarla sería romper el inventario sin vuelta atrás.

    `omitir_negativos=true` aplica los renglones sanos y EXCLUYE los trabados
    (con constancia en la respuesta y en la auditoría), en vez de frenar el
    conteo entero por uno solo. Se pide explícitamente: el default sigue siendo
    no tocar nada."""
    return svc.aplicar(db, inv_id, user.id, omitir_negativos=omitir_negativos)


@router.patch("/items/{item_id}")
def corregir_item(
    item_id: int, data: CorregirItemBody,
    db: Session = Depends(get_db), user: Usuario = Depends(require_admin),
):
    """Admin: corrige un renglón de un conteo cerrado (aún no aplicado) sin
    reabrir el mes. Recalcula diferencia y total."""
    return svc.corregir_item(db, item_id, data.cantidad_real, user.id)


@router.post("/reabrir")
def reabrir(
    tienda_id: int = Query(...), anio: int = Query(...), mes: int = Query(...),
    db: Session = Depends(get_db), user: Usuario = Depends(require_admin),
):
    """Admin: reabre el conteo mensual cerrado por error (conserva lo contado) y
    agrega los productos del catálogo que le falten al conteo."""
    return svc.reabrir(db, tienda_id, anio, mes, user.id)


@router.get("/actual")
def actual(
    tienda_id: int = Query(...), anio: int = Query(...), mes: int = Query(...),
    db: Session = Depends(get_db), user: Usuario = Depends(get_current_user),
):
    ensure_tienda_access(user, tienda_id)
    return svc.get_actual(db, tienda_id, anio, mes)


@router.get("/conciliacion")
def conciliacion(
    tienda_id: int = Query(...), anio: int = Query(...), mes: int = Query(...),
    db: Session = Depends(get_db), user: Usuario = Depends(require_admin),
):
    """Conciliación valorizada (admin): teórico vs físico vs diferencia + rankings."""
    return svc.get_conciliacion(db, tienda_id, anio, mes)


@router.get("/historial")
def historial(
    tienda_id: Optional[int] = Query(None),
    db: Session = Depends(get_db), user: Usuario = Depends(require_admin),
):
    return svc.get_historial(db, tienda_id)


@router.patch("/{inv_id}/guardar")
def guardar(
    inv_id: int, items: list = Body(...),
    db: Session = Depends(get_db), user: Usuario = Depends(get_current_user),
):
    """Guarda la existencia física contada. items: [{id, cantidad_real}]."""
    return svc.guardar(db, inv_id, items)


@router.post("/{inv_id}/cerrar")
def cerrar(
    inv_id: int,
    db: Session = Depends(get_db), user: Usuario = Depends(get_current_user),
):
    """Cierra el conteo y calcula las diferencias valorizadas."""
    return svc.cerrar(db, inv_id, user.id)
