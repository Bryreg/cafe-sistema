from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.deps import ensure_tienda_access, require_admin
from app.models.models import Usuario
from app.services import informes as svc
from app.services.siigo import sync_ventas, query_ventas_siigo
from app.services.filtros import InformeFilter
from datetime import date
from typing import Optional
import csv
import io

router = APIRouter(prefix="/informes", tags=["informes"])


def _build_filtro(
    tienda_id: int,
    fecha_desde: date,
    fecha_hasta: date,
    categoria: Optional[str],
    turno_id: Optional[int],
    producto_search: Optional[str],
    con_descuento: Optional[bool] = None,
) -> Optional[InformeFilter]:
    if any([categoria, turno_id, producto_search, con_descuento]):
        return InformeFilter(
            tienda_id=tienda_id,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            categoria=categoria,
            turno_id=turno_id,
            producto_search=producto_search,
            con_descuento=con_descuento,
        )
    return None


@router.get("/ventas")
def ventas(
    tienda_id: int = Query(...),
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    categoria: Optional[str] = Query(None),
    turno_id: Optional[int] = Query(None),
    producto_search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    filtro = _build_filtro(tienda_id, fecha_desde, fecha_hasta, categoria, turno_id, producto_search)
    return svc.reporte_ventas(db, tienda_id, fecha_desde, fecha_hasta, filtro=filtro)


@router.get("/mermas")
def mermas(
    tienda_id: int = Query(...),
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    categoria: Optional[str] = Query(None),
    turno_id: Optional[int] = Query(None),
    producto_search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    filtro = _build_filtro(tienda_id, fecha_desde, fecha_hasta, categoria, turno_id, producto_search)
    return svc.reporte_mermas(db, tienda_id, fecha_desde, fecha_hasta, filtro=filtro)


@router.get("/inventario-consumido")
def inventario_consumido(
    tienda_id: int = Query(...),
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    categoria: Optional[str] = Query(None),
    turno_id: Optional[int] = Query(None),
    producto_search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    filtro = _build_filtro(tienda_id, fecha_desde, fecha_hasta, categoria, turno_id, producto_search)
    return svc.reporte_inventario_consumido(db, tienda_id, fecha_desde, fecha_hasta, filtro=filtro)


@router.get("/entregas")
def entregas(
    tienda_id: int = Query(...),
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    categoria: Optional[str] = Query(None),
    turno_id: Optional[int] = Query(None),
    producto_search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    filtro = _build_filtro(tienda_id, fecha_desde, fecha_hasta, categoria, turno_id, producto_search)
    return svc.reporte_entregas(db, tienda_id, fecha_desde, fecha_hasta, filtro=filtro)


@router.get("/turnos")
def turnos(
    tienda_id: int = Query(...),
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    categoria: Optional[str] = Query(None),
    turno_id: Optional[int] = Query(None),
    producto_search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    filtro = _build_filtro(tienda_id, fecha_desde, fecha_hasta, categoria, turno_id, producto_search)
    return svc.reporte_turnos(db, tienda_id, fecha_desde, fecha_hasta, filtro=filtro)


@router.get("/kpi-mermas")
def kpi_mermas(
    tienda_id: int = Query(...),
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    categoria: Optional[str] = Query(None),
    turno_id: Optional[int] = Query(None),
    producto_search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    filtro = _build_filtro(tienda_id, fecha_desde, fecha_hasta, categoria, turno_id, producto_search)
    return svc.kpi_mermas(db, tienda_id, fecha_desde, fecha_hasta, filtro=filtro)


@router.get("/rotacion")
def rotacion(
    tienda_id: int = Query(...),
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    categoria: Optional[str] = Query(None),
    turno_id: Optional[int] = Query(None),
    producto_search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    filtro = _build_filtro(tienda_id, fecha_desde, fecha_hasta, categoria, turno_id, producto_search)
    return svc.reporte_rotacion(db, tienda_id, fecha_desde, fecha_hasta, filtro=filtro)


@router.get("/movimientos")
def movimientos(
    tienda_id: int = Query(...),
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    categoria: Optional[str] = Query(None),
    turno_id: Optional[int] = Query(None),
    producto_search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    filtro = _build_filtro(tienda_id, fecha_desde, fecha_hasta, categoria, turno_id, producto_search)
    return svc.reporte_movimientos(db, tienda_id, fecha_desde, fecha_hasta, filtro=filtro)


@router.get("/baristas")
def baristas(
    tienda_id: int = Query(...),
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    categoria: Optional[str] = Query(None),
    turno_id: Optional[int] = Query(None),
    producto_search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    filtro = _build_filtro(tienda_id, fecha_desde, fecha_hasta, categoria, turno_id, producto_search)
    return svc.reporte_baristas(db, tienda_id, fecha_desde, fecha_hasta, filtro=filtro)


@router.post("/siigo/sync")
async def siigo_sync(
    tienda_id: int = Query(...),
    fecha_desde: str = Query(...),
    fecha_hasta: str = Query(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    try:
        return await sync_ventas(db, tienda_id, fecha_desde, fecha_hasta)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/siigo/ventas")
def siigo_ventas(
    tienda_id: int = Query(...),
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    categoria: Optional[str] = Query(None),
    turno_id: Optional[int] = Query(None),
    producto_search: Optional[str] = Query(None),
    con_descuento: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    filtro = InformeFilter(
        tienda_id=tienda_id,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        categoria=categoria,
        turno_id=turno_id,
        producto_search=producto_search,
        con_descuento=con_descuento,
    )
    return query_ventas_siigo(db, filtro)


def _extraer_filas_csv(tipo: str, data: dict) -> list[dict]:
    """Normaliza la respuesta de cada reporte a una lista plana de filas para CSV."""
    if tipo == "movimientos":
        return data.get("movimientos", [])
    if tipo == "kpi-mermas":
        # Aplanar top_productos (lista de productos con mayor cantidad de mermas)
        return [
            {
                "nombre": p.get("nombre", ""),
                "unidad": p.get("unidad", ""),
                "tipo": p.get("tipo", ""),
                "cantidad": p.get("cantidad", 0),
                "n_registros": p.get("n", 0),
            }
            for p in data.get("top_productos", [])
        ]
    return data.get("filas", [])


@router.get("/export")
def export_csv(
    tipo: str = Query(..., description="ventas | mermas | inventario | turnos | entregas | baristas | rotacion | movimientos | kpi-mermas"),
    tienda_id: int = Query(...),
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    categoria: Optional[str] = Query(None),
    turno_id: Optional[int] = Query(None),
    producto_search: Optional[str] = Query(None),
    con_descuento: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    """Exporta un informe como CSV. Soporta filtros opcionales."""
    ensure_tienda_access(user, tienda_id)
    filtro = _build_filtro(tienda_id, fecha_desde, fecha_hasta, categoria, turno_id, producto_search, con_descuento)
    fn_map = {
        "ventas": svc.reporte_ventas,
        "mermas": svc.reporte_mermas,
        "inventario": svc.reporte_inventario_consumido,
        "turnos": svc.reporte_turnos,
        "entregas": svc.reporte_entregas,
        "baristas": svc.reporte_baristas,
        "rotacion": svc.reporte_rotacion,
        "movimientos": svc.reporte_movimientos,
        "kpi-mermas": svc.kpi_mermas,
    }
    if tipo not in fn_map:
        raise HTTPException(status_code=400, detail=f"tipo inválido. Opciones: {list(fn_map)}")

    data = fn_map[tipo](db, tienda_id, fecha_desde, fecha_hasta, filtro=filtro)
    filas = _extraer_filas_csv(tipo, data)

    output = io.StringIO()
    if filas:
        # Flatten nested lists/dicts to string
        flat_filas = [
            {k: (str(v) if isinstance(v, (list, dict)) else v) for k, v in f.items()}
            for f in filas
        ]
        writer = csv.DictWriter(output, fieldnames=flat_filas[0].keys())
        writer.writeheader()
        writer.writerows(flat_filas)

    output.seek(0)
    filename = f"{tipo}_{fecha_desde}_{fecha_hasta}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
