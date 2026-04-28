from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime
from fastapi import HTTPException
from app.models.models import CajaTurno, MovimientoCaja, ChecklistDiario, EstadoTurnoEnum, EntregaTurno
from app.services import audit, notificaciones
import logging

logger = logging.getLogger(__name__)


def get_turno_activo(db: Session, tienda_id: int):
    turno = db.query(CajaTurno).filter(
        CajaTurno.tienda_id == tienda_id,
        CajaTurno.estado == EstadoTurnoEnum.abierto
    ).first()
    if not turno:
        return None
    # Inyectar ultima_entrega para que el frontend pueda mostrar alerta
    ultima = db.query(EntregaTurno).filter(
        EntregaTurno.turno_id == turno.id
    ).order_by(EntregaTurno.fecha_hora.desc()).first()
    ingresos = db.query(func.sum(MovimientoCaja.valor)).filter(
        MovimientoCaja.caja_turno_id == turno.id,
        MovimientoCaja.tipo == "ingreso"
    ).scalar() or 0.0
    egresos = db.query(func.sum(MovimientoCaja.valor)).filter(
        MovimientoCaja.caja_turno_id == turno.id,
        MovimientoCaja.tipo == "egreso"
    ).scalar() or 0.0
    turno.ultima_entrega_fecha = ultima.fecha_hora if ultima else None
    turno.ultima_entrega_diferencia_efectivo = ultima.diferencia_efectivo if ultima else None
    turno.ingresos_movimientos = ingresos
    turno.egresos_movimientos = egresos
    turno.efectivo_esperado_actual = turno.base_real + turno.total_efectivo + ingresos - egresos
    return turno


def abrir_caja(db: Session, tienda_id: int, base_real: float, justificacion: str | None, usuario_id: int):
    if base_real < 0:
        raise HTTPException(status_code=400, detail="base_real no puede ser negativa")
    if get_turno_activo(db, tienda_id):
        raise HTTPException(status_code=400, detail="Ya existe un turno abierto para esta tienda")

    ultimo = db.query(CajaTurno).filter(
        CajaTurno.tienda_id == tienda_id,
        CajaTurno.estado == EstadoTurnoEnum.cerrado
    ).order_by(CajaTurno.fecha_cierre.desc()).first()

    base_sistema = ultimo.efectivo_final_real if ultimo and ultimo.efectivo_final_real is not None else 0.0
    diferencia = base_real - base_sistema

    if diferencia != 0 and not justificacion:
        raise HTTPException(
            status_code=400,
            detail=f"Diferencia de ${diferencia:,.0f} detectada. Se requiere justificación."
        )

    turno = CajaTurno(
        tienda_id=tienda_id,
        usuario_apertura_id=usuario_id,
        base_sistema=base_sistema,
        base_real=base_real,
        diferencia_apertura=diferencia,
        justificacion_apertura=justificacion,
        estado=EstadoTurnoEnum.abierto,
        tiene_conteo_apertura=False,
        tiene_ventas=False,
        tiene_conteo_cierre=False,
    )
    db.add(turno)
    db.flush()

    _tick_checklist(db, tienda_id, apertura_realizada=True)
    audit.registrar(
        db, accion="apertura_caja", tabla="caja_turnos",
        registro_id=turno.id, usuario_id=usuario_id, tienda_id=tienda_id,
        datos_despues={"base_real": base_real, "base_sistema": base_sistema,
                       "diferencia_apertura": diferencia},
    )
    db.commit()
    db.refresh(turno)
    logger.info(f"Turno {turno.id} abierto en tienda {tienda_id} por usuario {usuario_id}")
    return turno


def cerrar_caja(db: Session, turno_id: int, efectivo_final_real: float,
                justificacion: str | None, usuario_id: int,
                datafono_real: float | None = None):
    turno = db.query(CajaTurno).filter(
        CajaTurno.id == turno_id,
        CajaTurno.estado == EstadoTurnoEnum.abierto
    ).first()
    if not turno:
        raise HTTPException(status_code=404, detail="Turno no encontrado o ya cerrado")
    if not turno.tiene_conteo_cierre:
        raise HTTPException(status_code=400, detail="Debes completar el conteo de cierre antes de cerrar la caja")
    if efectivo_final_real < 0:
        raise HTTPException(status_code=400, detail="efectivo_final_real no puede ser negativo")
    if datafono_real is not None and datafono_real < 0:
        raise HTTPException(status_code=400, detail="datafono_real no puede ser negativo")
    if turno.total_tarjeta > 0 and datafono_real is None:
        raise HTTPException(status_code=400, detail="Debes registrar el total del datáfono Bold para cerrar")

    ingresos = db.query(func.sum(MovimientoCaja.valor)).filter(
        MovimientoCaja.caja_turno_id == turno_id,
        MovimientoCaja.tipo == "ingreso"
    ).scalar() or 0.0

    egresos = db.query(func.sum(MovimientoCaja.valor)).filter(
        MovimientoCaja.caja_turno_id == turno_id,
        MovimientoCaja.tipo == "egreso"
    ).scalar() or 0.0

    # Cuadre efectivo: contado - base = efectivo ventas → vs Siigo efectivo
    efectivo_ventas = efectivo_final_real - turno.base_real
    efectivo_esperado = turno.base_real + turno.total_efectivo + ingresos - egresos
    diferencia_cierre = efectivo_final_real - efectivo_esperado

    # Cuadre datáfono: Bold vs Siigo tarjeta
    diferencia_tarjeta = (datafono_real - turno.total_tarjeta) if datafono_real is not None else None

    hay_diff = diferencia_cierre != 0 or (diferencia_tarjeta is not None and diferencia_tarjeta != 0)
    if hay_diff and not justificacion:
        raise HTTPException(
            status_code=400,
            detail="Hay diferencias en el cuadre. Se requiere justificación."
        )

    turno.usuario_cierre_id = usuario_id
    turno.fecha_cierre = datetime.utcnow()
    turno.efectivo_final_real = efectivo_final_real
    turno.datafono_real = datafono_real
    turno.diferencia_cierre = diferencia_cierre
    turno.diferencia_tarjeta = diferencia_tarjeta
    turno.justificacion_cierre = justificacion
    turno.estado = EstadoTurnoEnum.cerrado

    _tick_checklist(db, turno.tienda_id, cierre_realizado=True)
    audit.registrar(
        db, accion="cierre_caja", tabla="caja_turnos",
        registro_id=turno_id, usuario_id=usuario_id, tienda_id=turno.tienda_id,
        datos_despues={"efectivo_final_real": efectivo_final_real,
                       "diferencia_cierre": diferencia_cierre,
                       "diferencia_tarjeta": diferencia_tarjeta,
                       "justificacion": justificacion},
    )
    # Etapa 7: notificación si hay diferencia
    if diferencia_cierre and diferencia_cierre != 0:
        notificaciones.crear(
            db, tienda_id=turno.tienda_id, tipo="diferencia_caja",
            nivel="critico" if abs(diferencia_cierre) > 10000 else "advertencia",
            mensaje=f"Diferencia de ${diferencia_cierre:,.0f} en cierre de turno #{turno_id}",
            referencia_id=turno_id,
        )
    db.commit()
    db.refresh(turno)
    logger.info(f"Turno {turno.id} cerrado. Δefectivo: {diferencia_cierre}, Δtarjeta: {diferencia_tarjeta}")
    return turno


def registrar_entrega(db: Session, turno_id: int, usuario_id: int,
                      efectivo_real: float, ventas_efectivo_siigo: float,
                      ventas_tarjeta_bold: float, imagen_url: str | None):
    turno = db.query(CajaTurno).filter(
        CajaTurno.id == turno_id,
        CajaTurno.estado == EstadoTurnoEnum.abierto
    ).first()
    if not turno:
        raise HTTPException(status_code=404, detail="No hay turno activo")
    if not turno.tiene_conteo_apertura:
        raise HTTPException(status_code=400, detail="Debes completar el conteo de apertura antes de registrar una entrega")
    if efectivo_real < 0 or ventas_efectivo_siigo < 0 or ventas_tarjeta_bold < 0:
        raise HTTPException(status_code=400, detail="Los valores numéricos no pueden ser negativos")

    ingresos = db.query(func.sum(MovimientoCaja.valor)).filter(
        MovimientoCaja.caja_turno_id == turno_id,
        MovimientoCaja.tipo == "ingreso"
    ).scalar() or 0.0
    egresos = db.query(func.sum(MovimientoCaja.valor)).filter(
        MovimientoCaja.caja_turno_id == turno_id,
        MovimientoCaja.tipo == "egreso"
    ).scalar() or 0.0

    efectivo_esperado = turno.base_real + turno.total_efectivo + ingresos - egresos
    if round(ventas_efectivo_siigo, 2) != round(turno.total_efectivo, 2):
        raise HTTPException(
            status_code=400,
            detail="El efectivo reportado en Siigo no coincide con las ventas registradas del turno. Revisa ventas antes de guardar la entrega."
        )
    diferencia_efectivo = efectivo_real - efectivo_esperado
    diferencia_tarjeta = ventas_tarjeta_bold - turno.total_tarjeta

    entrega = EntregaTurno(
        turno_id=turno_id,
        tienda_id=turno.tienda_id,
        usuario_id=usuario_id,
        efectivo_real=efectivo_real,
        efectivo_esperado=efectivo_esperado,
        ventas_efectivo_siigo=ventas_efectivo_siigo,
        ventas_tarjeta_bold=ventas_tarjeta_bold,
        diferencia_efectivo=diferencia_efectivo,
        diferencia_tarjeta=diferencia_tarjeta,
        imagen_url=imagen_url,
    )
    db.add(entrega)
    audit.registrar(
        db, accion="entrega_turno", tabla="entregas_turno",
        registro_id=None, usuario_id=usuario_id, tienda_id=turno.tienda_id,
        datos_despues={"efectivo_real": efectivo_real,
                       "efectivo_esperado": efectivo_esperado,
                       "diferencia_efectivo": diferencia_efectivo,
                       "diferencia_tarjeta": diferencia_tarjeta},
    )
    db.commit()
    db.refresh(entrega)
    return entrega


def get_entregas_turno(db: Session, turno_id: int):
    return db.query(EntregaTurno).filter(
        EntregaTurno.turno_id == turno_id
    ).order_by(EntregaTurno.fecha_hora.desc()).all()


def get_entregas_tienda(db: Session, tienda_id: int, limit: int = 20):
    return db.query(EntregaTurno).filter(
        EntregaTurno.tienda_id == tienda_id
    ).order_by(EntregaTurno.fecha_hora.desc()).limit(limit).all()


def registrar_movimiento(db: Session, turno_id: int, tipo: str, concepto: str,
                         valor: float, usuario_id: int):
    turno = db.query(CajaTurno).filter(
        CajaTurno.id == turno_id,
        CajaTurno.estado == EstadoTurnoEnum.abierto
    ).first()
    if not turno:
        raise HTTPException(status_code=404, detail="No hay turno activo")
    if tipo not in {"ingreso", "egreso"}:
        raise HTTPException(status_code=400, detail="tipo debe ser ingreso o egreso")
    if not concepto.strip():
        raise HTTPException(status_code=400, detail="concepto es obligatorio")
    if valor <= 0:
        raise HTTPException(status_code=400, detail="valor debe ser mayor a 0")

    mov = MovimientoCaja(
        caja_turno_id=turno_id,
        tipo=tipo,
        concepto=concepto,
        valor=valor,
        usuario_id=usuario_id
    )
    db.add(mov)
    audit.registrar(
        db, accion="movimiento_caja", tabla="movimientos_caja",
        registro_id=None, usuario_id=usuario_id, tienda_id=turno.tienda_id,
        datos_despues={"tipo": tipo, "concepto": concepto, "valor": valor},
    )
    db.commit()
    db.refresh(mov)
    return mov


def _tick_checklist(db: Session, tienda_id: int, **kwargs):
    """Actualiza el checklist del día como efecto secundario — idempotente."""
    hoy = datetime.utcnow().date()
    checklist = db.query(ChecklistDiario).filter(
        ChecklistDiario.tienda_id == tienda_id,
        func.date(ChecklistDiario.fecha) == hoy
    ).first()
    if not checklist:
        checklist = ChecklistDiario(tienda_id=tienda_id, fecha=datetime.utcnow())
        db.add(checklist)
        db.flush()
    for key, val in kwargs.items():
        setattr(checklist, key, val)
