from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.deps import ensure_tienda_access, ensure_turno_access, get_current_user, get_barista_actor
from app.models.models import Usuario, CajaTurno, TurnoBarista, EntregaTurno
from app.schemas.caja import AbrirCajaRequest, CerrarCajaRequest, MovimientoCajaRequest, TurnoOut, EntregaTurnoOut, FlujoCajaOut, TurnoHistorialItem
from app.services import caja as svc
from app.core.storage import upload_imagen
from typing import List, Optional

router = APIRouter(prefix="/caja", tags=["caja"])

@router.post("/abrir", response_model=TurnoOut)
def abrir(data: AbrirCajaRequest, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, data.tienda_id)
    return svc.abrir_caja(db, data.tienda_id, data.base_real, data.justificacion_apertura, user.id, data.barista_ids, data.tipo_turno)


@router.get("/activo-pub/{tienda_id}")
def turno_activo_publico(tienda_id: int, db: Session = Depends(get_db)):
    """Turno activo sin autenticación — solo lectura para el kiosco."""
    return svc.get_turno_activo(db, tienda_id)


@router.get("/dia-operativo/{tienda_id}/actual")
def dia_operativo_actual(tienda_id: int, db: Session = Depends(get_db)):
    """Contexto del día operativo actual (continuidad) — lectura pública para el kiosco."""
    return svc.get_dia_operativo_actual(db, tienda_id)


@router.get("/efectivo-inicio/{tienda_id}")
def efectivo_inicio(tienda_id: int, db: Session = Depends(get_db)):
    """Efectivo de inicio esperado (lo que dejó el último cierre, menos consignado).
    Lectura pública para que el kiosco lo muestre al abrir el turno (cuadre unificado)."""
    return svc.get_efectivo_inicio_esperado(db, tienda_id)

@router.get("/{turno_id}/flujo", response_model=FlujoCajaOut)
def get_flujo(turno_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_turno_access(db, user, turno_id)
    result = svc.get_flujo_turno(db, turno_id)
    if not result:
        raise HTTPException(status_code=404, detail="Turno no encontrado")
    return result

@router.post("/{turno_id}/cerrar", response_model=TurnoOut)
def cerrar(turno_id: int, data: CerrarCajaRequest, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_turno_access(db, user, turno_id)
    return svc.cerrar_caja(db, turno_id, data.efectivo_final_real, data.justificacion_cierre, user.id, data.datafono_real)

@router.post("/{turno_id}/movimiento")
async def movimiento(
    turno_id: int,
    tipo: str = Form(...),
    concepto: str = Form(...),
    valor: float = Form(...),
    imagen: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    barista: tuple = Depends(get_barista_actor),
):
    ensure_turno_access(db, user, turno_id)
    imagen_url = await upload_imagen(imagen)
    return svc.registrar_movimiento(db, turno_id, tipo, concepto, valor, user.id, imagen_url,
                                    barista_id=barista[0], barista_nombre=barista[1])

@router.get("/{turno_id}/movimientos")
def get_movimientos(turno_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_turno_access(db, user, turno_id)
    return svc.get_movimientos(db, turno_id)

@router.get("/activo/{tienda_id}")
def turno_activo(tienda_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_turno_activo(db, tienda_id)

@router.get("/entregas/tienda/{tienda_id}", response_model=List[EntregaTurnoOut])
def get_entregas_tienda(tienda_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_entregas_tienda(db, tienda_id)

@router.post("/{turno_id}/entrega", response_model=EntregaTurnoOut)
async def registrar_entrega(
    turno_id: int,
    efectivo_real: float = Form(...),
    ventas_tarjeta_bold: float = Form(...),
    imagen: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    barista: tuple = Depends(get_barista_actor),
):
    ensure_turno_access(db, user, turno_id)
    imagen_url = await upload_imagen(imagen)
    return svc.registrar_entrega(db, turno_id, user.id, efectivo_real, ventas_tarjeta_bold, imagen_url,
                                 barista_id=barista[0], barista_nombre=barista[1])

@router.post("/{turno_id}/cuadre-llegada", response_model=EntregaTurnoOut)
async def cuadre_llegada(
    turno_id: int,
    efectivo_real: float = Form(...),
    tipo_turno: str = Form(...),
    nota: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    barista: tuple = Depends(get_barista_actor),
):
    ensure_turno_access(db, user, turno_id)
    return svc.registrar_cuadre_llegada(db, turno_id, user.id, efectivo_real, tipo_turno, nota,
                                        barista_id=barista[0], barista_nombre=barista[1])


@router.get("/{turno_id}/entregas", response_model=List[EntregaTurnoOut])
def get_entregas(turno_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_turno_access(db, user, turno_id)
    return svc.get_entregas_turno(db, turno_id)

@router.post("/{turno_id}/entrada", response_model=TurnoOut)
async def registrar_entrada(
    turno_id: int,
    barista_id: int = Form(...),
    imagen: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    ensure_turno_access(db, user, turno_id)
    imagen_url = await upload_imagen(imagen)
    return svc.registrar_entrada_barista(db, turno_id, user.id, barista_id, imagen_url)


@router.post("/{turno_id}/salida-barista", response_model=TurnoOut)
async def salida_barista(
    turno_id: int,
    barista_nombre: str = Form(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    ensure_turno_access(db, user, turno_id)
    return svc.registrar_salida_barista(db, turno_id, barista_nombre)


@router.post("/{turno_id}/salida", response_model=TurnoOut)
async def salida_rapida(
    turno_id: int,
    efectivo_final_real: float = Form(...),
    datafono_real: float = Form(...),
    imagen: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    ensure_turno_access(db, user, turno_id)
    imagen_url = await upload_imagen(imagen)
    return svc.cerrar_turno_rapido(db, turno_id, user.id, efectivo_final_real, datafono_real, imagen_url)


@router.get("/historial/{tienda_id}", response_model=List[TurnoHistorialItem])
def historial(tienda_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    turnos = db.query(CajaTurno).filter(
        CajaTurno.tienda_id == tienda_id
    ).order_by(CajaTurno.fecha_apertura.desc()).all()

    if not turnos:
        return []

    turno_ids = [t.id for t in turnos]

    baristas_rows = db.query(TurnoBarista).filter(TurnoBarista.turno_id.in_(turno_ids)).all()
    baristas_by_turno: dict = {}
    for b in baristas_rows:
        baristas_by_turno.setdefault(b.turno_id, []).append(b.nombre_snapshot)

    fotos_rows = (
        db.query(EntregaTurno)
        .filter(
            EntregaTurno.turno_id.in_(turno_ids),
            EntregaTurno.imagen_url.isnot(None),
        )
        .order_by(EntregaTurno.turno_id, EntregaTurno.id.asc())
        .all()
    )
    # Latest photo per turno wins (salida is always last for closed shifts)
    foto_by_turno: dict = {}
    for f in fotos_rows:
        foto_by_turno[f.turno_id] = f.imagen_url

    result = []
    for t in turnos:
        estado_val = t.estado.value if hasattr(t.estado, "value") else str(t.estado)
        result.append(TurnoHistorialItem(
            id=t.id,
            fecha_apertura=t.fecha_apertura,
            fecha_cierre=t.fecha_cierre,
            estado=estado_val,
            tipo_turno=t.tipo_turno,
            total_ventas=float(t.total_ventas or 0),
            total_efectivo=float(t.total_efectivo or 0),
            total_tarjeta=float(t.total_tarjeta or 0),
            base_real=float(t.base_real or 0),
            efectivo_final_real=float(t.efectivo_final_real) if t.efectivo_final_real is not None else None,
            datafono_real=float(t.datafono_real) if t.datafono_real is not None else None,
            diferencia_apertura=float(t.diferencia_apertura or 0),
            diferencia_cierre=float(t.diferencia_cierre) if t.diferencia_cierre is not None else None,
            diferencia_tarjeta=float(t.diferencia_tarjeta) if t.diferencia_tarjeta is not None else None,
            baristas=baristas_by_turno.get(t.id, []),
            imagen_cierre_url=foto_by_turno.get(t.id),
        ))
    return result
