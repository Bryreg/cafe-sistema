from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timedelta, date
from fastapi import HTTPException
from app.models.models import (CajaTurno, MovimientoCaja, ChecklistDiario, EstadoTurnoEnum,
                               EntregaTurno, Consignacion, EstadoConsignacionEnum, TurnoBarista,
                               Usuario, DiaOperativo, EstadoDiaEnum, TipoTurnoEnum)
from app.core.tz import hoy_col, inicio_dia_col_utc, fin_dia_col_utc

# Colombia (UTC-5). Fase posterior: configurable por sede (ConfiguracionSede.timezone).
TZ_OFFSET_HORAS = -5


def _fecha_operativa() -> date:
    """Fecha del día-negocio en hora local, no UTC. Evita que un cierre pasada la
    medianoche caiga en el día equivocado (el bug que la fecha-calendario UTC produce)."""
    return (datetime.utcnow() + timedelta(hours=TZ_OFFSET_HORAS)).date()


def get_or_create_dia(db: Session, tienda_id: int, usuario_id: int) -> "DiaOperativo":
    """Día operativo de hoy para la tienda; lo crea si no existe (lazy, al abrir el 1er turno)."""
    fecha = _fecha_operativa()
    dia = db.query(DiaOperativo).filter(
        DiaOperativo.tienda_id == tienda_id,
        DiaOperativo.fecha_operativa == fecha,
    ).first()
    if not dia:
        dia = DiaOperativo(
            tienda_id=tienda_id, fecha_operativa=fecha,
            estado=EstadoDiaEnum.abierto, abierto_por_id=usuario_id,
        )
        db.add(dia)
        db.flush()
    return dia
from app.services import audit, notificaciones
import logging

logger = logging.getLogger(__name__)


def _hay_conteo_apertura_en_dia(db: Session, turno) -> bool:
    """¿Ya hubo un conteo de apertura en el día operativo de este turno?

    Permite que intermedio/cierre hereden la línea base del día sin repetir el
    conteo. Si el turno tiene día operativo (Fase 1) se consulta exacto por
    dia_operativo_id; si no (turno legacy), se usa una ventana de 18h como fallback.
    """
    if turno.dia_operativo_id:
        return db.query(CajaTurno).filter(
            CajaTurno.dia_operativo_id == turno.dia_operativo_id,
            CajaTurno.tiene_conteo_apertura == True,
        ).first() is not None
    desde = datetime.utcnow() - timedelta(hours=18)
    return db.query(CajaTurno).filter(
        CajaTurno.tienda_id == turno.tienda_id,
        CajaTurno.fecha_apertura >= desde,
        CajaTurno.tiene_conteo_apertura == True,
    ).first() is not None


def _es_operativo(db: Session, turno) -> bool:
    """Gate duro: el POS solo se habilita cuando el turno está OPERATIVO.

    Operativo = cuadre de llegada hecho Y conteo de apertura del día hecho.
      - apertura: requiere su propio conteo de apertura.
      - intermedio/cierre: heredan la línea base del día (no repiten el conteo).
      - si el turno ya registró ventas, se considera operativo (no bloquear un
        turno in-flight al desplegar este cambio).
    """
    if turno.tiene_ventas:
        return True
    if not turno.tiene_cuadre_llegada:
        return False
    if turno.tiene_conteo_apertura:
        return True
    if turno.tipo_turno in ("intermedio", "cierre"):
        return _hay_conteo_apertura_en_dia(db, turno)
    return False


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
    consigs_sum = db.query(func.sum(Consignacion.valor)).filter(
        Consignacion.caja_turno_id == turno.id
    ).scalar() or 0.0
    turno.ultima_entrega_fecha = ultima.fecha_hora if ultima else None
    turno.ultima_entrega_diferencia_efectivo = ultima.diferencia_efectivo if ultima else None
    turno.ingresos_movimientos = ingresos
    turno.egresos_movimientos = egresos
    turno.efectivo_esperado_actual = turno.base_real + turno.total_efectivo + ingresos - egresos
    turno.consignaciones_turno = consigs_sum
    baristas_db = db.query(TurnoBarista).filter(TurnoBarista.turno_id == turno.id).all()
    turno.baristas = [b.nombre_snapshot for b in baristas_db]
    turno.baristas_salidas = [b.nombre_snapshot for b in baristas_db if b.salida_at is not None]
    turno.dia_tiene_conteo_apertura = _hay_conteo_apertura_en_dia(db, turno)
    turno.es_operativo = _es_operativo(db, turno)
    return turno


def abrir_caja(db: Session, tienda_id: int, base_real: float | None, justificacion: str | None, usuario_id: int, barista_ids: list[int] | None = None, tipo_turno: str | None = None, caja_fuerte: float | None = None):
    # Dos modos:
    #  - base_real=None (flujo actual): cuadre DIFERIDO — el turno abre solo con baristas,
    #    tipo y caja fuerte; el efectivo se cuenta después del conteo de inventario vía
    #    registrar_cuadre_inicial. El POS queda bloqueado hasta entonces.
    #  - base_real con valor (legacy/tests): cuadre unificado al abrir, comportamiento previo.
    cuadre_unificado = base_real is not None
    if cuadre_unificado and base_real < 0:
        raise HTTPException(status_code=400, detail="base_real no puede ser negativa")
    if caja_fuerte is not None and caja_fuerte < 0:
        raise HTTPException(status_code=400, detail="caja_fuerte no puede ser negativa")
    if tipo_turno is not None and tipo_turno not in (e.value for e in TipoTurnoEnum):
        raise HTTPException(status_code=400, detail="tipo_turno inválido")
    if get_turno_activo(db, tienda_id):
        raise HTTPException(status_code=400, detail="Ya existe un turno abierto para esta tienda")

    ultimo = db.query(CajaTurno).filter(
        CajaTurno.tienda_id == tienda_id,
        CajaTurno.estado == EstadoTurnoEnum.cerrado
    ).order_by(CajaTurno.fecha_cierre.desc()).first()

    consigs_deducidas = 0.0
    if ultimo:
        consigs_deducidas = db.query(func.sum(Consignacion.valor)).filter(
            Consignacion.caja_turno_id == ultimo.id,
            Consignacion.estado == EstadoConsignacionEnum.realizada,
        ).scalar() or 0.0
    base_sistema = (ultimo.efectivo_final_real or 0.0) - consigs_deducidas if ultimo else 0.0
    diferencia = (base_real - base_sistema) if cuadre_unificado else 0.0

    if cuadre_unificado and round(diferencia, 2) != 0 and not justificacion:
        raise HTTPException(
            status_code=400,
            detail=f"Diferencia de ${diferencia:,.0f} detectada. Se requiere justificación."
        )

    turno = CajaTurno(
        tienda_id=tienda_id,
        usuario_apertura_id=usuario_id,
        base_sistema=base_sistema,
        # Cuadre diferido: base_real queda en 0 hasta registrar_cuadre_inicial.
        base_real=base_real if cuadre_unificado else 0.0,
        caja_fuerte=caja_fuerte or 0.0,
        diferencia_apertura=diferencia,
        justificacion_apertura=justificacion if cuadre_unificado else None,
        tipo_turno=tipo_turno,
        estado=EstadoTurnoEnum.abierto,
        tiene_conteo_apertura=False,
        # Unificado: contar el efectivo AL ABRIR es el cuadre de llegada.
        # Diferido: el cuadre de llegada lo registra registrar_cuadre_inicial.
        tiene_cuadre_llegada=cuadre_unificado,
        tiene_ventas=False,
        tiene_conteo_cierre=False,
        consignaciones_deducidas=consigs_deducidas,
    )
    db.add(turno)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Ya hay un turno abierto para esta tienda. Otro barista puede haberlo abierto.",
        )

    # Registrar baristas del turno (responsabilidad compartida)
    nombres_baristas = None
    if barista_ids:
        usuarios = db.query(Usuario).filter(Usuario.id.in_(barista_ids), Usuario.activo == True).all()
        for u in usuarios:
            db.add(TurnoBarista(turno_id=turno.id, usuario_id=u.id, nombre_snapshot=u.nombre))
        nombres_baristas = ", ".join(u.nombre for u in usuarios) or None

    # Cuadre de apertura unificado (solo modo legacy con base_real al abrir): el conteo del
    # efectivo de inicio ES el cuadre, atribuido a las baristas elegidas, sin foto (no hay
    # ventas todavía). En el flujo diferido este registro lo crea registrar_cuadre_inicial.
    if cuadre_unificado:
        db.add(EntregaTurno(
            turno_id=turno.id, tienda_id=tienda_id, usuario_id=usuario_id,
            efectivo_real=base_real, efectivo_esperado=base_sistema,
            base_snapshot=base_sistema, ventas_efectivo_snapshot=0.0,
            ingresos_snapshot=0.0, egresos_snapshot=0.0,
            ventas_efectivo_siigo=0.0, ventas_tarjeta_bold=0.0,
            diferencia_efectivo=diferencia, diferencia_tarjeta=0.0,
            imagen_url=None, tipo="apertura",
            barista_id=None, barista_nombre=nombres_baristas,
        ))

    # Fase 1: enlazar el turno al día operativo (continuidad entre turnos)
    dia = get_or_create_dia(db, tienda_id, usuario_id)
    turno.dia_operativo_id = dia.id
    anteriores = db.query(CajaTurno).filter(
        CajaTurno.dia_operativo_id == dia.id,
        CajaTurno.id != turno.id,
    ).order_by(CajaTurno.fecha_apertura.desc()).all()
    turno.secuencia_dia = len(anteriores) + 1
    turno.turno_anterior_id = anteriores[0].id if anteriores else None

    _tick_checklist(db, tienda_id, apertura_realizada=True)
    audit.registrar(
        db, accion="apertura_caja", tabla="caja_turnos",
        registro_id=turno.id, usuario_id=usuario_id, tienda_id=tienda_id,
        datos_despues={"base_real": base_real, "base_sistema": base_sistema,
                       "diferencia_apertura": diferencia,
                       "consignaciones_deducidas": consigs_deducidas,
                       "barista_ids": barista_ids or []},
    )
    db.commit()
    logger.info(f"Turno {turno.id} abierto en tienda {tienda_id} por usuario {usuario_id}")
    # Devolver el turno COMPLETAMENTE enriquecido (es_operativo, totales, baristas, etc.)
    return get_turno_activo(db, tienda_id)


def registrar_cuadre_inicial(db: Session, turno_id: int, usuario_id: int,
                             efectivo_real: float, justificacion: str | None = None,
                             barista_id: int | None = None, barista_nombre: str | None = None):
    """Cuadre inicial de caja (flujo diferido): tras el conteo de inventario, se cuenta el
    efectivo de la registradora contra lo que dejó el cierre anterior (base_sistema = ventas
    en efectivo del día anterior pendientes de consignar). Sin foto: aún no hay ventas.
    Fija base_real, marca el cuadre de llegada y desbloquea el POS (junto con el conteo)."""
    turno = db.query(CajaTurno).filter(
        CajaTurno.id == turno_id,
        CajaTurno.estado == EstadoTurnoEnum.abierto
    ).first()
    if not turno:
        raise HTTPException(status_code=404, detail="No hay turno activo")
    if turno.tiene_cuadre_llegada:
        raise HTTPException(status_code=400, detail="El cuadre inicial ya fue registrado")
    if efectivo_real < 0:
        raise HTTPException(status_code=400, detail="El valor no puede ser negativo")

    esperado = turno.base_sistema or 0.0
    diferencia = efectivo_real - esperado
    if round(diferencia, 2) != 0 and not justificacion:
        raise HTTPException(
            status_code=400,
            detail=f"Diferencia de ${diferencia:,.0f} detectada. Se requiere justificación."
        )

    turno.base_real = efectivo_real
    turno.diferencia_apertura = diferencia
    turno.justificacion_apertura = justificacion
    turno.tiene_cuadre_llegada = True

    db.add(EntregaTurno(
        turno_id=turno.id, tienda_id=turno.tienda_id, usuario_id=usuario_id,
        efectivo_real=efectivo_real, efectivo_esperado=esperado,
        base_snapshot=esperado, ventas_efectivo_snapshot=0.0,
        ingresos_snapshot=0.0, egresos_snapshot=0.0,
        ventas_efectivo_siigo=0.0, ventas_tarjeta_bold=0.0,
        diferencia_efectivo=diferencia, diferencia_tarjeta=0.0,
        imagen_url=None, tipo="apertura",
        barista_id=barista_id, barista_nombre=barista_nombre,
    ))
    audit.registrar(
        db, accion="cuadre_inicial", tabla="caja_turnos",
        registro_id=turno.id, usuario_id=usuario_id, tienda_id=turno.tienda_id,
        datos_despues={"efectivo_real": efectivo_real, "esperado": esperado,
                       "diferencia": diferencia, "justificacion": justificacion},
    )
    db.commit()
    return get_turno_activo(db, turno.tienda_id)


def ajustar_apertura(db: Session, turno_id: int, base_real: float,
                     caja_fuerte: float | None, usuario_id: int, motivo: str | None = None):
    """Corrección admin de la apertura de un turno: ajusta la base real de la registradora
    y la caja fuerte, y recalcula la diferencia de apertura. Con auditoría. Sirve para
    corregir errores como meter la caja fuerte dentro de la base."""
    turno = db.query(CajaTurno).filter(CajaTurno.id == turno_id).first()
    if not turno:
        raise HTTPException(status_code=404, detail="Turno no encontrado")
    if base_real < 0 or (caja_fuerte is not None and caja_fuerte < 0):
        raise HTTPException(status_code=400, detail="Los valores no pueden ser negativos")

    antes = {
        "base_real": float(turno.base_real or 0),
        "caja_fuerte": float(turno.caja_fuerte or 0),
        "diferencia_apertura": float(turno.diferencia_apertura or 0),
    }
    turno.base_real = base_real
    if caja_fuerte is not None:
        turno.caja_fuerte = caja_fuerte
    turno.diferencia_apertura = base_real - (turno.base_sistema or 0)

    audit.registrar(
        db, accion="ajuste_apertura", tabla="caja_turnos",
        registro_id=turno.id, usuario_id=usuario_id, tienda_id=turno.tienda_id,
        datos_antes=antes,
        datos_despues={"base_real": base_real, "caja_fuerte": caja_fuerte,
                       "diferencia_apertura": turno.diferencia_apertura, "motivo": motivo},
    )
    db.commit()
    if turno.estado == EstadoTurnoEnum.abierto:
        return get_turno_activo(db, turno.tienda_id)
    db.refresh(turno)
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

    # Cuadre efectivo: esperado = base + ventas efectivo (POS) + ingresos - egresos
    efectivo_ventas = efectivo_final_real - turno.base_real
    efectivo_esperado = turno.base_real + turno.total_efectivo + ingresos - egresos
    diferencia_cierre = efectivo_final_real - efectivo_esperado

    # Cuadre datáfono: total Bold contado vs ventas tarjeta del POS
    diferencia_tarjeta = (datafono_real - turno.total_tarjeta) if datafono_real is not None else None

    hay_diff = round(diferencia_cierre, 2) != 0 or (diferencia_tarjeta is not None and round(diferencia_tarjeta, 2) != 0)
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

    # Cerrar el día operativo cuando se cierra un turno de tipo 'cierre' (último del día)
    if turno.tipo_turno == TipoTurnoEnum.cierre and turno.dia_operativo_id:
        dia = db.query(DiaOperativo).filter(DiaOperativo.id == turno.dia_operativo_id).first()
        if dia and dia.estado != EstadoDiaEnum.cerrado:
            dia.estado = EstadoDiaEnum.cerrado
            dia.cerrado_por_id = usuario_id
            dia.fecha_cierre = datetime.utcnow()

    _tick_checklist(db, turno.tienda_id, cierre_realizado=True)
    audit.registrar(
        db, accion="cierre_caja", tabla="caja_turnos",
        registro_id=turno_id, usuario_id=usuario_id, tienda_id=turno.tienda_id,
        datos_despues={"efectivo_final_real": efectivo_final_real,
                       "diferencia_cierre": diferencia_cierre,
                       "diferencia_tarjeta": diferencia_tarjeta,
                       "justificacion": justificacion},
    )
    # Etapa 7+: notificación de descuadre por el motor de reglas (canal_bell/push).
    # El umbral de la regla actúa como TOLERANCIA: solo avisa si |diferencia| la supera.
    if diferencia_cierre is not None and round(diferencia_cierre, 2) != 0:
        from app.services import notif_reglas
        regla = notif_reglas.get_regla(db, turno.tienda_id, "descuadre_caja")
        tolerancia = (regla.umbral or 0) if regla else 0
        if abs(diferencia_cierre) > tolerancia:
            nivel = "critico" if abs(diferencia_cierre) > 10000 else "advertencia"
            msg = f"Diferencia de ${diferencia_cierre:,.0f} en cierre de turno #{turno_id}"
            notificaciones.disparar(
                db, tienda_id=turno.tienda_id, tipo="descuadre_caja",
                mensaje=msg, nivel=nivel, referencia_id=turno_id,
                push_titulo="Descuadre de caja", push_cuerpo=msg,
            )
    db.commit()
    db.refresh(turno)
    logger.info(f"Turno {turno.id} cerrado. Δefectivo: {diferencia_cierre}, Δtarjeta: {diferencia_tarjeta}")
    return turno


def registrar_entrega(db: Session, turno_id: int, usuario_id: int,
                      efectivo_real: float,
                      ventas_tarjeta_bold: float, imagen_url: str | None,
                      barista_id: int | None = None, barista_nombre: str | None = None):
    turno = db.query(CajaTurno).filter(
        CajaTurno.id == turno_id,
        CajaTurno.estado == EstadoTurnoEnum.abierto
    ).first()
    if not turno:
        raise HTTPException(status_code=404, detail="No hay turno activo")
    # Los turnos intermedio/cierre NO repiten el conteo de apertura: heredan la línea base
    # del día. Validar contra el día (no contra el flag del turno individual) para no bloquear
    # ni el cierre ni la entrada-con-cuadre de esos turnos.
    if not _hay_conteo_apertura_en_dia(db, turno):
        raise HTTPException(status_code=400, detail="Debes completar el conteo de apertura antes de registrar una entrega")
    if efectivo_real < 0 or ventas_tarjeta_bold < 0:
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
    diferencia_efectivo = efectivo_real - efectivo_esperado
    diferencia_tarjeta = ventas_tarjeta_bold - turno.total_tarjeta

    entrega = EntregaTurno(
        turno_id=turno_id,
        tienda_id=turno.tienda_id,
        usuario_id=usuario_id,
        efectivo_real=efectivo_real,
        efectivo_esperado=efectivo_esperado,
        base_snapshot=turno.base_real,
        ventas_efectivo_snapshot=turno.total_efectivo,
        ingresos_snapshot=ingresos,
        egresos_snapshot=egresos,
        ventas_efectivo_siigo=0.0,  # remanente dormido: el esperado ya sale del POS (turno.total_efectivo)
        ventas_tarjeta_bold=ventas_tarjeta_bold,
        diferencia_efectivo=diferencia_efectivo,
        diferencia_tarjeta=diferencia_tarjeta,
        imagen_url=imagen_url,
        barista_id=barista_id,
        barista_nombre=barista_nombre,
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


def get_entregas_tienda(db: Session, tienda_id: int, limit: int | None = None, solo_hoy: bool = True):
    q = db.query(EntregaTurno).filter(EntregaTurno.tienda_id == tienda_id)
    if solo_hoy:
        hoy = hoy_col()
        q = q.filter(EntregaTurno.fecha_hora >= inicio_dia_col_utc(hoy),
                     EntregaTurno.fecha_hora <= fin_dia_col_utc(hoy))
    return q.order_by(EntregaTurno.fecha_hora.desc()).limit(limit).all()


def registrar_movimiento(db: Session, turno_id: int, tipo: str, concepto: str,
                         valor: float, usuario_id: int, imagen_url: str | None = None,
                         barista_id: int | None = None, barista_nombre: str | None = None):
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
        usuario_id=usuario_id,
        imagen_url=imagen_url,
        barista_id=barista_id,
        barista_nombre=barista_nombre,
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


def registrar_cuadre_llegada(db: Session, turno_id: int, usuario_id: int,
                              efectivo_real: float, tipo_turno: str, nota: str | None = None,
                              barista_id: int | None = None, barista_nombre: str | None = None):
    turno = db.query(CajaTurno).filter(
        CajaTurno.id == turno_id,
        CajaTurno.estado == EstadoTurnoEnum.abierto
    ).first()
    if not turno:
        raise HTTPException(status_code=404, detail="No hay turno activo")
    if efectivo_real < 0:
        raise HTTPException(status_code=400, detail="El valor no puede ser negativo")

    ingresos = db.query(func.sum(MovimientoCaja.valor)).filter(
        MovimientoCaja.caja_turno_id == turno_id,
        MovimientoCaja.tipo == "ingreso"
    ).scalar() or 0.0
    egresos = db.query(func.sum(MovimientoCaja.valor)).filter(
        MovimientoCaja.caja_turno_id == turno_id,
        MovimientoCaja.tipo == "egreso"
    ).scalar() or 0.0
    efectivo_esperado = turno.base_real + turno.total_efectivo + ingresos - egresos
    diferencia = efectivo_real - efectivo_esperado

    entrega = EntregaTurno(
        turno_id=turno_id,
        tienda_id=turno.tienda_id,
        usuario_id=usuario_id,
        efectivo_real=efectivo_real,
        efectivo_esperado=efectivo_esperado,
        base_snapshot=turno.base_real,
        ventas_efectivo_snapshot=turno.total_efectivo,
        ingresos_snapshot=ingresos,
        egresos_snapshot=egresos,
        ventas_efectivo_siigo=0.0,
        ventas_tarjeta_bold=0.0,
        diferencia_efectivo=diferencia,
        diferencia_tarjeta=0.0,
        imagen_url=None,
        tipo="recibo",
        barista_id=barista_id,
        barista_nombre=barista_nombre,
    )
    db.add(entrega)
    turno.tiene_cuadre_llegada = True
    audit.registrar(
        db, accion="cuadre_llegada", tabla="entregas_turno",
        registro_id=None, usuario_id=usuario_id, tienda_id=turno.tienda_id,
        datos_despues={"tipo_turno": tipo_turno, "efectivo_real": efectivo_real,
                       "efectivo_esperado": efectivo_esperado, "diferencia": diferencia},
    )
    db.commit()
    db.refresh(entrega)
    return entrega


def get_movimientos(db: Session, turno_id: int):
    return db.query(MovimientoCaja).filter(
        MovimientoCaja.caja_turno_id == turno_id
    ).order_by(MovimientoCaja.fecha.desc()).all()


def _mov_tipo(m) -> str:
    return str(m.tipo.value if hasattr(m.tipo, "value") else m.tipo)


def get_entrega_desglose(db: Session, entrega_id: int) -> dict | None:
    """Desglose del efectivo esperado de UN cuadre puntual (transparencia + histórico).

    Usa el snapshot congelado al momento del cuadre (base/ventas_efectivo/ingresos/egresos).
    Para cuadres previos a esta feature (sin snapshot), reconstruye best-effort desde el turno
    y los movimientos hasta la hora del cuadre. Incluye la lista de movimientos de caja
    (ingresos/egresos) registrados hasta ese instante, para que se vea de dónde sale el número.
    """
    e = db.query(EntregaTurno).filter(EntregaTurno.id == entrega_id).first()
    if not e:
        return None

    movimientos = db.query(MovimientoCaja).filter(
        MovimientoCaja.caja_turno_id == e.turno_id,
        MovimientoCaja.fecha <= e.fecha_hora,
    ).order_by(MovimientoCaja.fecha.asc()).all()

    turno = db.query(CajaTurno).filter(CajaTurno.id == e.turno_id).first()
    caja_fuerte = float(turno.caja_fuerte) if turno and turno.caja_fuerte is not None else 0.0

    tiene_snapshot = e.base_snapshot is not None
    if tiene_snapshot:
        base = float(e.base_snapshot or 0)
        ventas_efectivo = float(e.ventas_efectivo_snapshot or 0)
        ingresos = float(e.ingresos_snapshot or 0)
        egresos = float(e.egresos_snapshot or 0)
    else:
        # Cuadre viejo: reconstruir lo posible sin romper. base del turno; ingresos/egresos
        # hasta la hora del cuadre; ventas_efectivo se despeja del esperado ya guardado.
        base = float(turno.base_real or 0) if turno else 0.0
        ingresos = sum(float(m.valor) for m in movimientos if _mov_tipo(m) == "ingreso")
        egresos = sum(float(m.valor) for m in movimientos if _mov_tipo(m) == "egreso")
        ventas_efectivo = float(e.efectivo_esperado or 0) - base - ingresos + egresos

    esperado = base + ventas_efectivo + ingresos - egresos

    return {
        "entrega_id": e.id,
        "turno_id": e.turno_id,
        "tipo": e.tipo,
        "fecha_hora": e.fecha_hora.isoformat() if e.fecha_hora else None,
        "barista": e.barista_nombre or (e.usuario.nombre if e.usuario else None),
        "base": round(base, 2),
        "ventas_efectivo": round(ventas_efectivo, 2),
        "ingresos": round(ingresos, 2),
        "egresos": round(egresos, 2),
        "caja_fuerte": round(caja_fuerte, 2),
        "efectivo_esperado": round(esperado, 2),
        "efectivo_real": float(e.efectivo_real or 0),
        "diferencia_efectivo": float(e.diferencia_efectivo or 0),
        "tiene_snapshot": tiene_snapshot,
        "movimientos": [
            {
                "tipo": _mov_tipo(m),
                "concepto": m.concepto,
                "valor": float(m.valor),
                "fecha": m.fecha.isoformat() if m.fecha else None,
            }
            for m in movimientos
        ],
    }


def get_efectivo_inicio_esperado(db: Session, tienda_id: int):
    """Efectivo de inicio esperado = lo que quedó en caja al último cierre, menos lo consignado.

    Es la 'bolsa' de efectivo que corre entre días (pendiente de consignar). Coincide con el
    base_sistema que calcula abrir_caja. Sirve para que el barista cuente el efectivo de inicio
    contra esta expectativa al abrir el turno (cuadre unificado)."""
    ultimo = db.query(CajaTurno).filter(
        CajaTurno.tienda_id == tienda_id,
        CajaTurno.estado == EstadoTurnoEnum.cerrado,
    ).order_by(CajaTurno.fecha_cierre.desc()).first()
    if not ultimo:
        return {"esperado": 0.0, "hay_cierre_previo": False, "fecha_ultimo_cierre": None}
    consigs = db.query(func.sum(Consignacion.valor)).filter(
        Consignacion.caja_turno_id == ultimo.id,
        Consignacion.estado == EstadoConsignacionEnum.realizada,
    ).scalar() or 0.0
    esperado = (ultimo.efectivo_final_real or 0.0) - consigs
    return {
        "esperado": round(esperado, 2),
        "hay_cierre_previo": True,
        "fecha_ultimo_cierre": ultimo.fecha_cierre.isoformat() if ultimo.fecha_cierre else None,
    }


def get_dia_operativo_actual(db: Session, tienda_id: int):
    """Contexto del día operativo de hoy: resumen + turnos, para continuidad.

    Devuelve None si aún no se abrió ningún turno hoy. Lectura para el kiosko/admin.
    """
    fecha = _fecha_operativa()
    dia = db.query(DiaOperativo).filter(
        DiaOperativo.tienda_id == tienda_id,
        DiaOperativo.fecha_operativa == fecha,
    ).first()
    if not dia:
        return None
    turnos = db.query(CajaTurno).filter(
        CajaTurno.dia_operativo_id == dia.id
    ).order_by(CajaTurno.secuencia_dia).all()

    def _val(v):
        return v.value if hasattr(v, "value") else v

    return {
        "id": dia.id,
        "tienda_id": dia.tienda_id,
        "fecha_operativa": dia.fecha_operativa.isoformat(),
        "estado": _val(dia.estado),
        "total_ventas": round(sum(t.total_ventas or 0.0 for t in turnos), 2),
        "total_efectivo": round(sum(t.total_efectivo or 0.0 for t in turnos), 2),
        "total_tarjeta": round(sum(t.total_tarjeta or 0.0 for t in turnos), 2),
        "n_turnos": len(turnos),
        "turnos": [
            {
                "id": t.id,
                "tipo_turno": _val(t.tipo_turno) if t.tipo_turno else None,
                "secuencia_dia": t.secuencia_dia,
                "estado": _val(t.estado),
                "total_ventas": round(t.total_ventas or 0.0, 2),
                "tiene_conteo_apertura": t.tiene_conteo_apertura,
                "fecha_apertura": t.fecha_apertura.isoformat() if t.fecha_apertura else None,
                "fecha_cierre": t.fecha_cierre.isoformat() if t.fecha_cierre else None,
            }
            for t in turnos
        ],
    }


def get_flujo_turno(db: Session, turno_id: int) -> dict | None:
    turno = db.query(CajaTurno).filter(CajaTurno.id == turno_id).first()
    if not turno:
        return None

    barista = turno.usuario_apertura.nombre if turno.usuario_apertura else "—"

    movimientos = db.query(MovimientoCaja).filter(
        MovimientoCaja.caja_turno_id == turno_id
    ).all()

    consignaciones = db.query(Consignacion).filter(
        Consignacion.caja_turno_id == turno_id
    ).all()

    from app.models.models import TipoMovCajaEnum
    ingresos = sum(m.valor for m in movimientos if m.tipo == TipoMovCajaEnum.ingreso)
    egresos  = sum(m.valor for m in movimientos if m.tipo == TipoMovCajaEnum.egreso)
    consigs_sum = sum(c.valor for c in consignaciones)
    efectivo_esperado = (turno.base_real or 0) + (turno.total_efectivo or 0) + ingresos - egresos - consigs_sum

    return {
        "turno_id": turno.id,
        "barista": barista,
        "fecha_apertura": turno.fecha_apertura.isoformat(),
        "base_real": turno.base_real or 0,
        "ventas_total": turno.total_ventas or 0,
        "ventas_efectivo": turno.total_efectivo or 0,
        "ventas_tarjeta": turno.total_tarjeta or 0,
        "movimientos": [
            {"tipo": str(m.tipo.value if hasattr(m.tipo, 'value') else m.tipo),
             "concepto": m.concepto,
             "valor": m.valor}
            for m in movimientos
        ],
        "consignaciones": [
            {"id": c.id, "valor": c.valor, "fecha": c.fecha.isoformat()}
            for c in consignaciones
        ],
        "efectivo_esperado": efectivo_esperado,
        "efectivo_final_real": turno.efectivo_final_real,
        "diferencia_cierre": turno.diferencia_cierre,
    }


def registrar_entrada_barista(
    db: Session,
    turno_id: int,
    usuario_id: int,
    barista_id: int,
    imagen_url: str | None = None,
):
    turno = db.query(CajaTurno).filter(
        CajaTurno.id == turno_id,
        CajaTurno.estado == EstadoTurnoEnum.abierto,
    ).first()
    if not turno:
        raise HTTPException(status_code=404, detail="No hay turno activo")

    barista = db.query(Usuario).filter(
        Usuario.id == barista_id, Usuario.activo == True
    ).first()
    if not barista:
        raise HTTPException(status_code=404, detail="Barista no encontrada")

    # Add to shift roster — ignore if already registered
    from sqlalchemy.exc import IntegrityError as _IE
    try:
        db.add(TurnoBarista(turno_id=turno_id, usuario_id=barista_id, nombre_snapshot=barista.nombre))
        db.flush()
    except _IE:
        db.rollback()

    # Snapshot actual cash state (no manual count at entry)
    ingresos = db.query(func.sum(MovimientoCaja.valor)).filter(
        MovimientoCaja.caja_turno_id == turno_id, MovimientoCaja.tipo == "ingreso"
    ).scalar() or 0.0
    egresos = db.query(func.sum(MovimientoCaja.valor)).filter(
        MovimientoCaja.caja_turno_id == turno_id, MovimientoCaja.tipo == "egreso"
    ).scalar() or 0.0
    efectivo_esperado = turno.base_real + turno.total_efectivo + ingresos - egresos

    db.add(EntregaTurno(
        turno_id=turno_id, tienda_id=turno.tienda_id, usuario_id=usuario_id,
        efectivo_esperado=efectivo_esperado, efectivo_real=efectivo_esperado,
        base_snapshot=turno.base_real, ventas_efectivo_snapshot=turno.total_efectivo,
        ingresos_snapshot=ingresos, egresos_snapshot=egresos,
        ventas_efectivo_siigo=0.0, ventas_tarjeta_bold=turno.total_tarjeta,
        diferencia_efectivo=0.0, diferencia_tarjeta=0.0,
        imagen_url=imagen_url, barista_id=barista_id, barista_nombre=barista.nombre,
        tipo="entrada",
    ))
    audit.registrar(
        db, accion="entrada_barista", tabla="caja_turnos",
        registro_id=turno_id, usuario_id=usuario_id, tienda_id=turno.tienda_id,
        datos_despues={"barista_id": barista_id, "barista_nombre": barista.nombre},
    )
    db.commit()
    return get_turno_activo(db, turno.tienda_id)


def registrar_salida_barista(db: Session, turno_id: int, barista_nombre: str):
    """Marca la salida de UNA barista sin cerrar el turno.
    Sólo válido cuando hay más de una barista activa. Si es la última, usar cerrar_turno_rapido.
    """
    turno = db.query(CajaTurno).filter(
        CajaTurno.id == turno_id,
        CajaTurno.estado == EstadoTurnoEnum.abierto,
    ).first()
    if not turno:
        raise HTTPException(status_code=404, detail="Turno no encontrado o ya cerrado")

    tb = db.query(TurnoBarista).filter(
        TurnoBarista.turno_id == turno_id,
        TurnoBarista.nombre_snapshot == barista_nombre,
        TurnoBarista.salida_at.is_(None),
    ).first()
    if not tb:
        raise HTTPException(status_code=404, detail="Barista no encontrada en este turno o ya registró salida")

    tb.salida_at = datetime.utcnow()
    audit.registrar(
        db, accion="salida_barista", tabla="turno_baristas",
        registro_id=tb.id, usuario_id=tb.usuario_id, tienda_id=turno.tienda_id,
        datos_despues={"barista_nombre": barista_nombre},
    )
    db.commit()
    return get_turno_activo(db, turno.tienda_id)


def cerrar_turno_rapido(
    db: Session,
    turno_id: int,
    usuario_id: int,
    efectivo_final_real: float,
    datafono_real: float,
    imagen_url: str | None = None,
):
    turno = db.query(CajaTurno).filter(
        CajaTurno.id == turno_id,
        CajaTurno.estado == EstadoTurnoEnum.abierto,
    ).first()
    if not turno:
        raise HTTPException(status_code=404, detail="Turno no encontrado o ya cerrado")
    if efectivo_final_real < 0:
        raise HTTPException(status_code=400, detail="efectivo_final_real no puede ser negativo")
    if datafono_real < 0:
        raise HTTPException(status_code=400, detail="datafono_real no puede ser negativo")
    # El conteo de cierre es INDEPENDIENTE del cuadre (se registra desde el PC).
    # Se exige hecho ANTES de tocar nada — ya no se auto-marca desde el kiosko.
    if not turno.tiene_conteo_cierre:
        raise HTTPException(
            status_code=400,
            detail="Falta el conteo de cierre — se registra desde el PC en Gestión de turno",
        )

    ingresos = db.query(func.sum(MovimientoCaja.valor)).filter(
        MovimientoCaja.caja_turno_id == turno_id, MovimientoCaja.tipo == "ingreso"
    ).scalar() or 0.0
    egresos = db.query(func.sum(MovimientoCaja.valor)).filter(
        MovimientoCaja.caja_turno_id == turno_id, MovimientoCaja.tipo == "egreso"
    ).scalar() or 0.0
    efectivo_esperado = turno.base_real + turno.total_efectivo + ingresos - egresos

    # Record closure proof photo with the real counted vs expected diff
    if imagen_url:
        db.add(EntregaTurno(
            turno_id=turno_id, tienda_id=turno.tienda_id, usuario_id=usuario_id,
            efectivo_esperado=efectivo_esperado, efectivo_real=efectivo_final_real,
            base_snapshot=turno.base_real, ventas_efectivo_snapshot=turno.total_efectivo,
            ingresos_snapshot=ingresos, egresos_snapshot=egresos,
            ventas_efectivo_siigo=0.0, ventas_tarjeta_bold=datafono_real,
            diferencia_efectivo=round(efectivo_final_real - efectivo_esperado, 2),
            diferencia_tarjeta=round(datafono_real - turno.total_tarjeta, 2),
            imagen_url=imagen_url, tipo="salida",
        ))

    # Always provide justification so cerrar_caja doesn't 400 on diffs
    justificacion = "Salida desde kiosco — efectivo contado por barista"
    return cerrar_caja(db, turno_id, efectivo_final_real, justificacion, usuario_id, datafono_real)


def _tick_checklist(db: Session, tienda_id: int, **kwargs):
    """Actualiza el checklist del día como efecto secundario — idempotente."""
    hoy = hoy_col()
    checklist = db.query(ChecklistDiario).filter(
        ChecklistDiario.tienda_id == tienda_id,
        ChecklistDiario.fecha >= inicio_dia_col_utc(hoy),
        ChecklistDiario.fecha <= fin_dia_col_utc(hoy),
    ).first()
    if not checklist:
        checklist = ChecklistDiario(tienda_id=tienda_id, fecha=datetime.utcnow())
        db.add(checklist)
        db.flush()
    for key, val in kwargs.items():
        setattr(checklist, key, val)
