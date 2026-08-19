import json
import math
from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, UploadFile, File, Form, Query, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.deps import ensure_tienda_access, ensure_turno_access, get_current_user, get_barista_actor, require_admin
from app.core.tz import dia_col, hoy_col
from app.models.models import Usuario, CajaTurno, Tienda, TurnoBarista, EntregaTurno
from app.schemas.caja import AbrirCajaRequest, AjustarAperturaRequest, CerrarAdministrativoRequest, CerrarCajaRequest, MovimientoCajaRequest, PrestamoCajaFuerteCreate, TurnoOut, EntregaTurnoOut, FlujoCajaOut, TurnoHistorialItem
from app.services import caja as svc
from app.core.storage import upload_imagen
from typing import List, Optional

# Tope del monto de un traslado. No es una regla inventada: la base de una sede es
# de $500.000 y el techo deja tres ceros de margen. Más que eso en efectivo saliendo
# de la caja fuerte de una cafetería es un cero de más tecleado, no una emergencia.
MONTO_TRASLADO_MAX = 1e8

router = APIRouter(prefix="/caja", tags=["caja"])

@router.post("/abrir", response_model=TurnoOut)
def abrir(data: AbrirCajaRequest, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, data.tienda_id)
    return svc.abrir_caja(db, data.tienda_id, data.base_real, data.justificacion_apertura, user.id, data.barista_ids, data.tipo_turno, caja_fuerte=data.caja_fuerte)


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

# ── Traslados entre la caja fuerte y el cajón ───────────────────────────────
#
# Cada sede guarda $500.000 fijos en la caja fuerte y los saca al cajón cuando los
# pagos a proveedores en efectivo se comen la venta en efectivo del día. Esa plata
# está en la registradora y no es de nadie: está PRESTADA. Registrarlo es lo que
# hace que el cuadre dé exacto y que el consignable no reclame la base de la sede
# (Palmetto, 15-ago: pedía $697.900 donde iban $197.900).
#
# TODAS `require_admin`: mover la base es decisión del dueño, no de la barista.
#
# Las validaciones van ACÁ y no en el schema. El `detail` de un 422 de pydantic es
# una LISTA de errores y el cliente solo sabe renderizar strings, así que una regla
# violada le llegaba al dueño como "Reintenta" en vez del motivo. Con
# HTTPException(400, "...") el mensaje viaja tal cual y él sabe qué corregir.
#
# Declaradas ANTES de las rutas `/{turno_id}/...` a propósito: si una ruta con un
# path param entero llegara a matchear primero, "prestamos-caja-fuerte" fallaría la
# validación del int y devolvería un 422 en vez de caer en el handler correcto.


def _normalizar_fecha_traslado(fecha: datetime | None) -> datetime | None:
    """La fecha del traslado, en la convención del repo: UTC-naive.

    Pydantic parsea "2026-08-15T14:30:00-05:00" como datetime CON zona, y guardar
    eso en una columna que todo el resto del sistema lee como UTC-naive rompe
    cualquier comparación posterior (`fecha <= hasta` empieza a tirar TypeError
    entre aware y naive, justo adentro del cálculo del saldo). Se convierte a UTC
    y se le saca la zona; una fecha sin zona ya viene en la convención y pasa igual.
    """
    if fecha is None:
        return None
    if fecha.tzinfo is not None:
        return fecha.astimezone(timezone.utc).replace(tzinfo=None)
    return fecha


@router.post("/prestamos-caja-fuerte", status_code=201)
def registrar_prestamo_caja_fuerte(
    data: PrestamoCajaFuerteCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    """Registra que la base de la caja fuerte salió al cajón, o que volvió."""
    sentido = (data.sentido or "").strip().lower()
    if sentido not in svc.SENTIDOS_PRESTAMO:
        raise HTTPException(400, "El traslado tiene que decir si la base 'saca' de la caja "
                                 "fuerte o si se 'devuelve' a ella.")
    if not math.isfinite(data.monto):
        raise HTTPException(400, "El monto del traslado debe ser un número válido.")
    if data.monto <= 0:
        raise HTTPException(400, "El monto del traslado va en positivo: el sentido dice si "
                                 "sale o vuelve.")
    if data.monto > MONTO_TRASLADO_MAX:
        raise HTTPException(400, "El monto del traslado es demasiado grande.")
    if data.motivo is not None and len(data.motivo) > 200:
        raise HTTPException(400, "El motivo del traslado no puede pasar de 200 caracteres.")

    fecha = _normalizar_fecha_traslado(data.fecha)
    # Contra hoy_col() y no contra datetime.utcnow(): el servidor corre en UTC y en
    # Colombia son 5 horas menos, así que entre las 19:00 y la medianoche local un
    # traslado de ESTA tarde ya cae en el "mañana" de UTC y sería rechazado.
    if fecha is not None and dia_col(fecha) > hoy_col():
        raise HTTPException(400, "No podés registrar un traslado de un día que todavía no llegó.")

    tienda = db.query(Tienda).filter(Tienda.id == data.tienda_id).first()
    if tienda is None:
        raise HTTPException(400, "Esa sede no existe.")
    if not tienda.activa:
        raise HTTPException(400, "Esa sede está inactiva.")
    ensure_tienda_access(user, data.tienda_id)

    return svc.registrar_prestamo_caja_fuerte(db, data.tienda_id, sentido, data.monto,
                                              user.id, fecha=fecha, motivo=data.motivo)


@router.get("/prestamos-caja-fuerte")
def listar_prestamos_caja_fuerte(
    tienda_id: int = Query(..., ge=1),
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    """Los traslados de una sede en un rango + cuánto de la base sigue en el cajón.

    El saldo que vuelve es el VIGENTE de la sede, no la suma del rango listado."""
    ensure_tienda_access(user, tienda_id)
    if desde is not None and hasta is not None and desde > hasta:
        raise HTTPException(400, "El rango de fechas está al revés: 'desde' es posterior a 'hasta'.")
    return svc.listar_prestamos_caja_fuerte(db, tienda_id, desde=desde, hasta=hasta)


@router.delete("/prestamos-caja-fuerte/{prestamo_id}")
def eliminar_prestamo_caja_fuerte(prestamo_id: int, db: Session = Depends(get_db),
                                  user: Usuario = Depends(require_admin)):
    """Revierte un traslado cargado por error. No recalcula cuadres ya firmados."""
    return svc.eliminar_prestamo_caja_fuerte(db, prestamo_id, user.id)


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

@router.post("/{turno_id}/cerrar-administrativo", response_model=TurnoOut)
def cerrar_administrativo(turno_id: int,
                          data: CerrarAdministrativoRequest = CerrarAdministrativoRequest(),
                          db: Session = Depends(get_db),
                          user: Usuario = Depends(require_admin)):
    """Cierra un turno huérfano de un día anterior con el esperado (diferencia 0).
    Con `omitir_conteo` + motivo rescata además un turno viejo que nunca registró el
    conteo de cierre (solo días anteriores; queda marcado como cerrado sin conteo)."""
    return svc.cerrar_turno_administrativo(db, turno_id, user.id,
                                           omitir_conteo=data.omitir_conteo, motivo=data.motivo)


@router.delete("/{turno_id}/cancelar")
def cancelar_turno(turno_id: int, db: Session = Depends(get_db),
                   admin: Usuario = Depends(require_admin)):
    """Admin: elimina un turno abierto por error/demo SIN actividad (0 ventas, 0
    movimientos, sin cuadre). Rechaza si tiene cualquier actividad."""
    return svc.cancelar_turno_vacio(db, turno_id, admin.id)


@router.post("/{turno_id}/reabrir-cierre", response_model=TurnoOut)
def reabrir_conteo_cierre(turno_id: int, db: Session = Depends(get_db),
                          admin: Usuario = Depends(require_admin)):
    """Admin: revierte un conteo de cierre adelantado — el POS vuelve a facturar y
    el conteo real se registra de nuevo al cierre."""
    return svc.reabrir_conteo_cierre(db, turno_id, admin.id)


@router.post("/{turno_id}/ajustar-apertura", response_model=TurnoOut)
def ajustar_apertura(turno_id: int, data: AjustarAperturaRequest, db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    """Corrección admin: ajusta base real de la registradora y caja fuerte de un turno (con auditoría)."""
    ensure_turno_access(db, user, turno_id)
    return svc.ajustar_apertura(db, turno_id, data.base_real, data.caja_fuerte, user.id, data.motivo,
                                saldos_incluidos=data.saldos_incluidos)

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

@router.get("/turno/{turno_id}/timeline")
def turno_timeline(turno_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    """Timeline cronológico del turno (apertura, entradas/salidas, cuadres, cierre) +
    resumen por barista. Alimenta el hub de Cuadres rediseñado."""
    ensure_turno_access(db, user, turno_id)
    return svc.get_turno_timeline(db, turno_id)


@router.get("/entrega/{entrega_id}/desglose")
def entrega_desglose(entrega_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    """Desglose del efectivo esperado de un cuadre puntual + movimientos hasta ese instante."""
    e = db.query(EntregaTurno).filter(EntregaTurno.id == entrega_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Cuadre no encontrado")
    ensure_tienda_access(user, e.tienda_id)
    return svc.get_entrega_desglose(db, entrega_id)

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
    base_separada: bool = Form(False),
    es_salida: bool = Form(False),  # True cuando el cuadre viene del flujo de SALIDA de barista
    # Flujo de salida: quién(es) SALE(N). Sin esto el cuadre se atribuía a la
    # barista activa del header del kiosko (X-Barista-Id), que puede ser otra —
    # caso real: Luisa contó y salió, pero el timeline decía "Salida Esther".
    barista_salida_nombre: Optional[str] = Form(None),
    imagen: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    barista: tuple = Depends(get_barista_actor),
):
    ensure_turno_access(db, user, turno_id)
    imagen_url = await upload_imagen(imagen)
    barista_id, barista_nombre = barista[0], barista[1]
    if es_salida and barista_salida_nombre and barista_salida_nombre.strip():
        barista_nombre = barista_salida_nombre.strip()
        # Resolver el id solo si el nombre matchea UNA barista del turno (si salen
        # varias juntas viaja "A y B": queda el nombre compuesto, sin id).
        tb = db.query(TurnoBarista).filter(
            TurnoBarista.turno_id == turno_id,
            TurnoBarista.nombre_snapshot == barista_nombre,
        ).first()
        barista_id = tb.usuario_id if tb else None
    return svc.registrar_entrega(db, turno_id, user.id, efectivo_real, ventas_tarjeta_bold, imagen_url,
                                 barista_id=barista_id, barista_nombre=barista_nombre,
                                 base_separada=base_separada,
                                 tipo_cuadre="salida_barista" if es_salida else "entrega")

@router.post("/{turno_id}/cuadre-inicial", response_model=TurnoOut)
async def cuadre_inicial(
    turno_id: int,
    efectivo_real: float = Form(...),
    justificacion: Optional[str] = Form(None),
    saldos_incluidos: Optional[str] = Form(None),  # JSON: [turno_id, ...] — días cuyo saldo está en caja
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    barista: tuple = Depends(get_barista_actor),
):
    """Cuadre inicial de caja del flujo de apertura (post-conteo, sin foto)."""
    ensure_turno_access(db, user, turno_id)
    seleccion: Optional[list[int]] = None
    if saldos_incluidos is not None:
        try:
            parsed = json.loads(saldos_incluidos)
            if not isinstance(parsed, list):
                raise ValueError
            seleccion = [int(x) for x in parsed]
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="saldos_incluidos debe ser una lista JSON de ids")
    return svc.registrar_cuadre_inicial(db, turno_id, user.id, efectivo_real, justificacion,
                                        barista_id=barista[0], barista_nombre=barista[1],
                                        saldos_incluidos=seleccion)

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
    base_separada: bool = Form(False),
    imagen: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    ensure_turno_access(db, user, turno_id)
    imagen_url = await upload_imagen(imagen)
    return svc.cerrar_turno_rapido(db, turno_id, user.id, efectivo_final_real, datafono_real, imagen_url,
                                   base_separada=base_separada)


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
            tiene_conteo_cierre=bool(t.tiene_conteo_cierre),
            baristas=baristas_by_turno.get(t.id, []),
            imagen_cierre_url=foto_by_turno.get(t.id),
        ))
    return result
