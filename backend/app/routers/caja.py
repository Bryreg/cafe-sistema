from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.deps import ensure_tienda_access, ensure_turno_access, get_current_user
from app.models.models import Usuario, CajaTurno
from app.schemas.caja import AbrirCajaRequest, CerrarCajaRequest, MovimientoCajaRequest, TurnoOut, EntregaTurnoOut, FlujoCajaOut
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
):
    ensure_turno_access(db, user, turno_id)
    imagen_url = await upload_imagen(imagen)
    return svc.registrar_movimiento(db, turno_id, tipo, concepto, valor, user.id, imagen_url)

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
):
    ensure_turno_access(db, user, turno_id)
    imagen_url = await upload_imagen(imagen)
    return svc.registrar_entrega(db, turno_id, user.id, efectivo_real, ventas_tarjeta_bold, imagen_url)

@router.post("/{turno_id}/cuadre-llegada", response_model=EntregaTurnoOut)
async def cuadre_llegada(
    turno_id: int,
    efectivo_real: float = Form(...),
    tipo_turno: str = Form(...),
    nota: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    ensure_turno_access(db, user, turno_id)
    return svc.registrar_cuadre_llegada(db, turno_id, user.id, efectivo_real, tipo_turno, nota)


@router.get("/{turno_id}/entregas", response_model=List[EntregaTurnoOut])
def get_entregas(turno_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_turno_access(db, user, turno_id)
    return svc.get_entregas_turno(db, turno_id)

@router.get("/historial/{tienda_id}")
def historial(tienda_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    turnos = db.query(CajaTurno).filter(CajaTurno.tienda_id == tienda_id).order_by(CajaTurno.fecha_apertura.desc()).limit(30).all()
    return turnos
