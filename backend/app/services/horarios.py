"""Horario PLANEADO: armar la semana, ver el total contra la jornada vigente,
publicarlo y avisar a cada barista.

El planeado vive aparte de lo real (`TurnoBarista`) a propósito: son dos hechos
distintos —lo que se pidió y lo que pasó— y la diferencia entre los dos es
justamente la evidencia que el dueño necesita a fin de mes.

Las horas se manejan como texto "HH:MM" de reloj de pared Colombia. Un horario no
es un instante UTC: es una intención local ("entra a las 7"). Guardarlo así lo
deja inmune al huso y hace que la grilla del admin sea literalmente lo que se ve.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.models import (
    ContratoBarista, EstadoProgramadoEnum, RolEnum, TurnoProgramado, Usuario,
)
from app.services import notificaciones, tasas_laborales
from app.services.horas import lunes_de, restar_pausas as hsvc_restar_pausas

_HORA_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

DIAS_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


# ---------------------------------------------------------------------------
# Helpers de hora de pared
# ---------------------------------------------------------------------------

def validar_hora(valor: str, campo: str) -> str:
    if not isinstance(valor, str) or not _HORA_RE.match(valor.strip()):
        raise HTTPException(
            status_code=400,
            detail=f"{campo} tiene que ser una hora del día en formato HH:MM (ej. 07:00).")
    return valor.strip()


def _minutos(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def duracion_bruta_horas(hora_inicio: str, hora_fin: str) -> float:
    """Horas de PRESENCIA: de la entrada a la salida, almuerzo incluido. Si el fin
    es menor o igual al inicio, el turno cruza la medianoche y termina al día
    siguiente."""
    ini, fin = _minutos(hora_inicio), _minutos(hora_fin)
    if fin <= ini:
        fin += 24 * 60
    return (fin - ini) / 60.0


def duracion_horas(hora_inicio: str, hora_fin: str,
                   almuerzo_minutos: int | None = None) -> float:
    """Horas TRABAJADAS: la presencia menos el almuerzo.

    El almuerzo es descanso NO remunerado: no cuenta como jornada ni consume el
    tope semanal del art. 161 CST. Sin `almuerzo_minutos` (o en cero) devuelve lo
    mismo que devolvía antes de que existiera el descanso, que es lo que hace que
    los turnos viejos —todos sin almuerzo— sigan liquidando igual.
    """
    bruta = duracion_bruta_horas(hora_inicio, hora_fin)
    return max(0.0, bruta - max(0, int(almuerzo_minutos or 0)) / 60.0)


def _offset_minutos(hora_inicio: str, hora: str) -> int:
    """Minutos desde la entrada del turno hasta esa hora de pared. Si la hora es
    anterior a la entrada, es del día siguiente (el turno cruzó la medianoche)."""
    delta = _minutos(hora) - _minutos(hora_inicio)
    return delta + 24 * 60 if delta < 0 else delta


def rango_datetimes(fecha: date, hora_inicio: str, hora_fin: str) -> tuple[datetime, datetime]:
    """El turno planeado como par de datetimes LOCALES (hora Colombia), de la
    entrada a la salida y SIN descontar el almuerzo. No son UTC y no deben
    guardarse como tal. Para liquidar horas usá `tramos_datetimes`, que sí saca
    el descanso."""
    ini = datetime.combine(fecha, datetime.min.time()) + timedelta(minutes=_minutos(hora_inicio))
    fin = datetime.combine(fecha, datetime.min.time()) + timedelta(minutes=_minutos(hora_fin))
    if fin <= ini:
        fin += timedelta(days=1)
    return ini, fin


def pausa_datetimes(fecha: date, hora_inicio: str, hora_fin: str,
                    almuerzo_inicio: str | None,
                    almuerzo_minutos: int | None) -> tuple[datetime, datetime] | None:
    """El almuerzo como par de datetimes locales, o None si el turno no tiene.

    Se ancla al INICIO del turno y no a la fecha: en un turno 18:00→02:00 un
    almuerzo a las 00:30 es del día siguiente, y anclarlo a la fecha lo pondría
    dieciocho horas antes de que la persona entrara.
    """
    if not almuerzo_inicio or not almuerzo_minutos or int(almuerzo_minutos) <= 0:
        return None
    ini, _fin = rango_datetimes(fecha, hora_inicio, hora_fin)
    arranque = ini + timedelta(minutes=_offset_minutos(hora_inicio, almuerzo_inicio))
    return arranque, arranque + timedelta(minutes=int(almuerzo_minutos))


def tramos_datetimes(fecha: date, hora_inicio: str, hora_fin: str,
                     almuerzo_inicio: str | None = None,
                     almuerzo_minutos: int | None = None) -> list[tuple[datetime, datetime]]:
    """Los tramos de TIEMPO TRABAJADO del turno planeado, ya sin el almuerzo.

    Un turno sin almuerzo devuelve un solo tramo (idéntico a `rango_datetimes`);
    con almuerzo devuelve dos. Es lo que hay que darle a `services/horas`: así el
    descanso se descuenta de la franja en la que cae y los recargos de las horas
    que sí se trabajaron quedan intactos.
    """
    ini, fin = rango_datetimes(fecha, hora_inicio, hora_fin)
    pausa = pausa_datetimes(fecha, hora_inicio, hora_fin, almuerzo_inicio, almuerzo_minutos)
    if pausa is None:
        return [(ini, fin)]
    return hsvc_restar_pausas(ini, fin, [pausa])


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------

def validar_almuerzo(hora_inicio: str, hora_fin: str, almuerzo_inicio: str | None,
                     almuerzo_minutos: int | None) -> tuple[str | None, int | None]:
    """Normaliza el almuerzo del turno y lo valida contra el turno mismo.

    Devuelve `(None, None)` cuando el turno no tiene almuerzo — que es el caso de
    todos los turnos que ya existían y el default de los nuevos.

    Se exigen los DOS datos juntos: la hora sola no dice cuánto dura y los
    minutos solos no dicen de qué franja sacarlos (un almuerzo diurno y uno
    nocturno cuestan distinto). Y el descanso tiene que caber ENTERO y con
    trabajo de los dos lados: un "almuerzo" pegado a la entrada o a la salida no
    es un descanso, es un turno más corto, y conviene escribirlo así.
    """
    minutos = int(almuerzo_minutos or 0)
    hora = (almuerzo_inicio or "").strip() or None

    if minutos <= 0 and hora is None:
        return None, None
    if minutos <= 0:
        raise HTTPException(
            status_code=400,
            detail="Pusiste hora de almuerzo pero no cuánto dura. Indicá los minutos.")
    if hora is None:
        raise HTTPException(
            status_code=400,
            detail="Falta a qué hora arranca el almuerzo: sin eso no se sabe si sale "
                   "de horas diurnas o nocturnas, que se pagan distinto.")

    hora = validar_hora(hora, "La hora de almuerzo")
    total = int(round(duracion_bruta_horas(hora_inicio, hora_fin) * 60))
    arranque = _offset_minutos(hora_inicio, hora)
    if arranque <= 0 or arranque + minutos >= total:
        raise HTTPException(
            status_code=400,
            detail=f"El almuerzo tiene que quedar adentro del turno "
                   f"({hora_inicio} a {hora_fin}) y dejar trabajo antes y después. "
                   f"{hora} por {minutos} min no entra.")
    return hora, minutos


def _barista(db: Session, usuario_id: int) -> Usuario:
    u = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if u is None or not u.activo:
        raise HTTPException(status_code=404, detail="Esa barista no existe o está inactiva.")
    return u


def guardar_turno(db: Session, tienda_id: int, usuario_id: int, fecha: date,
                  hora_inicio: str, hora_fin: str, creado_por_id: int | None = None,
                  nota: str | None = None, almuerzo_inicio: str | None = None,
                  almuerzo_minutos: int | None = None) -> TurnoProgramado:
    """Crea o actualiza un turno planeado.

    La clave natural es (barista, fecha, hora de entrada): volver a guardar la
    misma entrada EDITA el turno en vez de duplicarlo, que es lo que el admin
    espera cuando arrastra la hora de salida en la grilla.

    Si el turno YA estaba publicado, el cambio le avisa a la barista. Sobre un
    borrador no molesta a nadie: todavía se está armando la semana.
    """
    hora_inicio = validar_hora(hora_inicio, "La hora de entrada")
    hora_fin = validar_hora(hora_fin, "La hora de salida")
    if hora_inicio == hora_fin:
        # Entrada y salida iguales es ambiguo (¿cero horas o veinticuatro?), y
        # ninguna de las dos lecturas es un turno de cafetería.
        raise HTTPException(
            status_code=400,
            detail="La entrada y la salida no pueden ser la misma hora.")
    almuerzo_inicio, almuerzo_minutos = validar_almuerzo(
        hora_inicio, hora_fin, almuerzo_inicio, almuerzo_minutos)

    u = _barista(db, usuario_id)
    fila = db.query(TurnoProgramado).filter(
        TurnoProgramado.usuario_id == usuario_id,
        TurnoProgramado.fecha == fecha,
        TurnoProgramado.hora_inicio == hora_inicio,
    ).first()

    if fila is None:
        fila = TurnoProgramado(
            tienda_id=tienda_id, usuario_id=usuario_id, nombre_snapshot=u.nombre,
            fecha=fecha, hora_inicio=hora_inicio, hora_fin=hora_fin,
            almuerzo_inicio=almuerzo_inicio, almuerzo_minutos=almuerzo_minutos,
            estado=EstadoProgramadoEnum.borrador, nota=nota,
            creado_por_id=creado_por_id,
        )
        db.add(fila)
        db.commit()
        db.refresh(fila)
        return fila

    cambio = (fila.hora_fin != hora_fin) or (fila.nota != nota) or (
        fila.almuerzo_inicio != almuerzo_inicio
        or (fila.almuerzo_minutos or 0) != (almuerzo_minutos or 0))
    fila.hora_fin = hora_fin
    fila.almuerzo_inicio = almuerzo_inicio
    fila.almuerzo_minutos = almuerzo_minutos
    fila.nota = nota
    fila.tienda_id = tienda_id
    fila.nombre_snapshot = u.nombre
    if fila.estado == EstadoProgramadoEnum.cancelado:
        fila.estado = EstadoProgramadoEnum.borrador
    if cambio and fila.estado == EstadoProgramadoEnum.publicado:
        _avisar_cambio(db, fila, f"Cambió tu turno del {_dia_legible(fecha)}: "
                                 f"ahora es de {hora_inicio} a {hora_fin}"
                                 f"{_texto_almuerzo(almuerzo_inicio, almuerzo_minutos)}.")
    db.commit()
    db.refresh(fila)
    return fila


def borrar_turno(db: Session, turno_id: int) -> bool:
    """Saca un turno del horario. Si ya estaba publicado, la barista se entera:
    dejar de contar con alguien es un cambio tan avisable como agregarlo."""
    fila = db.query(TurnoProgramado).filter(TurnoProgramado.id == turno_id).first()
    if fila is None:
        return False
    if fila.estado == EstadoProgramadoEnum.publicado:
        _avisar_cambio(db, fila,
                       f"Se dio de baja tu turno del {_dia_legible(fila.fecha)} "
                       f"({fila.hora_inicio} a {fila.hora_fin}).")
    db.delete(fila)
    db.commit()
    return True


def publicar_semana(db: Session, tienda_id: int, lunes: date, publicado_por_id: int) -> dict:
    """Publica los borradores de la semana y le avisa a cada barista SU horario.

    Republicar no vuelve a molestar a quien ya estaba publicado y sin cambios:
    solo los borradores pasan a publicado, así que un segundo envío sobre una
    semana intacta no manda nada.
    """
    domingo = lunes + timedelta(days=6)
    borradores = db.query(TurnoProgramado).filter(
        TurnoProgramado.tienda_id == tienda_id,
        TurnoProgramado.fecha >= lunes,
        TurnoProgramado.fecha <= domingo,
        TurnoProgramado.estado == EstadoProgramadoEnum.borrador,
    ).order_by(TurnoProgramado.fecha.asc(), TurnoProgramado.hora_inicio.asc()).all()

    if not borradores:
        return {"publicados": 0, "avisados": 0, "lunes": lunes.isoformat()}

    ahora = datetime.utcnow()
    por_barista: dict[int, list[TurnoProgramado]] = {}
    for tp in borradores:
        tp.estado = EstadoProgramadoEnum.publicado
        tp.publicado_at = ahora
        por_barista.setdefault(tp.usuario_id, []).append(tp)

    for usuario_id, turnos in por_barista.items():
        nombre = turnos[0].nombre_snapshot
        total = sum(duracion_horas(t.hora_inicio, t.hora_fin, t.almuerzo_minutos)
                    for t in turnos)
        detalle = " · ".join(
            f"{DIAS_ES[t.fecha.weekday()]} {t.hora_inicio}-{t.hora_fin}"
            f"{_texto_almuerzo(t.almuerzo_inicio, t.almuerzo_minutos)}"
            for t in turnos)
        mensaje = (f"{nombre}: horario de la semana del {lunes.isoformat()} "
                   f"({_fmt_horas(total)} h) — {detalle}")
        notificaciones.disparar(
            db, tienda_id, "horario_publicado", mensaje, "info",
            referencia_id=usuario_id,
            push_titulo="Tu horario de la semana",
            push_cuerpo=f"Semana del {lunes.isoformat()}: {detalle}",
            usuario_id=usuario_id, push_url="/mi-horario",
        )

    db.commit()
    return {"publicados": len(borradores), "avisados": len(por_barista),
            "lunes": lunes.isoformat()}


def copiar_semana(db: Session, tienda_id: int, lunes_origen: date, lunes_destino: date,
                  creado_por_id: int | None = None) -> int:
    """Copia una semana entera como BORRADOR sobre otra. Nunca pisa lo que ya
    existe en la semana destino: el admin ajusta y después publica."""
    origen = db.query(TurnoProgramado).filter(
        TurnoProgramado.tienda_id == tienda_id,
        TurnoProgramado.fecha >= lunes_origen,
        TurnoProgramado.fecha <= lunes_origen + timedelta(days=6),
        TurnoProgramado.estado != EstadoProgramadoEnum.cancelado,
    ).all()
    delta = lunes_destino - lunes_origen
    creados = 0
    for tp in origen:
        nueva_fecha = tp.fecha + delta
        existe = db.query(TurnoProgramado).filter(
            TurnoProgramado.usuario_id == tp.usuario_id,
            TurnoProgramado.fecha == nueva_fecha,
            TurnoProgramado.hora_inicio == tp.hora_inicio,
        ).first()
        if existe is not None:
            continue
        db.add(TurnoProgramado(
            tienda_id=tienda_id, usuario_id=tp.usuario_id,
            nombre_snapshot=tp.nombre_snapshot, fecha=nueva_fecha,
            hora_inicio=tp.hora_inicio, hora_fin=tp.hora_fin,
            # El almuerzo viaja con el turno: copiar la semana y perder los
            # descansos inflaría las horas de la semana nueva en silencio.
            almuerzo_inicio=tp.almuerzo_inicio, almuerzo_minutos=tp.almuerzo_minutos,
            estado=EstadoProgramadoEnum.borrador, nota=tp.nota,
            creado_por_id=creado_por_id,
        ))
        creados += 1
    if creados:
        db.commit()
    return creados


def _avisar_cambio(db: Session, fila: TurnoProgramado, mensaje: str) -> None:
    notificaciones.disparar(
        db, fila.tienda_id, "horario_cambiado",
        f"{fila.nombre_snapshot}: {mensaje}", "advertencia",
        referencia_id=fila.usuario_id,
        push_titulo="Cambio en tu horario", push_cuerpo=mensaje,
        usuario_id=fila.usuario_id, push_url="/mi-horario",
    )


def _dia_legible(f: date) -> str:
    return f"{DIAS_ES[f.weekday()]} {f.day:02d}/{f.month:02d}"


def _texto_almuerzo(almuerzo_inicio: str | None, almuerzo_minutos: int | None) -> str:
    """Sufijo para los avisos. El almuerzo se le dice a la barista con hora Y
    duración: es tiempo suyo, no de la cafetería, y tiene que poder planearlo."""
    if not almuerzo_inicio or not almuerzo_minutos:
        return ""
    return f" (almuerzo {almuerzo_inicio}, {int(almuerzo_minutos)} min)"


def _fmt_horas(h: float) -> str:
    return f"{h:.0f}" if abs(h - round(h)) < 0.01 else f"{h:.1f}"


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

def _out(tp: TurnoProgramado) -> dict:
    # `horas` son las TRABAJADAS (sin almuerzo): es el número que se paga y el
    # que se compara contra la jornada máxima. `horas_brutas` queda al lado para
    # que la pantalla pueda mostrar las dos y nadie tenga que adivinar si el
    # descanso ya está descontado.
    pausa = pausa_datetimes(tp.fecha, tp.hora_inicio, tp.hora_fin,
                            tp.almuerzo_inicio, tp.almuerzo_minutos)
    return {
        "id": tp.id,
        "usuario_id": tp.usuario_id,
        "nombre": tp.nombre_snapshot,
        "fecha": tp.fecha.isoformat(),
        "hora_inicio": tp.hora_inicio,
        "hora_fin": tp.hora_fin,
        "almuerzo_inicio": tp.almuerzo_inicio,
        "almuerzo_minutos": int(tp.almuerzo_minutos) if tp.almuerzo_minutos else None,
        "almuerzo_fin": pausa[1].strftime("%H:%M") if pausa else None,
        "horas": duracion_horas(tp.hora_inicio, tp.hora_fin, tp.almuerzo_minutos),
        "horas_brutas": duracion_bruta_horas(tp.hora_inicio, tp.hora_fin),
        "cruza_medianoche": _minutos(tp.hora_fin) <= _minutos(tp.hora_inicio),
        "estado": tp.estado.value if hasattr(tp.estado, "value") else tp.estado,
        "nota": tp.nota,
    }


serializar = _out


def baristas_de(db: Session, tienda_id: int) -> list[Usuario]:
    """Personas de la sede que entran al HORARIO (a quién se le arma turno).

    Mismo filtro canónico que `/auth/baristas`: el usuario "Kiosk" es un
    dispositivo, no una persona, y no se le arma horario ni se le paga.

    OJO al alcance: esto responde «a quién le toca turno», que NO es «a quién se
    le paga». Para lo segundo está `personas_de_nomina`, que es más ancha. El
    administrador cobra sueldo y no entra a la grilla de turnos, así que las dos
    listas tienen que existir por separado: unificarlas metería al admin en el
    horario del mostrador, o —como pasaba— lo dejaría fuera de la planilla.
    """
    return db.query(Usuario).filter(
        Usuario.rol == RolEnum.barista,
        Usuario.activo == True,  # noqa: E712
        Usuario.tienda_id == tienda_id,
        ~Usuario.email.like("kiosk@%"),
    ).order_by(Usuario.nombre.asc()).all()


def personas_de_nomina(db: Session, tienda_id: int) -> list[Usuario]:
    """A quién se le PAGA en esta sede: las baristas + quien tenga contrato.

    EL CRITERIO: nadie entra a la nómina por tener rol admin — entra por TENER
    CONTRATO CARGADO. El rol dice qué puede hacer en el sistema; el contrato
    dice que se le paga. Son dos preguntas distintas, y hasta acá el módulo
    respondía la primera para decidir la segunda: el administrador, que es el
    sueldo más grande de la planilla, no aparecía ni en la lista de contratos ni
    en el resumen del mes, y su costo daba $0 en toda proyección.

    Que el criterio sea el contrato y no el rol tiene la otra mitad: un admin
    sin contrato sigue sin aparecer. Nadie se mete solo en la planilla por
    tener permisos; alguien tiene que declarar que se le paga. Por eso esto no
    le cambia el número a ningún negocio que todavía no cargó ese contrato.

    `activa` del contrato NO se mira: la fila existe = la persona está en la
    planilla, igual que una barista con contrato marcado inactivo sigue
    apareciendo. La baja de verdad es `Usuario.activo`.
    """
    return db.query(Usuario).outerjoin(
        ContratoBarista, ContratoBarista.usuario_id == Usuario.id,
    ).filter(
        Usuario.activo == True,  # noqa: E712
        Usuario.tienda_id == tienda_id,
        ~Usuario.email.like("kiosk@%"),
        or_(Usuario.rol == RolEnum.barista, ContratoBarista.id.isnot(None)),
    ).order_by(Usuario.nombre.asc()).all()


def semana(db: Session, tienda_id: int, lunes: date) -> dict:
    """La grilla de la semana: barista × día, con el total de cada una contra la
    jornada máxima VIGENTE esa semana.

    La jornada se resuelve por el LUNES de la semana: el tope del art. 161 CST es
    un límite semanal, así que la semana se mide entera con una sola vara. Si la
    ley cambia a mitad de semana, esa semana usa la tasa de su lunes y la
    siguiente ya usa la nueva — y la pantalla muestra cuál usó.
    """
    lunes = lunes_de(lunes)
    domingo = lunes + timedelta(days=6)
    fila_tasa = tasas_laborales.tasa_vigente(db, lunes)
    jornada = float(fila_tasa.jornada_max_semanal)

    turnos = db.query(TurnoProgramado).filter(
        TurnoProgramado.tienda_id == tienda_id,
        TurnoProgramado.fecha >= lunes,
        TurnoProgramado.fecha <= domingo,
        TurnoProgramado.estado != EstadoProgramadoEnum.cancelado,
    ).order_by(TurnoProgramado.fecha.asc(), TurnoProgramado.hora_inicio.asc()).all()

    por_usuario: dict[int, list[TurnoProgramado]] = {}
    for tp in turnos:
        por_usuario.setdefault(tp.usuario_id, []).append(tp)

    personas = {u.id: u for u in baristas_de(db, tienda_id)}
    # Alguien con turno cargado pero ya movido de sede o inactivo tiene que
    # seguir viéndose: si no, sus horas desaparecen de la grilla sin explicación.
    for uid in por_usuario:
        if uid not in personas:
            u = db.query(Usuario).filter(Usuario.id == uid).first()
            if u is not None:
                personas[uid] = u

    baristas = []
    for uid, u in sorted(personas.items(), key=lambda kv: kv[1].nombre or ""):
        mios = por_usuario.get(uid, [])
        # Contra la jornada máxima se compara el tiempo TRABAJADO: el almuerzo es
        # descanso y no consume el tope semanal del art. 161 CST. Sumar la
        # presencia marcaría en rojo semanas que están dentro de la ley.
        total = sum(duracion_horas(t.hora_inicio, t.hora_fin, t.almuerzo_minutos)
                    for t in mios)
        minutos_almuerzo = sum(int(t.almuerzo_minutos or 0) for t in mios)
        baristas.append({
            "usuario_id": uid,
            "nombre": u.nombre,
            "activa": bool(u.activo) and u.tienda_id == tienda_id,
            "turnos": [_out(t) for t in mios],
            "total_horas": round(total, 2),
            "minutos_almuerzo": minutos_almuerzo,
            "excede_jornada": total > jornada + 1e-9,
            "horas_sobre_jornada": round(max(0.0, total - jornada), 2),
            "publicados": sum(1 for t in mios if t.estado == EstadoProgramadoEnum.publicado),
            "borradores": sum(1 for t in mios if t.estado == EstadoProgramadoEnum.borrador),
        })

    return {
        "tienda_id": tienda_id,
        "lunes": lunes.isoformat(),
        "domingo": domingo.isoformat(),
        "dias": [
            {"fecha": (lunes + timedelta(days=i)).isoformat(), "nombre": DIAS_ES[i]}
            for i in range(7)
        ],
        "jornada_max_semanal": jornada,
        "tasa": tasas_laborales.a_dict(fila_tasa),
        "baristas": baristas,
        "hay_borradores": any(b["borradores"] for b in baristas),
    }


def mi_horario(db: Session, usuario_id: int, desde: date, hasta: date,
               tienda_id: int | None = None) -> list[dict]:
    """Lo que ve la barista: SOLO sus turnos y SOLO los publicados.

    Un borrador es una idea del admin a medio armar; mostrárselo sería prometer
    algo que todavía puede cambiar.

    `tienda_id` acota a una sede. Lo usa el kiosko —cuyo token es compartido—
    para que un id de la otra sede no devuelva sus turnos. El admin consulta sin
    acotar, que es su trabajo.
    """
    q = db.query(TurnoProgramado).filter(
        TurnoProgramado.usuario_id == usuario_id,
        TurnoProgramado.fecha >= desde,
        TurnoProgramado.fecha <= hasta,
        TurnoProgramado.estado == EstadoProgramadoEnum.publicado,
    )
    if tienda_id is not None:
        q = q.filter(TurnoProgramado.tienda_id == tienda_id)
    turnos = q.order_by(TurnoProgramado.fecha.asc(),
                        TurnoProgramado.hora_inicio.asc()).all()
    return [_out(t) for t in turnos]


def turnos_publicados(db: Session, tienda_id: int, desde: date,
                      hasta: date) -> list[TurnoProgramado]:
    """Filas publicadas del rango — la base del PLANEADO del resumen mensual."""
    return db.query(TurnoProgramado).filter(
        TurnoProgramado.tienda_id == tienda_id,
        TurnoProgramado.fecha >= desde,
        TurnoProgramado.fecha <= hasta,
        TurnoProgramado.estado == EstadoProgramadoEnum.publicado,
    ).order_by(TurnoProgramado.fecha.asc(), TurnoProgramado.hora_inicio.asc()).all()
