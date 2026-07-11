from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timedelta, date
from fastapi import HTTPException
from app.models.models import (CajaTurno, MovimientoCaja, ChecklistDiario, EstadoTurnoEnum,
                               EntregaTurno, Consignacion, EstadoConsignacionEnum, TurnoBarista,
                               Usuario, DiaOperativo, EstadoDiaEnum, TipoTurnoEnum)
from app.core.tz import hoy_col, inicio_dia_col_utc, fin_dia_col_utc, dia_col

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


def _base_desde_ultimo_cierre(ultimo, consigs_deducidas: float) -> float:
    """Base esperada del turno nuevo según el último cierre. Dos casos:

    - RELEVO DEL MISMO DÍA (turno intermedio/cierre tras un cierre de hoy): la caja
      no se vacía entre relevos — queda todo el efectivo del cierre menos lo ya
      consignado.
    - DÍA NUEVO: la base de AYER se consigna COMPLETA (los pagos de contado del día
      ya salieron de la venta del día, no cargan a esa consignación). Lo que queda
      en la registradora = contado al cierre − base de ayer, que equivale a ventas
      en efectivo + ingresos − egresos + diferencia del cierre. Regla del negocio
      definida por el dueño el 2-jul.

    El "mismo día" se ancla en el día que el turno OPERÓ (su fecha_apertura), no en
    la fecha del cierre: un turno de ayer cerrado administrativamente esta mañana es
    DÍA NUEVO (caso 3-jul: el cuadre inicial mostraba $2.152.892 en vez de $989.192
    porque el cierre a las 6am parecía relevo del mismo día)."""
    if ultimo is None:
        return 0.0
    dia_operado = dia_col(ultimo.fecha_apertura) if ultimo.fecha_apertura else (
        dia_col(ultimo.fecha_cierre) if ultimo.fecha_cierre else None)
    if dia_operado == _fecha_operativa():
        return (ultimo.efectivo_final_real or 0.0) - consigs_deducidas
    return max(0.0, (ultimo.efectivo_final_real or 0.0) - (ultimo.base_real or 0.0))


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
    activo = get_turno_activo(db, tienda_id)
    if activo:
        # Si el turno abierto es de un día anterior, decir EXACTAMENTE qué faltó y cómo
        # resolverlo (caso 3-jul: apertura bloqueada sin explicación).
        if activo.fecha_apertura and dia_col(activo.fecha_apertura) != _fecha_operativa():
            fecha = dia_col(activo.fecha_apertura).strftime("%d/%m")
            falta = ("faltó el cuadre de salida" if activo.tiene_conteo_cierre
                     else "faltan el conteo de cierre (PC) y el cuadre de salida (celular)")
            raise HTTPException(
                status_code=400,
                detail=(f"El turno del {fecha} quedó abierto: {falta}. Completalo desde Salida "
                        f"o pedile al administrador cerrarlo desde Cuadres."),
            )
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
    base_sistema = _base_desde_ultimo_cierre(ultimo, consigs_deducidas)
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
                             barista_id: int | None = None, barista_nombre: str | None = None,
                             saldos_incluidos: list[int] | None = None):
    """Cuadre inicial de caja (flujo diferido): tras el conteo de inventario, se cuenta el
    efectivo de la registradora. Dos modos de ESPERADO:

    - saldos_incluidos (diseño del dueño, 6-jul): la barista marca QUÉ días con
      saldo pendiente por consignar están físicamente en la caja (a veces la
      consignación de un día fue $0 y conviven varios días). El esperado = suma
      de esos saldos, recalculada AQUÍ desde la verdad del servidor — jamás se
      confía la suma del cliente. La selección queda en auditoría.
    - Sin selección (legacy): lo que dejó el último cierre (base_sistema).

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

    seleccion_detalle = None
    if saldos_incluidos is not None:
        from app.services.consignaciones import _saldos_consignacion
        pendientes = {
            s["turno"].id: s
            for s in _saldos_consignacion(db, turno.tienda_id)
            if round(s["saldo"], 2) > 0
        }
        esperado = 0.0
        seleccion_detalle = []
        for tid in saldos_incluidos:
            s = pendientes.get(tid)
            if not s:
                continue    # ese saldo ya no está pendiente (p.ej. se consignó hace un momento)
            esperado += s["saldo"]
            seleccion_detalle.append({
                "turno_id": tid,
                "fecha": s["turno"].fecha_apertura.isoformat() if s["turno"].fecha_apertura else None,
                "saldo": round(s["saldo"], 2),
            })
        esperado = round(esperado, 2)
        # El esperado del día queda anclado a la selección (visible en timeline/cuadres)
        turno.base_sistema = esperado
    else:
        esperado = turno.base_sistema or 0.0
    diferencia = efectivo_real - esperado
    if round(diferencia, 2) != 0 and not justificacion:
        raise HTTPException(
            status_code=400,
            detail=f"Diferencia de ${diferencia:,.0f} detectada. Se requiere justificación."
        )

    turno.base_real = efectivo_real
    turno.diferencia_apertura = diferencia
    # Sobrante al abrir: plata extra sin dueño de días anteriores → debe bancarse
    # con ESTE turno (entra al esperado a consignar). El faltante no: es novedad.
    turno.sobrante_consignable = max(0.0, round(diferencia, 2))
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
                       "diferencia": diferencia, "justificacion": justificacion,
                       "saldos_incluidos": seleccion_detalle},
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

    # El cuadre de cierre ES el cuadre de salida de las últimas baristas: marcar la
    # salida de todas las que sigan en turno (regla del dueño 3-jul — antes quedaban
    # "en turno" si el flujo se abandonaba y el negocio abierto sin que nadie lo diga).
    for tb in db.query(TurnoBarista).filter(
        TurnoBarista.turno_id == turno_id,
        TurnoBarista.salida_at.is_(None),
    ).all():
        tb.salida_at = datetime.utcnow()

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


def cerrar_turno_administrativo(db: Session, turno_id: int, usuario_id: int):
    """Cierre administrativo de un turno huérfano (quedó abierto de un día anterior):
    cierra con el esperado (diferencia 0) y justificación explícita. La diferencia
    real la captura el cuadre inicial del día siguiente. Requiere el conteo de
    cierre hecho — el inventario no se salta."""
    turno = db.query(CajaTurno).filter(
        CajaTurno.id == turno_id,
        CajaTurno.estado == EstadoTurnoEnum.abierto,
    ).first()
    if not turno:
        raise HTTPException(status_code=404, detail="Turno no encontrado o ya cerrado")
    if not turno.tiene_conteo_cierre:
        raise HTTPException(
            status_code=400,
            detail="Falta el conteo de cierre: la sede debe registrarlo desde el PC antes del cierre administrativo",
        )
    ingresos = db.query(func.sum(MovimientoCaja.valor)).filter(
        MovimientoCaja.caja_turno_id == turno_id, MovimientoCaja.tipo == "ingreso"
    ).scalar() or 0.0
    egresos = db.query(func.sum(MovimientoCaja.valor)).filter(
        MovimientoCaja.caja_turno_id == turno_id, MovimientoCaja.tipo == "egreso"
    ).scalar() or 0.0
    esperado = turno.base_real + turno.total_efectivo + ingresos - egresos
    justificacion = ("Cierre administrativo: el cuadre de salida no se realizó. Se cierra con el "
                     "esperado (diferencia 0); la diferencia real la captura el cuadre inicial siguiente.")
    return cerrar_caja(db, turno_id, esperado, justificacion, usuario_id,
                       datafono_real=turno.total_tarjeta if turno.total_tarjeta else None)


def reabrir_conteo_cierre(db: Session, turno_id: int, usuario_id: int):
    """El conteo de cierre CONGELA las ventas del turno (pos.py bloquea facturar).
    Si la sede lo registró antes de tiempo (adelantaron el conteo y el POS quedó
    bloqueado), el admin lo reabre: el turno vuelve a vender y el conteo REAL debe
    registrarse de nuevo al cierre (el guard de registrar_conteo es por flag, y la
    referencia/conciliación toman el conteo más reciente). Solo-admin."""
    from app.models.models import ConteoFisico, TipoConteoEnum
    turno = db.query(CajaTurno).filter(
        CajaTurno.id == turno_id,
        CajaTurno.estado == EstadoTurnoEnum.abierto,
    ).first()
    if not turno:
        raise HTTPException(status_code=404, detail="Turno no encontrado o ya cerrado")

    # El índice único permite UN conteo de cierre por turno: el adelantado se
    # RECLASIFICA como 'existencia' (queda como registro histórico, visible en el
    # monitor) para liberar el lugar del cierre real. Sin esto, el nuevo conteo
    # chocaba contra el índice aunque el flag estuviera reabierto.
    adelantados = db.query(ConteoFisico).filter(
        ConteoFisico.turno_id == turno_id,
        ConteoFisico.tipo == TipoConteoEnum.cierre,
    ).all()
    if not turno.tiene_conteo_cierre and not adelantados:
        raise HTTPException(status_code=400, detail="El turno no tiene conteo de cierre registrado")
    for c in adelantados:
        c.tipo = TipoConteoEnum.existencia

    turno.tiene_conteo_cierre = False
    turno.ts_conteo_cierre = None
    audit.registrar(
        db, accion="reabrir_conteo_cierre", tabla="caja_turnos",
        registro_id=turno_id, usuario_id=usuario_id, tienda_id=turno.tienda_id,
        datos_despues={"motivo": "conteo de cierre adelantado — se reabre la venta; el conteo real se registra al cierre",
                       "conteos_reclasificados": [c.id for c in adelantados]},
    )
    db.commit()
    return get_turno_activo(db, turno.tienda_id)


def cancelar_turno_vacio(db: Session, turno_id: int, usuario_id: int) -> dict:
    """Elimina un turno ABIERTO SIN actividad (abierto por error o para demo): sin
    ventas, sin movimientos de caja, sin conteos, sin entregas. Borra también sus
    baristas asociados (cascade). Si tiene CUALQUIER actividad se rechaza — para eso
    está el cierre normal/administrativo. Solo-admin."""
    turno = db.query(CajaTurno).filter(CajaTurno.id == turno_id).first()
    if not turno:
        raise HTTPException(status_code=404, detail="Turno no encontrado")
    if turno.estado != EstadoTurnoEnum.abierto:
        raise HTTPException(status_code=400, detail="Solo se puede cancelar un turno abierto")

    actividad = []
    if (turno.total_ventas or 0) or (turno.total_efectivo or 0) or (turno.total_tarjeta or 0):
        actividad.append("ventas")
    if turno.tiene_ventas or turno.tiene_conteo_apertura or turno.tiene_conteo_cierre:
        actividad.append("cuadre/conteo")
    if turno.movimientos:
        actividad.append("movimientos de caja")
    if turno.ventas:
        actividad.append("ventas registradas")
    if turno.conteos:
        actividad.append("conteos")
    if turno.entregas:
        actividad.append("entregas")
    if actividad:
        raise HTTPException(status_code=400, detail=(
            f"El turno tiene actividad ({', '.join(actividad)}); no se puede cancelar. "
            "Usá el cierre normal o administrativo."))

    audit.registrar(
        db, accion="cancelar_turno_vacio", tabla="caja_turnos",
        registro_id=turno_id, usuario_id=usuario_id, tienda_id=turno.tienda_id,
        datos_antes={"fecha_apertura": str(turno.fecha_apertura),
                     "baristas": [b.nombre_snapshot for b in turno.baristas_turno]},
    )
    try:
        db.delete(turno)   # cascade → turno_baristas
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=400,
                            detail="El turno tiene registros asociados; no se puede cancelar")
    return {"cancelado": turno_id}


def _msg_pagos_superan_venta(entrada_dia: float, egresos: float) -> str:
    """Cuadre con 'venta de ayer separada' cuando los pagos superan la venta del día:
    la plata que faltó salió físicamente del sobre separado, así que contar 'solo la
    registradora' ya no representa nada — se cuenta todo junto."""
    faltante = egresos - entrada_dia
    return (
        f"Los pagos de hoy (${egresos:,.0f}) superan la venta en efectivo del día (${entrada_dia:,.0f}): "
        f"${faltante:,.0f} salieron de la plata separada. "
        "Destildá la casilla y contá TODO junto: registradora + lo que quede de lo separado."
    )


def registrar_entrega(db: Session, turno_id: int, usuario_id: int,
                      efectivo_real: float,
                      ventas_tarjeta_bold: float, imagen_url: str | None,
                      barista_id: int | None = None, barista_nombre: str | None = None,
                      base_separada: bool = False, tipo_cuadre: str = "entrega"):
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
    # Sin cuadre inicial base_real=0: el esperado saldría sin la base y el snapshot
    # persistido quedaría erróneo. El cuadre inicial va primero, siempre.
    if not turno.tiene_cuadre_llegada:
        raise HTTPException(status_code=400, detail="Falta el cuadre inicial de caja — completalo antes de registrar cuadres")
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
    if base_separada:
        # Venta de ayer separada y guardada: la barista cuenta SOLO la registradora.
        # El monto separado (la base) queda documentado en base_snapshot sin contarse.
        efectivo_esperado -= turno.base_real
        if efectivo_esperado < 0:
            # Las salidas superan la venta del día: físicamente tuvieron que tocar la
            # plata separada, así que el cuadre "solo registradora" no tiene sentido.
            # El kiosko oculta la casilla en este caso; esto es el backstop para
            # clientes con bundle viejo — con los montos para que se entienda.
            raise HTTPException(
                status_code=400,
                detail=_msg_pagos_superan_venta(turno.total_efectivo + ingresos, egresos),
            )
    diferencia_efectivo = efectivo_real - efectivo_esperado
    diferencia_tarjeta = ventas_tarjeta_bold - turno.total_tarjeta

    entrega = EntregaTurno(
        turno_id=turno_id,
        tienda_id=turno.tienda_id,
        usuario_id=usuario_id,
        efectivo_real=efectivo_real,
        efectivo_esperado=efectivo_esperado,
        base_separada=base_separada,
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
        # 'salida_barista' cuando una barista se va a mitad de turno (desde PanelSalida):
        # así el timeline lo rotula "Salida" y no "Llegada". Default 'entrega' (cuadre común).
        tipo=tipo_cuadre,
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


def get_turno_timeline(db: Session, turno_id: int) -> dict:
    """Timeline cronológico de un turno + resumen de baristas, para el hub de Cuadres.

    Eventos: apertura del turno, entradas/salidas de baristas y cada cuadre (EntregaTurno,
    con esperado/contado/diferencia). El resumen dice, por barista, cuándo entró/salió y
    cómo fue su último cuadre."""
    turno = db.query(CajaTurno).filter(CajaTurno.id == turno_id).first()
    if not turno:
        raise HTTPException(status_code=404, detail="Turno no encontrado")

    TIPO_LBL = {
        "apertura": "Cuadre inicial", "entrada": "Entrada de barista",
        "entrega": "Cuadre de llegada", "recibo": "Cuadre de llegada",
        "salida_barista": "Salida de barista", "salida": "Cuadre de cierre",
    }
    eventos = []

    # 1) Apertura del turno
    apertura_barista = db.query(TurnoBarista).filter(
        TurnoBarista.turno_id == turno_id
    ).order_by(TurnoBarista.created_at.asc()).first()
    eventos.append({
        "tipo": "apertura_turno",
        "titulo": "Apertura de turno",
        "fecha": turno.fecha_apertura.isoformat() if turno.fecha_apertura else None,
        "barista": apertura_barista.nombre_snapshot if apertura_barista else None,
        "detalle": f"Base ${float(turno.base_real or 0):,.0f}".replace(",", "."),
        "monto": float(turno.base_real or 0),
    })

    # 2) Entradas / salidas de baristas
    for tb in db.query(TurnoBarista).filter(TurnoBarista.turno_id == turno_id).all():
        eventos.append({
            "tipo": "barista_entra", "titulo": f"{tb.nombre_snapshot} entró al turno",
            "fecha": tb.created_at.isoformat() if tb.created_at else None,
            "barista": tb.nombre_snapshot, "detalle": None, "monto": None,
        })
        if tb.salida_at:
            eventos.append({
                "tipo": "barista_sale", "titulo": f"{tb.nombre_snapshot} marcó salida",
                "fecha": tb.salida_at.isoformat(),
                "barista": tb.nombre_snapshot, "detalle": None, "monto": None,
            })

    # 3) Cuadres (EntregaTurno)
    entregas = db.query(EntregaTurno).filter(
        EntregaTurno.turno_id == turno_id
    ).order_by(EntregaTurno.fecha_hora.asc()).all()
    for e in entregas:
        dif = float(e.diferencia_efectivo or 0)
        eventos.append({
            "tipo": "cuadre", "subtipo": e.tipo,
            "titulo": TIPO_LBL.get(e.tipo, "Cuadre"),
            "fecha": e.fecha_hora.isoformat() if e.fecha_hora else None,
            "barista": e.barista_nombre,
            "esperado": float(e.efectivo_esperado or 0),
            "contado": float(e.efectivo_real or 0),
            "diferencia": dif,
            "base_separada": bool(getattr(e, "base_separada", False)),
            "imagen_url": e.imagen_url,
            "entrega_id": e.id,
            "detalle": None, "monto": None,
        })

    # 4) Cierre del turno
    if turno.estado == EstadoTurnoEnum.cerrado and turno.fecha_cierre:
        eventos.append({
            "tipo": "cierre_turno", "titulo": "Cierre de turno",
            "fecha": turno.fecha_cierre.isoformat(),
            "barista": None,
            "detalle": (f"Diferencia ${float(turno.diferencia_cierre or 0):,.0f}".replace(",", ".")
                        if turno.diferencia_cierre else "Cuadró exacto"),
            "monto": float(turno.efectivo_final_real or 0),
        })

    eventos.sort(key=lambda x: x["fecha"] or "")

    # Resumen por barista
    resumen = []
    for tb in db.query(TurnoBarista).filter(TurnoBarista.turno_id == turno_id).all():
        cuadre = next((e for e in reversed(entregas)
                       if (e.barista_nombre or "") == tb.nombre_snapshot), None)
        resumen.append({
            "barista": tb.nombre_snapshot,
            "entro": tb.created_at.isoformat() if tb.created_at else None,
            "salio": tb.salida_at.isoformat() if tb.salida_at else None,
            "diferencia_cuadre": float(cuadre.diferencia_efectivo or 0) if cuadre else None,
        })

    # Movimientos de caja (ingresos/egresos: pagos a proveedor, cambio de sencilla…)
    # para mostrar el detalle al lado del turno sin un segundo request.
    movs = (
        db.query(MovimientoCaja)
        .filter(MovimientoCaja.caja_turno_id == turno_id)
        .order_by(MovimientoCaja.fecha.asc())
        .all()
    )
    movimientos = [
        {
            "tipo": _mov_tipo(m),
            "concepto": m.concepto,
            "valor": float(m.valor or 0),
            "fecha": m.fecha.isoformat() if m.fecha else None,
            "imagen_url": m.imagen_url,
        }
        for m in movs
    ]

    return {
        "turno_id": turno.id,
        "estado": turno.estado.value if turno.estado else None,
        "eventos": eventos,
        "resumen_baristas": resumen,
        "movimientos": movimientos,
    }


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
    # Antes del cuadre inicial la caja no tiene base fijada: un movimiento acá
    # desalinearía el esperado del propio cuadre inicial (que compara solo contra
    # lo que dejó el cierre anterior).
    if not turno.tiene_cuadre_llegada:
        raise HTTPException(status_code=400, detail="Falta el cuadre inicial de caja — completalo antes de registrar movimientos")
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
    base_separada = bool(getattr(e, "base_separada", False))
    if base_separada:
        # La venta de ayer estaba separada: el cuadre se hizo contra la registradora.
        esperado -= base

    return {
        "entrega_id": e.id,
        "turno_id": e.turno_id,
        "tipo": e.tipo,
        "fecha_hora": e.fecha_hora.isoformat() if e.fecha_hora else None,
        "barista": e.barista_nombre or (e.usuario.nombre if e.usuario else None),
        "base": round(base, 2),
        "base_separada": base_separada,
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
    """Efectivo esperado para el cuadre inicial. Coincide con el base_sistema que calcula
    abrir_caja (_base_desde_ultimo_cierre): en día nuevo = ventas en efectivo del día
    anterior + diferencia del cierre (la plata vieja va a consignación/proveedores); en
    relevo del mismo día = todo el efectivo del cierre menos lo consignado."""
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
    esperado = _base_desde_ultimo_cierre(ultimo, consigs)
    # Anclado en el día que el turno OPERÓ (igual que _base_desde_ultimo_cierre).
    mismo_dia = bool(ultimo.fecha_apertura and dia_col(ultimo.fecha_apertura) == _fecha_operativa())
    return {
        "esperado": round(esperado, 2),
        "hay_cierre_previo": True,
        "fecha_ultimo_cierre": ultimo.fecha_cierre.isoformat() if ultimo.fecha_cierre else None,
        "mismo_dia": mismo_dia,
        "efectivo_cierre_anterior": round(float(ultimo.efectivo_final_real or 0.0), 2),
        "base_consignar_anterior": round(float(ultimo.base_real or 0.0), 2),
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
    # El snapshot de entrada usa base_real: sin cuadre inicial quedaría con base 0.
    if not turno.tiene_cuadre_llegada:
        raise HTTPException(status_code=400, detail="Falta el cuadre inicial de caja — completalo antes de registrar entradas")

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


AUTO_CIERRE_VENTANA_MIN = 60


def _auto_cerrar_si_quedo_sin_baristas(db: Session, turno, usuario_id: int):
    """La salida de la ÚLTIMA barista cierra el turno server-side.

    2 turnos huérfanos en 2 días (3 y 4-jul): las baristas hicieron cuadres,
    conteo de cierre y salidas — pero el cierre dependía de OTRA llamada del
    front que se perdió (PWA cerrada / red). Si ya no queda nadie en turno, el
    conteo de cierre existe y hay un cuadre RECIENTE (≤60 min, para no inventar
    un cierre con números viejos), se cierra acá mismo con ese cuadre.
    Best-effort: si el cierre no aplica, la salida queda registrada igual y el
    turno lo cierra el admin (camino actual)."""
    quedan = db.query(TurnoBarista).filter(
        TurnoBarista.turno_id == turno.id,
        TurnoBarista.salida_at.is_(None),
    ).count()
    if quedan > 0 or not turno.tiene_conteo_cierre:
        return None
    ent = (
        db.query(EntregaTurno)
        .filter(EntregaTurno.turno_id == turno.id)
        .order_by(EntregaTurno.fecha_hora.desc())
        .first()
    )
    if not ent or not ent.fecha_hora:
        return None
    if (datetime.utcnow() - ent.fecha_hora).total_seconds() > AUTO_CIERRE_VENTANA_MIN * 60:
        return None
    # Mismas semánticas que cerrar_turno_rapido: si la venta de ayer estaba
    # separada, hacia el cierre viaja el total equivalente (contado + base).
    efectivo_total = float(ent.efectivo_real or 0) + (
        float(ent.base_snapshot or 0) if ent.base_separada else 0.0
    )
    try:
        return cerrar_caja(
            db, turno.id, efectivo_total,
            "Cierre automático: salida de la última barista (efectivo del último cuadre)",
            usuario_id, float(ent.ventas_tarjeta_bold or 0),
        )
    except HTTPException as e:
        logger.warning(f"Auto-cierre del turno {turno.id} no aplicado: {e.detail}")
        return None


def registrar_salida_barista(db: Session, turno_id: int, barista_nombre: str):
    """Marca la salida de UNA barista. Si con ella el turno queda sin baristas y el
    conteo de cierre está hecho, el turno se CIERRA automáticamente (server-side,
    con el último cuadre) — ya no depende de otra llamada del front."""
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

    cerrado = _auto_cerrar_si_quedo_sin_baristas(db, turno, tb.usuario_id)
    if cerrado is not None:
        return cerrado
    return get_turno_activo(db, turno.tienda_id)


def cerrar_turno_rapido(
    db: Session,
    turno_id: int,
    usuario_id: int,
    efectivo_final_real: float,
    datafono_real: float,
    imagen_url: str | None = None,
    base_separada: bool = False,
):
    turno = db.query(CajaTurno).filter(
        CajaTurno.id == turno_id,
        CajaTurno.estado == EstadoTurnoEnum.abierto,
    ).first()
    if not turno:
        # Idempotencia con el auto-cierre: si la salida de la última barista ya
        # cerró el turno hace instantes, este POST tardío del front NO debe
        # fallarle a la barista — el cierre que quería ya existe.
        ya_cerrado = db.query(CajaTurno).filter(
            CajaTurno.id == turno_id,
            CajaTurno.estado == EstadoTurnoEnum.cerrado,
        ).first()
        if (ya_cerrado and ya_cerrado.fecha_cierre
                and (datetime.utcnow() - ya_cerrado.fecha_cierre).total_seconds() < 600
                and (ya_cerrado.justificacion_cierre or "").startswith("Cierre automático")):
            return ya_cerrado
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
    # Venta de ayer separada: la barista contó SOLO la registradora. El cuadre se
    # evalúa contra el esperado de la registradora, y hacia cerrar_caja viaja el
    # total equivalente (registradora + base separada) para que la base de mañana
    # salga igual a la registradora de hoy (la venta de hoy).
    esperado_cuadre = efectivo_esperado - turno.base_real if base_separada else efectivo_esperado
    if base_separada and esperado_cuadre < 0:
        # El kiosko oculta la casilla en este caso; backstop para bundles viejos.
        raise HTTPException(
            status_code=400,
            detail=_msg_pagos_superan_venta(turno.total_efectivo + ingresos, egresos),
        )
    efectivo_total = efectivo_final_real + turno.base_real if base_separada else efectivo_final_real

    # Record closure proof photo with the real counted vs expected diff
    if imagen_url:
        db.add(EntregaTurno(
            turno_id=turno_id, tienda_id=turno.tienda_id, usuario_id=usuario_id,
            efectivo_esperado=esperado_cuadre, efectivo_real=efectivo_final_real,
            base_separada=base_separada,
            base_snapshot=turno.base_real, ventas_efectivo_snapshot=turno.total_efectivo,
            ingresos_snapshot=ingresos, egresos_snapshot=egresos,
            ventas_efectivo_siigo=0.0, ventas_tarjeta_bold=datafono_real,
            diferencia_efectivo=round(efectivo_final_real - esperado_cuadre, 2),
            diferencia_tarjeta=round(datafono_real - turno.total_tarjeta, 2),
            imagen_url=imagen_url, tipo="salida",
        ))

    # Always provide justification so cerrar_caja doesn't 400 on diffs
    justificacion = "Salida desde kiosco — efectivo contado por barista"
    if base_separada:
        justificacion += " (venta de ayer separada, sin contar)"
    return cerrar_caja(db, turno_id, efectivo_total, justificacion, usuario_id, datafono_real)


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
