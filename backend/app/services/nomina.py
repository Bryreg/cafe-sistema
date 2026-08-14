"""Resumen mensual por barista: horas por categoría, novedades y planeado vs real.

═══════════════════════════════════════════════════════════════════════════════
DECISIÓN: LA LIQUIDACIÓN SE HACE SOBRE LO **REAL**, NO SOBRE LO PLANEADO.
═══════════════════════════════════════════════════════════════════════════════
El planeado es una intención; lo real es lo que pasó. Pagar sobre el planeado
significaría pagarle a alguien que no vino y no pagarle las horas de más a quien
se quedó cubriendo. En una cafetería donde el horario se mueve por novedades todo
el tiempo, el planeado se desactualiza en cuanto alguien se enferma.

Con dos correcciones, porque "real" a secas sería injusto:

  1. Un día cubierto por una novedad REMUNERADA que acredita tiempo (incapacidad,
     vacaciones, permiso remunerado) no tiene marcación pero sí se paga: se
     acreditan las horas que esa persona tenía PROGRAMADAS ese día. Por eso el
     número que se valoriza se llama ACREDITADO = real + novedades acreditadas.
  2. El planeado nunca se esconde. La pantalla muestra planeado, real y la
     diferencia, siempre — nunca un solo número en silencio.

LÍMITE CONOCIDO Y DECLARADO: `salida_at` se rellena al cerrar la caja para quien
no marcó salida (services/caja.py). O sea las horas reales están sesgadas HACIA
ARRIBA para quien se fue antes del cierre. El resumen lo dice en `advertencias`
en vez de simular una precisión que el dato no tiene.

Todo el módulo trabaja en HORA COLOMBIA: los timestamps de la base son UTC naive
y se convierten con core/tz antes de tocar el cálculo.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.tz import local_col
from app.models.models import (
    CajaTurno, ContratoBarista, NovedadNomina, RolEnum, Tienda, TurnoBarista,
    Usuario,
)
from app.services import festivos as fsvc
from app.services import horarios as hsvc
from app.services import liquidacion as lqsvc
from app.services import parametros_nomina as pnsvc
from app.services import novedades_nomina as nsvc
from app.services import tasas_laborales
from app.services.horas import (
    CATEGORIAS, ETIQUETAS, liquidar_semana_por_tramo, lunes_de, restar_pausas,
    valorizar,
)

ADVERTENCIAS = [
    "Las horas reales salen de la entrada y la salida que se marcan en caja. "
    "Cuando alguien no marca su salida, el cierre de caja la registra por ella con "
    "la hora del cierre: esos días pueden quedar con más horas de las que se "
    "trabajaron de verdad.",
    "El planeado cuenta solo los turnos PUBLICADOS. Los borradores no entran.",
    "El almuerzo es descanso y no se paga: se descuenta de las horas —planeadas y "
    "reales— usando la ventana que está cargada en el horario, porque la caja no "
    "marca la salida a almorzar. Un turno sin almuerzo configurado no descuenta "
    "nada.",
    "Los días que alguien cubrió en la OTRA sede cuentan para su tope semanal (la "
    "jornada máxima es por persona, no por local), pero su almuerzo no se les "
    "descuenta: el horario que se está mirando es el de esta sede. Si alguien "
    "cubre seguido en las dos, sus horas pueden quedar un poco altas.",
    # Estas tres reemplazaron a una sola que decía «no incluye auxilio de
    # transporte, prestaciones, seguridad social ni deducciones». Desde que el
    # resumen expone `liquidacion`, esa frase pasó a ser MENTIRA — y una
    # advertencia que miente es peor que ninguna, porque el dueño deja de
    # leerlas. La regla acá es que la advertencia NOMBRE lo que falta: «es un
    # estimado» a secas no le sirve a nadie para saber qué revisar.
    "Los montos son un ESTIMADO. El DEVENGADO sale del tiempo acreditado "
    "valorizado con los recargos que están cargados en la pantalla de Tasas. El "
    "auxilio de transporte, las deducciones de la barista, los aportes del "
    "empleador y las prestaciones salen del mínimo y de los porcentajes de la "
    "pantalla de Parámetros de nómina: si un porcentaje de ahí está mal, todo "
    "ese bloque está mal.",
    "El auxilio de transporte se prorratea por DÍA con divisor 30 —un mes de "
    "nómina son 30 días, tenga 28 o 31 el calendario— y se SUSPENDE los días de "
    "incapacidad, vacaciones, licencia y permiso no remunerado. A quien trabaja "
    "medio tiempo se le paga el día completo: nunca se prorratea por horas. Y "
    "ojo con el otro lado: los aportes de un medio tiempo NO se parten a la "
    "mitad, porque la base de cotización nunca baja de un salario mínimo entero.",
    "Lo que este cálculo NO tiene y tu contador SÍ va a poner: retención en la "
    "fuente, embargos, libranzas y cualquier descuento autorizado (préstamos, "
    "cooperativa, fondo de empleados), y el redondeo de aportes de PILA "
    "(Decreto 1990/2016), que aproxima cada aporte al múltiplo de 100 de arriba "
    "y mueve el neto unos pesos. Las incapacidades acreditan el TIEMPO al 100%: "
    "acá no se reparte quién paga qué parte (EPS/ARL o el negocio) ni se aplica "
    "el 66,67% de la incapacidad general. Y las prestaciones son la PROVISIÓN "
    "del mes, no un pago: la prima se gira en junio y diciembre, las cesantías "
    "en febrero.",
]


def rango_mes(anio: int, mes: int) -> tuple[date, date]:
    if not 1 <= int(mes) <= 12:
        raise HTTPException(status_code=400, detail="Mes inválido (tiene que ser 1 a 12).")
    ultimo = calendar.monthrange(int(anio), int(mes))[1]
    return date(int(anio), int(mes), 1), date(int(anio), int(mes), ultimo)


def _es_persona(u: Usuario) -> bool:
    """El usuario "Kiosk" es un DISPOSITIVO, no alguien a quien pagarle.
    Mismo filtro canónico que /auth/baristas."""
    return u.rol == RolEnum.barista and not (u.email or "").startswith("kiosk@")


def _cero() -> dict[str, float]:
    return {c: 0.0 for c in CATEGORIAS}


def _sumar(destino: dict[str, float], origen: dict[str, float]) -> None:
    for c in CATEGORIAS:
        destino[c] += origen.get(c, 0.0)


def _redondear(h: dict[str, float]) -> dict[str, float]:
    return {c: round(v, 2) for c, v in h.items()}


def _tramos_reales(db: Session, tienda_id: int, desde: date, hasta: date,
                   pausas: dict[int, list[tuple[datetime, datetime]]] | None = None,
                   ) -> tuple[dict[int, list], dict[int, int], dict[int, Usuario]]:
    """Tramos REALES (entró/salió) de la sede en el rango, en hora Colombia.

    A cada tramo se le sacan las ventanas de almuerzo PLANEADAS que caigan
    adentro (ver `_pausas_planeadas`): la caja no marca el descanso, así que sin
    esto la hora de almuerzo se pagaría como trabajada. Un turno sin almuerzo
    configurado no pierde ni un minuto — el descuento es exactamente la ventana
    que alguien puso en el horario.

    El rango se filtra con margen de un día a cada lado sobre los timestamps UTC
    y después se recorta en local: un turno que empieza a las 20:00 Colombia está
    guardado como 01:00 UTC del día siguiente, así que filtrar el UTC crudo por el
    día calendario se comería turnos de noche.
    """
    ini_utc = datetime.combine(desde, datetime.min.time()) - timedelta(days=1)
    fin_utc = datetime.combine(hasta, datetime.max.time()) + timedelta(days=1)

    # SIN filtro de sede: la jornada máxima del art. 161 CST es un tope por
    # TRABAJADOR y por empleador, no por local. Filtrando la sede acá, quien
    # cubre en las dos nunca junta sus horas y sus extras desaparecen (48 h
    # repartidas 32/16 se liquidaban como dos semanas de jornada normal). Cada
    # tramo viaja etiquetado con si es de ESTA sede: el umbral se calcula sobre
    # todos y el reporte suma solo los propios.
    filas = (
        db.query(TurnoBarista, Usuario, CajaTurno.tienda_id)
        .join(CajaTurno, CajaTurno.id == TurnoBarista.turno_id)
        .join(Usuario, Usuario.id == TurnoBarista.usuario_id)
        .filter(TurnoBarista.created_at >= ini_utc,
                TurnoBarista.created_at <= fin_utc)
        .all()
    )

    tramos: dict[int, list[tuple[datetime, datetime, bool]]] = {}
    sin_salida: dict[int, int] = {}
    personas: dict[int, Usuario] = {}
    otra_sede: dict[int, set[date]] = {}
    for tb, u, sede_id in filas:
        if not _es_persona(u) or tb.created_at is None:
            continue
        entrada = local_col(tb.created_at)
        if not (desde <= entrada.date() <= hasta):
            continue
        propio = sede_id == tienda_id
        if propio:
            # `personas` y `sin_salida` son del REPORTE, que es de esta sede: no
            # se pueblan con gente que solo trabajó en la otra.
            personas[u.id] = u
        else:
            otra_sede.setdefault(u.id, set()).add(entrada.date())
        if tb.salida_at is None:
            # Sin salida no se inventan horas: se cuenta como pendiente y se avisa.
            if propio:
                sin_salida[u.id] = sin_salida.get(u.id, 0) + 1
            continue
        salida = local_col(tb.salida_at)
        if salida <= entrada:
            if propio:
                sin_salida[u.id] = sin_salida.get(u.id, 0) + 1
            continue
        # Si la persona salió y volvió a marcar (dos filas), el almuerzo ya está
        # fuera de los dos tramos y no se superpone con ninguno: `restar_pausas`
        # no descuenta nada y no se paga el descanso dos veces.
        # El 4º campo es el DÍA DE ATRIBUCIÓN: el día en que arrancó la marcación,
        # no el día en que arranca cada pedazo. Sin él, un almuerzo que termina
        # después de medianoche parte el turno y el segundo pedazo se atribuía al
        # día siguiente: caía en otra semana (cambiando qué horas son extra), en
        # otro mes, o directamente en ninguno — una hora que no se pagaba en
        # ningún lado. Es la misma convención que el módulo ya declara: «un turno
        # 18:00→02:00 es del día que arrancó».
        for a, b in restar_pausas(entrada, salida, (pausas or {}).get(u.id, [])):
            tramos.setdefault(u.id, []).append((a, b, propio, entrada.date()))
    return tramos, sin_salida, personas, otra_sede


def _tramos_planeados(db: Session, tienda_id: int, desde: date,
                      hasta: date) -> tuple[dict[int, list], dict[int, dict[date, float]]]:
    """Tramos PLANEADOS (publicados) como datetimes locales, y las horas
    programadas por día — que son las que se acreditan cuando hay novedad.

    Un turno con almuerzo entra como DOS tramos, uno de cada lado del descanso:
    el almuerzo no se trabaja, no se paga y no consume jornada.
    """
    tramos: dict[int, list[tuple[datetime, datetime]]] = {}
    por_dia: dict[int, dict[date, float]] = {}
    for tp in hsvc.turnos_publicados(db, tienda_id, desde, hasta):
        # El tercer campo es la etiqueta de sede que `_liquidar` necesita: el
        # planeado ya viene filtrado por tienda, así que todo es propio.
        for ini, fin in hsvc.tramos_datetimes(tp.fecha, tp.hora_inicio, tp.hora_fin,
                                              tp.almuerzo_inicio, tp.almuerzo_minutos):
            # `tp.fecha` es el día del turno: no hay que inferirlo del tramo.
            tramos.setdefault(tp.usuario_id, []).append((ini, fin, True, tp.fecha))
        dia = por_dia.setdefault(tp.usuario_id, {})
        dia[tp.fecha] = dia.get(tp.fecha, 0.0) + hsvc.duracion_horas(
            tp.hora_inicio, tp.hora_fin, tp.almuerzo_minutos)
    return tramos, por_dia


def _pausas_planeadas(db: Session, tienda_id: int, desde: date,
                      hasta: date) -> dict[int, list[tuple[datetime, datetime]]]:
    """Las ventanas de almuerzo del horario PUBLICADO, por persona.

    Sirven para descontar el descanso también de lo REAL. La marcación de caja no
    registra el almuerzo —se marca al entrar y al salir, no al sentarse a comer—,
    así que sin esto un turno 07:00→15:00 con una hora de almuerzo se liquidaría
    con 8 h reales contra 7 h planeadas y el resumen mostraría una hora extra
    todos los días. Se descuenta la ventana PLANEADA, que es el único dato que el
    sistema tiene sobre el descanso, y se dice en `advertencias`.

    LÍMITE: el almuerzo sale del horario de ESTA sede. Un tramo trabajado en la
    otra entra al umbral semanal sin descontarle su descanso, porque su horario
    no se está consultando acá.
    """
    pausas: dict[int, list[tuple[datetime, datetime]]] = {}
    for tp in hsvc.turnos_publicados(db, tienda_id, desde, hasta):
        p = hsvc.pausa_datetimes(tp.fecha, tp.hora_inicio, tp.hora_fin,
                                 tp.almuerzo_inicio, tp.almuerzo_minutos)
        if p is not None:
            pausas.setdefault(tp.usuario_id, []).append(p)
    return pausas


def _semanas(desde: date, hasta: date) -> list[tuple[date, date]]:
    """Semanas lunes→domingo que cubren el mes. La extra se decide por semana, así
    que hay que liquidar semanas COMPLETAS aunque el mes las corte."""
    out = []
    lunes = lunes_de(desde)
    while lunes <= hasta:
        out.append((lunes, lunes + timedelta(days=6)))
        lunes += timedelta(days=7)
    return out


def _liquidar(tramos: list[tuple[datetime, datetime]], semanas, tasas,
              es_festivo, desde: date, hasta: date,
              solo_propio: bool = True) -> tuple[dict, dict, dict]:
    """Liquida los tramos semana por semana y devuelve
    (total_del_mes, horas_por_dia, estimado_bruto_por_semana).

    Cada semana usa SU tasa (jornada máxima y recargos vigentes ese lunes) y la
    liquidación es de la semana entera; después se suman solo los tramos cuyo día
    de inicio cae dentro del mes pedido. Así el umbral semanal sigue siendo real y
    el corte del mes no inventa ni pierde horas extra.
    """
    total = _cero()
    por_dia: dict[date, dict[str, float]] = {}
    por_semana: list[tuple[date, dict[str, float]]] = []

    for (lunes, domingo), tasa in zip(semanas, tasas):
        # La semana entra ENTERA (todas sus sedes, y sus días de otro mes): el
        # umbral que decide si una hora vale 1,0 o 1,25 es semanal y por persona.
        # La semana se elige por el DÍA DE ATRIBUCIÓN (t[3]), no por el inicio del
        # tramo: los dos pedazos de un turno partido por el almuerzo pertenecen a
        # la misma semana aunque el segundo arranque después de medianoche.
        de_la_semana = [t for t in tramos if lunes <= t[3] <= domingo]
        if not de_la_semana:
            continue
        # `liquidar_semana_por_tramo` ordena por inicio y devuelve un resultado
        # por tramo en ese mismo orden: se ordena igual acá para poder volver a
        # pegarle su etiqueta de sede a cada resultado.
        ordenados = sorted((t for t in de_la_semana if t[1] > t[0]), key=lambda t: t[0])
        pares = [(i, f) for i, f, _p, _d in ordenados]
        acumulado_semana = _cero()
        for (_inicio, horas), (_i, _f, propio, dia) in zip(
                liquidar_semana_por_tramo(pares, tasa, es_festivo), ordenados):
            # El CORTE es solo del reporte: se liquidó la semana completa y de
            # todas las sedes, y recién acá se suma lo que pertenece a este mes y
            # a esta sede. Antes el corte se hacía ANTES de liquidar, así que una
            # semana partida por el borde del mes arrancaba de cero en los dos y
            # las extras desaparecían — 14 h y $26.250 en una sola semana.
            # `solo_propio=False` suma TODAS las sedes: es lo que hace falta
            # para liquidar a la PERSONA. El auxilio de transporte, el piso del
            # IBC, los aportes y las prestaciones son mensuales por trabajador,
            # no por local; calculándolos con el devengado de una sola sede, la
            # misma barista recibía un juego entero en cada pantalla y sumar las
            # dos duplicaba media nómina (medido: +$512.350 de costo inventado y
            # $140.072 de deducciones de más contra su sueldo).
            if not ((propio or not solo_propio) and desde <= dia <= hasta):
                continue
            _sumar(total, horas)
            _sumar(por_dia.setdefault(dia, _cero()), horas)
            _sumar(acumulado_semana, horas)
        por_semana.append((lunes, acumulado_semana))
    return total, por_dia, por_semana


def _dias_con_novedad(novedades, desde: date,
                      hasta: date) -> tuple[dict[date, NovedadNomina], set[date]]:
    """Qué días del rango cubre cada novedad, y cuáles de esos días ACREDITAN
    tiempo (novedad remunerada de un tipo que acredita horas)."""
    cubiertos: dict[date, NovedadNomina] = {}
    acreditantes: set[date] = set()
    for n in novedades:
        tipo = n.tipo.value if hasattr(n.tipo, "value") else n.tipo
        meta = nsvc.TIPOS.get(tipo, {})
        d = max(n.fecha_desde, desde)
        fin = min(n.fecha_hasta, hasta)
        while d <= fin:
            cubiertos.setdefault(d, n)
            if bool(n.remunerada) and meta.get("acredita_horas"):
                acreditantes.add(d)
            d += timedelta(days=1)
    return cubiertos, acreditantes


def _acreditar(tramos_reales: list, tramos_planeados: list,
               acreditantes: set[date]) -> list:
    """ACREDITADO = lo real + lo PROGRAMADO de los días con novedad remunerada y
    sin marcación. Es la base de lo que se paga.

    Vive en su propia función porque la usan dos consumidores —el resumen mensual
    y el costo que entra al P&L— y son el MISMO número: si se calculara en dos
    lados, la pantalla de nómina y el margen podrían empezar a discrepar sin que
    nadie lo note.

    Un día con marcación propia NO acredita además el planeado: sería pagar el
    día dos veces.
    """
    # Por DÍA DE ATRIBUCIÓN, no por el inicio del tramo: con el turno partido por
    # un almuerzo post-medianoche, el segundo pedazo marcaba como «trabajado» el
    # día siguiente — y si ese día tenía una incapacidad remunerada, la novedad
    # dejaba de acreditar. Un día entero de incapacidad se evaporaba (16 h → 7,5).
    dias_con_real = {d for _i, _f, _p, d in tramos_reales}
    return list(tramos_reales) + [
        (i, f, True, d) for i, f, _p, d in tramos_planeados
        if d in acreditantes and d not in dias_con_real
    ]


def resumen_mensual(db: Session, tienda_id: int, anio: int, mes: int) -> dict:
    """El resumen del mes: por barista, horas por categoría, novedades y
    planeado vs real. Es la pantalla que el dueño pidió para fin de mes."""
    desde, hasta = rango_mes(anio, mes)
    semanas = _semanas(desde, hasta)
    tasas = [tasas_laborales.tasa_para(db, lunes) for lunes, _ in semanas]
    filas_tasa = [tasas_laborales.tasa_vigente(db, lunes) for lunes, _ in semanas]

    # Los festivos del rango extendido (las semanas desbordan el mes), resueltos
    # de una sola vez: una query, no una por día.
    borde_ini, borde_fin = semanas[0][0], semanas[-1][1]
    festivas = fsvc.fechas_festivas(db, borde_ini, borde_fin)
    def es_festivo(d: date) -> bool:
        return d in festivas

    # Los tramos se traen sobre las SEMANAS COMPLETAS (borde_ini..borde_fin), no
    # sobre el mes: el umbral semanal necesita ver la semana entera aunque el mes
    # la corte. El recorte al mes lo hace `_liquidar` DESPUÉS de liquidar.
    # Las pausas se resuelven ANTES que lo real: son parte de la definición de
    # "tiempo trabajado", no un ajuste posterior.
    pausas = _pausas_planeadas(db, tienda_id, borde_ini, borde_fin)
    reales, sin_salida, personas_real, otra_sede = _tramos_reales(
        db, tienda_id, borde_ini, borde_fin, pausas)
    planeados, _plan_dia_ext = _tramos_planeados(db, tienda_id, borde_ini, borde_fin)
    # `planeado_por_dia` alimenta la tabla día por día y las ausencias: ese SÍ va
    # acotado al mes, o el resumen mostraría días que no le corresponden.
    _plan_mes, planeado_por_dia = _tramos_planeados(db, tienda_id, desde, hasta)
    novedades = nsvc.listar(db, tienda_id, desde, hasta)

    # Universo de personas: las de la sede + cualquiera con horas, horario o
    # novedad en el mes (alguien que se fue a mitad de mes tiene que aparecer).
    personas: dict[int, Usuario] = {u.id: u for u in hsvc.baristas_de(db, tienda_id)}
    personas.update(personas_real)
    for uid in list(planeados) + [n.usuario_id for n in novedades]:
        if uid not in personas:
            u = db.query(Usuario).filter(Usuario.id == uid).first()
            if u is not None and _es_persona(u):
                personas[uid] = u

    contratos = {
        c.usuario_id: c
        for c in db.query(ContratoBarista).filter(
            ContratoBarista.usuario_id.in_(list(personas) or [0])).all()
    }

    salida = []
    for uid, u in sorted(personas.items(), key=lambda kv: (kv[1].nombre or "").lower()):
        salida.append(_resumen_barista(
            db, uid, u, reales.get(uid, []), planeados.get(uid, []),
            planeado_por_dia.get(uid, {}), [n for n in novedades if n.usuario_id == uid],
            semanas, tasas, es_festivo, desde, hasta,
            sin_salida.get(uid, 0), contratos.get(uid), otra_sede.get(uid, set()),
        ))

    return {
        "tienda_id": tienda_id,
        "anio": int(anio), "mes": int(mes),
        "desde": desde.isoformat(), "hasta": hasta.isoformat(),
        "base_liquidacion": "real",
        "base_liquidacion_detalle": (
            "Se liquida sobre lo REAL (lo que se marcó al entrar y salir), más las "
            "horas programadas de los días cubiertos por una novedad remunerada. El "
            "planeado se muestra al lado para poder compararlo."
        ),
        # Las fijas MÁS la de la exoneración, que depende del estado de HOY y no
        # se puede escribir en una constante. La exoneración del art. 114-1
        # exige dos trabajadores o más, y esa condición se pierde sin que nadie
        # toque el sistema: alcanza con que se vaya gente. El día que pase, se
        # deben salud patronal, SENA e ICBF retroactivamente para ese período,
        # no desde que alguien se dé cuenta — por eso el aviso viaja acá, en la
        # pantalla que el dueño abre todos los meses, y no en la de parámetros,
        # que se mira una vez al año.
        "advertencias": ADVERTENCIAS + [
            a for a in [pnsvc.alerta_exoneracion(db, pnsvc.para(db, desde))] if a
        ],
        "categorias": [{"clave": c, "label": ETIQUETAS[c]} for c in CATEGORIAS],
        "semanas": [
            {"lunes": lunes.isoformat(), "domingo": domingo.isoformat(),
             "jornada_max_semanal": float(fila.jornada_max_semanal),
             "vigente_desde": fila.vigente_desde.isoformat(),
             "confirmar_contador": bool(fila.confirmar_contador)}
            for (lunes, domingo), fila in zip(semanas, filas_tasa)
        ],
        "baristas": salida,
        "totales": _totales(salida),
    }


def _resumen_barista(db, uid, u, tramos_reales, tramos_planeados, planeado_dia,
                     novedades, semanas, tasas, es_festivo, desde, hasta,
                     sin_salida, contrato, dias_otra_sede=frozenset()) -> dict:
    real_total, real_dia, _ = _liquidar(tramos_reales, semanas, tasas, es_festivo, desde, hasta)
    plan_total, plan_dia, _ = _liquidar(tramos_planeados, semanas, tasas, es_festivo, desde, hasta)

    # Días cubiertos por una novedad, y cuáles de ellas acreditan tiempo.
    cubiertos, acreditantes = _dias_con_novedad(novedades, desde, hasta)

    # Se arma como una lista de tramos y se liquida igual que el resto, para que
    # esas horas también pasen por el umbral semanal y por las franjas.
    tramos_acreditados = _acreditar(tramos_reales, tramos_planeados, acreditantes)
    acred_total, acred_dia, acred_semana = _liquidar(
        tramos_acreditados, semanas, tasas, es_festivo, desde, hasta)

    # El sueldo se resuelve POR LA FECHA DEL PERÍODO, no por el número de hoy:
    # un contrato que dice «1 SMMLV» vale el mínimo de ESE mes. Sin esto, subir
    # a la barista al mínimo de 2026 reescribía hacia atrás todo 2025.
    params = pnsvc.para(db, desde)
    salario = pnsvc.salario_del_contrato(contrato, params)
    estimado = _estimar(acred_semana, semanas, tasas, salario)

    # ── El devengado de la PERSONA, sumando sus dos sedes ─────────────────────
    # `estimado` es de ESTA sede y así tiene que quedar: el dueño quiere saber
    # qué le cuesta Vida. Pero el auxilio de transporte, el piso del IBC, los
    # aportes y las prestaciones NO son por local: son mensuales por trabajador.
    # Liquidándolos con el devengado de una sola sede, quien cubre en las dos
    # aparecía cobrando el auxilio ENTERO en cada pantalla y con un juego
    # completo de aportes en cada una. Sumar las dos sedes duplicaba media
    # nómina de esa persona: +$512.350 de costo que no existe y $140.072 de
    # deducciones de más contra su sueldo.
    #
    # Entonces se liquida UNA vez sobre el consolidado, y a cada sede se le
    # atribuye la parte que le corresponde por lo que devengó ahí. Con eso
    # Σ(sedes) vuelve a dar exactamente la nómina real de la persona.
    _tot_persona, _dia_persona, semana_persona = _liquidar(
        tramos_acreditados, semanas, tasas, es_festivo, desde, hasta,
        solo_propio=False)
    estimado_persona = _estimar(semana_persona, semanas, tasas, salario)
    dev_persona = estimado_persona["total"]
    # Con devengado 0 en las dos sedes no hay nada que repartir. Con devengado
    # solo en esta, la parte es 1.0 y todo funciona como antes.
    parte_sede = round(estimado["total"] / dev_persona, 6) if dev_persona > 0 else 0.0

    dias = []
    for d in sorted(set(plan_dia) | set(real_dia) | set(cubiertos) | set(planeado_dia)):
        if not (desde <= d <= hasta):
            continue
        h_plan = round(sum(plan_dia.get(d, {}).values()), 2)
        h_real = round(sum(real_dia.get(d, {}).values()), 2)
        nov = cubiertos.get(d)
        dias.append({
            "fecha": d.isoformat(),
            "horas_planeadas": h_plan,
            "horas_reales": h_real,
            "novedad": nsvc.a_dict(nov) if nov else None,
            "estado": _estado_dia(h_plan, h_real, nov, d in acreditantes,
                                  d in dias_otra_sede),
        })

    # ── De UN número a los CINCO ────────────────────────────────────────────
    # `estimado` es tiempo × recargos: el DEVENGADO. Solo con eso, la pantalla
    # dejaba creer que el sueldo es lo que cuesta la persona, cuando el costo
    # real es ~1,69 veces y el neto que ella recibe es otro número distinto.
    # `liquidacion.liquidar` es puro y ya está probado contra los decretos: acá
    # solo se le arman las tres entradas.
    #
    # Va DESPUÉS del armado de `dias` a propósito: los días que suspenden el
    # auxilio se cuentan de esa misma lista —que ya trae la novedad de cada
    # día— en vez de volver a la base. Dos recorridos distintos de las mismas
    # novedades es la forma más barata de que la pantalla y el CSV empiecen a
    # discrepar sin que nadie lo note.
    #
    # UN DÍA QUE SE TRABAJÓ NO PIERDE EL AUXILIO, tenga la novedad que tenga.
    # Si alguien está de vacaciones del 10 al 14 pero vino a cubrir el 12, ese
    # día se desplazó y gastó el pasaje: descontárselo sería sacarle plata por
    # un dato que la propia lista desmiente. Es el reflejo exacto del criterio
    # de `_acreditar`, que no acredita el planeado de un día con marcación
    # propia para no pagarlo dos veces; acá es al revés y por el mismo motivo:
    # manda lo que PASÓ, no lo que estaba cargado.
    dias_sin_auxilio = sum(
        1 for d in dias
        if d["novedad"]
        and d["horas_reales"] <= 0
        and d["novedad"]["tipo"] in lqsvc.NOVEDADES_SIN_AUXILIO)
    # SIN DEVENGADO NO HAY AUXILIO. `auxilio_del_periodo` le da derecho a
    # cualquier sueldo por debajo del tope, y un sueldo de $0 —barista sin
    # contrato cargado— está por debajo: sin este guardia, quien no tiene
    # contrato aparecía cobrando el auxilio entero y nada más. Es el mismo
    # criterio que ya usa `liquidacion.ibc`: sin jornada no se inventa nada.
    dias_auxilio = (lqsvc.dias_con_auxilio(_dias_de_nomina(desde, hasta, params),
                                           dias_sin_auxilio)
                    if dev_persona > 0 else 0)
    # Sobre el devengado de la PERSONA (todas sus sedes), no sobre el de esta.
    liquidacion = (lqsvc.liquidar(params, dev_persona, salario, dias_auxilio)
                   if params is not None else _liquidacion_vacia())
    liquidacion = {**liquidacion,
                   "parte_de_esta_sede": parte_sede,
                   "en_varias_sedes": parte_sede > 0 and parte_sede < 1}

    # «Sin marcación» ≠ «faltó». El sistema solo sabe que no hay registro; la
    # causa puede ser una novedad que nadie cargó o un olvido de marcar.
    sin_marcacion = [d["fecha"] for d in dias if d["estado"] == "sin_marcacion"]
    total_plan = round(sum(plan_total.values()), 2)
    total_acred = round(sum(acred_total.values()), 2)

    return {
        "usuario_id": uid,
        "nombre": u.nombre,
        "activa": bool(u.activo),
        "tiene_contrato": contrato is not None,
        # DOS COSAS DISTINTAS, y confundirlas es el bug recurrente de este
        # proyecto: `tiene_contrato` es «existe la fila» y `tiene_sueldo` es
        # «hay plata adentro». El PUT de la pestaña Sueldos crea la fila con
        # salario 0, así que una barista puede tener contrato y valer $0 —y
        # entonces su devengado, su auxilio, su neto y su costo dan todos cero
        # sin que nada lo explique. La pantalla tiene que decidir por el MONTO.
        "tiene_sueldo": salario > 0,
        "salario_mensual": salario,
        "horas_planeadas": _redondear(plan_total),
        "total_planeado": total_plan,
        "horas_reales": _redondear(real_total),
        "total_real": round(sum(real_total.values()), 2),
        "horas_acreditadas": _redondear(acred_total),
        "total_acreditado": total_acred,
        "diferencia_horas": round(total_acred - total_plan, 2),
        "tramos_sin_salida": sin_salida,
        "novedades": [nsvc.a_dict(n) for n in novedades],
        "dias_sin_marcacion": sin_marcacion,
        "dias": dias,
        "estimado": estimado,
        "liquidacion": liquidacion,
    }


def _estado_dia(h_plan: float, h_real: float, novedad, acredita: bool,
                cubrio_otra_sede: bool = False) -> str:
    """El estado de un día. El sistema NO sabe si alguien "no vino": sabe si hay
    o no una MARCACIÓN. Por eso el estado se llama `sin_marcacion`, no `ausencia`:
    una calificación disciplinaria derivada de la falta de un registro es una
    acusación, y acá se mide, no se juzga."""
    if h_real > 0:
        return "ok" if h_plan > 0 else "no_programado"
    if cubrio_otra_sede:
        # Marcó en la otra sede: no falta a ningún lado. Sin esto, el día que fue
        # a ayudar aparecía como ausencia en el resumen de su propia sede.
        return "cubrio_otra_sede"
    if novedad is not None:
        return "novedad_remunerada" if acredita else "novedad_no_remunerada"
    if h_plan > 0:
        return "sin_marcacion"
    return "libre"


def _estimar(acred_semana, semanas, tasas, salario: float) -> dict:
    """Valoriza SEMANA POR SEMANA con la tasa de cada una y suma.

    Si la ley cambia a mitad de mes, cada semana se valoriza con los recargos que
    regían esa semana — que es exactamente lo que hace que recalcular un mes viejo
    dé siempre lo mismo.
    """
    por_lunes = {lunes: tasa for (lunes, _), tasa in zip(semanas, tasas)}
    detalle = {c: 0.0 for c in CATEGORIAS}
    total = 0.0
    for lunes, horas in acred_semana:
        v = valorizar(horas, por_lunes[lunes], salario)
        for c in CATEGORIAS:
            detalle[c] += v["detalle"][c]
        total += v["total"]
    tasa_ref = tasas[0] if tasas else None
    divisor = float(tasa_ref.divisor_hora_mensual) if tasa_ref else 0.0
    return {
        "valor_hora_ordinaria": (salario / divisor) if divisor > 0 else 0.0,
        "detalle": {c: round(v, 2) for c, v in detalle.items()},
        "total": round(total, 2),
        "es_estimado": True,
    }


def _dias_de_nomina(desde: date, hasta: date, params) -> int:
    """Días de nómina del período, en MES COMERCIAL de 30 días.

    En Colombia el mes de nómina son 30 días SIEMPRE: febrero paga 30 y agosto
    paga 30. Contar los días del calendario acá rompería el auxilio por los dos
    lados, porque el divisor de `Parametros.auxilio_por_dia` ya es 30 fijo:
    agosto (31 días) pagaría $257.398 y febrero (28) pagaría $232.489, cuando
    el decreto dice $249.095 en los dos. De más en siete meses del año, y de
    MENOS en febrero — que además es ilegal, el auxilio es un piso, no un
    promedio. La regla es numerador y denominador en la misma unidad.

    Un período que NO es un mes entero cuenta sus días de calendario con tope
    en la base. Hoy no existe —`resumen_mensual` siempre pide un mes completo—
    pero la función no puede depender de eso para dar un número correcto.
    """
    base = int(getattr(params, "dias_base_auxilio", 30) or 30) if params else 30
    ultimo = calendar.monthrange(desde.year, desde.month)[1]
    if desde.day == 1 and hasta == date(desde.year, desde.month, ultimo):
        return base
    return min((hasta - desde).days + 1, base)


def _liquidacion_vacia() -> dict:
    """La misma FORMA que devuelve `liquidacion.liquidar`, toda en cero.

    Se usa cuando no hay ni una vigencia de parámetros que resolver — una base
    recién creada cuya siembra falló. La pantalla, el CSV y `_totales` leen
    `liquidacion` sin preguntar: devolver `None` los rompe en el primer acceso
    y devolver medio dict los rompe más adentro y más tarde. Cero, con
    `confirmar_contador` prendido, es la respuesta honesta: no hay con qué
    liquidar y hay que decirlo, no adivinar un mínimo.
    """
    return {
        "devengado": 0.0,
        "auxilio": {"tiene_derecho": False, "dias": 0, "por_dia": 0.0, "total": 0.0,
                    "razon": "No hay parámetros de nómina cargados."},
        "deducciones": {"base_ibc": 0.0, "salud": 0.0, "pension": 0.0,
                        "fondo_solidaridad": 0.0, "total": 0.0},
        "neto_a_pagar": 0.0,
        "aportes_empleador": {"base_ibc": 0.0, "base_parafiscales": 0.0,
                              "exonerado": False, "salud": 0.0,
                              "pension": 0.0, "arl": 0.0, "caja_compensacion": 0.0,
                              "sena": 0.0, "icbf": 0.0, "total": 0.0,
                              "ahorro_por_exoneracion": 0.0},
        "prestaciones": {"base_con_auxilio": 0.0, "base_sin_auxilio": 0.0,
                         "prima": 0.0, "cesantias": 0.0, "intereses_cesantias": 0.0,
                         "vacaciones": 0.0, "total": 0.0},
        "costo_empleador": 0.0,
        "factor_costo": 0.0,
        "vigencia_parametros": None,
        "confirmar_contador": True,
        # Las dos que `_resumen_barista` pisa con los valores reales. Van acá
        # igual para que la forma vacía no se quede corta: el test que compara
        # las dos formas existe justamente porque una clave faltante revienta la
        # pantalla en producción, que es cuando se descubre.
        "parte_de_esta_sede": 0.0,
        "en_varias_sedes": False,
        "es_estimado": True,
    }


def _parte(barista: dict, *ruta: str) -> float:
    """El pedazo de la liquidación de una persona que le toca a ESTA sede.

    `liquidacion` viene del mes completo del trabajador (todas sus sedes),
    porque el auxilio, el piso del IBC, los aportes y las prestaciones son
    mensuales por persona. `parte_de_esta_sede` es la fracción que devengó acá.
    Para quien trabajó en una sola sede vale 1.0.
    """
    valor = barista["liquidacion"]
    for clave in ruta:
        valor = valor[clave]
    return float(valor or 0.0) * float(
        barista["liquidacion"].get("parte_de_esta_sede", 1.0) or 0.0)


def _totales(baristas: list[dict]) -> dict:
    """Los agregados del mes. Los cinco números se SUMAN, nunca se recalculan.

    Recalcular el total sobre el devengado agregado daría OTRO número y sería
    el equivocado: el piso del IBC y el tope del auxilio son por PERSONA. Dos
    baristas de medio tiempo cotizan sobre dos mínimos enteros, no sobre uno
    solo; sumar sus devengados y liquidar eso una vez se comería la mitad de
    los aportes. El total es la suma de las liquidaciones, punto.
    """
    return {
        "total_planeado": round(sum(b["total_planeado"] for b in baristas), 2),
        "total_real": round(sum(b["total_real"] for b in baristas), 2),
        "total_acreditado": round(sum(b["total_acreditado"] for b in baristas), 2),
        "estimado": round(sum(b["estimado"]["total"] for b in baristas), 2),
        # PRORRATEADOS POR SEDE. `liquidacion` es del MES COMPLETO de la
        # persona —el auxilio, el piso del IBC, los aportes y las prestaciones
        # son por trabajador y no por local—, así que sumarla cruda en las dos
        # sedes duplicaba media nómina de quien cubre en ambas. Acá se suma la
        # parte que devengó en ESTA sede, y con eso Σ(sedes) vuelve a dar
        # exactamente la nómina real de esa persona. Para quien trabaja en una
        # sola sede `parte_de_esta_sede` es 1.0 y no cambia nada.
        "total_devengado": round(sum(_parte(b, "devengado") for b in baristas), 2),
        "total_auxilio": round(
            sum(_parte(b, "auxilio", "total") for b in baristas), 2),
        "total_deducciones": round(
            sum(_parte(b, "deducciones", "total") for b in baristas), 2),
        "total_neto": round(sum(_parte(b, "neto_a_pagar") for b in baristas), 2),
        "total_costo_empleador": round(
            sum(_parte(b, "costo_empleador") for b in baristas), 2),
        # Cuántas personas del mes trabajaron además en la otra sede: su fila
        # muestra el mes COMPLETO y los totales solo la parte de acá, así que la
        # pantalla tiene que poder decirlo o los dos números parecen pelearse.
        "en_varias_sedes": sum(
            1 for b in baristas if b["liquidacion"].get("en_varias_sedes")),
        "dias_sin_marcacion": sum(len(b["dias_sin_marcacion"]) for b in baristas),
        "tramos_sin_salida": sum(b["tramos_sin_salida"] for b in baristas),
        "sin_contrato": sum(1 for b in baristas if not b["tiene_contrato"]),
        # El que la pantalla usa para avisar: cuenta a quien NO tiene sueldo,
        # tenga o no fila de contrato. Contando solo las filas faltantes, el
        # dueño leía «2 sin sueldo cargado» cuando eran 3.
        "sin_sueldo": sum(1 for b in baristas if not b["tiene_sueldo"]),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# COSTO LABORAL DEL PERÍODO — lo que consume el P&L
# ═══════════════════════════════════════════════════════════════════════════════

def costo_laboral(db: Session, desde: date, hasta: date,
                  tienda_id: int | None = None,
                  excluir_meses: set[str] | None = None,
                  excluir_mes_sede: set[tuple[str, int]] | None = None) -> dict:
    """Costo laboral ESTIMADO de un rango cualquiera, abierto por mes y por sede.

    Es el MISMO cálculo que muestra el resumen mensual —horas acreditadas,
    liquidadas semana por semana con la tasa vigente de cada una— pero sobre un
    rango arbitrario y con el corte que el P&L necesita. Reusa las mismas
    primitivas (`_tramos_reales`, `_acreditar`, `_liquidar`, `valorizar`), no una
    copia: si las dos pantallas calcularan por su cuenta, la nómina y el margen
    empezarían a discrepar sin que nadie lo note.

    CORTE POR PERÍODO: las semanas se liquidan ENTERAS (el umbral de hora extra
    es semanal) y recién después se suman los días que caen adentro del rango.
    Una hora se atribuye al día en que EMPEZÓ su tramo, igual que en el resumen.
    Cada semana se valoriza con SU tasa, así que recalcular un período viejo da
    siempre el mismo número.

    SIN SALARIO CARGADO NO HAY COSTO. `valorizar` parte del salario del contrato:
    quien no tiene contrato aporta $0 y viaja contado en `sin_contrato`. Por eso
    esto no le cambia el margen a nadie que todavía no haya cargado sueldos —
    aparece cuando el dato existe, no antes.

    La granularidad de valorización es (persona, semana, mes): para las semanas
    que no cruzan el borde del mes —casi todas— es exactamente la misma llamada
    que hace el resumen mensual, y el número coincide al peso.

    Dos formas de excluir, que el P&L usa para los meses que ya tienen la nómina
    cargada a mano: `excluir_meses` saca un mes en TODAS las sedes (es lo que
    corresponde a una obligación corporativa, que cubre a todo el mundo) y
    `excluir_mes_sede` saca el par (mes, sede) de una obligación que pertenece a
    una sede sola. Mezclar las dos en una era el bug: la nómina cargada para una
    sede borraba el costo calculado de las otras.

    Se descartan ADENTRO del cálculo y no después, para que `personas`, `horas` y
    `total` hablen siempre del mismo conjunto de días: un total que no incluye un
    mes y un contador de horas que sí lo incluye es un pie de página que miente.
    """
    if hasta < desde:
        return _costo_vacio()
    excluidos = excluir_meses or set()
    excluidos_sede = excluir_mes_sede or set()

    sedes = ([tienda_id] if tienda_id is not None
             else [t.id for t in db.query(Tienda).order_by(Tienda.id).all()])
    if not sedes:
        return _costo_vacio()

    semanas = _semanas(desde, hasta)
    tasas = [tasas_laborales.tasa_para(db, lunes) for lunes, _ in semanas]
    por_lunes = {lunes: tasa for (lunes, _), tasa in zip(semanas, tasas)}
    borde_ini, borde_fin = semanas[0][0], semanas[-1][1]
    festivas = fsvc.fechas_festivas(db, borde_ini, borde_fin)

    def es_festivo(d: date) -> bool:
        return d in festivas

    por_mes_sede: dict[tuple[str, int], float] = defaultdict(float)
    personas_con_costo: set[int] = set()
    sin_contrato: set[int] = set()
    horas = 0.0

    for sede in sedes:
        # Mismas fuentes y mismo orden que el resumen mensual: pausas de almuerzo
        # primero, porque son parte de la definición de tiempo trabajado.
        pausas = _pausas_planeadas(db, sede, borde_ini, borde_fin)
        reales, _sin_salida, personas_real, _otra = _tramos_reales(
            db, sede, borde_ini, borde_fin, pausas)
        planeados, _plan_dia = _tramos_planeados(db, sede, borde_ini, borde_fin)
        novedades = nsvc.listar(db, sede, desde, hasta)

        personas = dict(personas_real)
        for uid in list(planeados) + [n.usuario_id for n in novedades]:
            if uid not in personas:
                u = db.query(Usuario).filter(Usuario.id == uid).first()
                if u is not None and _es_persona(u):
                    personas[uid] = u
        if not personas:
            continue

        contratos = {
            c.usuario_id: c
            for c in db.query(ContratoBarista).filter(
                ContratoBarista.usuario_id.in_(list(personas) or [0])).all()
        }
        # Parámetros vigentes en el período liquidado: el contrato que dice «1
        # SMMLV» vale el mínimo de ESA fecha, no el de hoy. Se resuelve una vez
        # por período para que ninguna persona quede mezclando dos vigencias.
        params_periodo = pnsvc.para(db, desde)

        for uid in personas:
            _cub, acreditantes = _dias_con_novedad(
                [n for n in novedades if n.usuario_id == uid], desde, hasta)
            tramos = _acreditar(reales.get(uid, []), planeados.get(uid, []), acreditantes)
            _total, por_dia, _por_semana = _liquidar(
                tramos, semanas, tasas, es_festivo, desde, hasta)
            if not por_dia:
                continue

            # (semana, mes): la semana manda porque es la unidad de la tasa y del
            # umbral de extras; el mes, porque es como corta el P&L.
            agrupado: dict[tuple[date, str], dict[str, float]] = {}
            horas_persona = 0.0
            for dia, h in por_dia.items():
                mes = dia.strftime("%Y-%m")
                if mes in excluidos or (mes, sede) in excluidos_sede:
                    continue
                _sumar(agrupado.setdefault((lunes_de(dia), mes), _cero()), h)
                horas_persona += sum(h.values())
            if not agrupado:
                continue

            contrato = contratos.get(uid)
            salario = pnsvc.salario_del_contrato(contrato, params_periodo)
            personas_con_costo.add(uid)
            horas += horas_persona
            if salario <= 0:
                # Tiene horas y no tiene sueldo: su costo es $0 y hay que decirlo,
                # o el margen se lee como si esas horas fueran gratis.
                sin_contrato.add(uid)

            for (lunes, mes), h in agrupado.items():
                por_mes_sede[(mes, sede)] += valorizar(h, por_lunes[lunes], salario)["total"]

    pares = {k: round(v, 2) for k, v in por_mes_sede.items()}
    return {
        "por_mes_sede": pares,
        "total": round(sum(pares.values()), 2),
        "meses": sorted({mes for mes, _sede in pares}),
        "personas": len(personas_con_costo),
        "sin_contrato": len(sin_contrato),
        "horas": round(horas, 2),
        "es_estimado": True,
    }


def _costo_vacio() -> dict:
    return {"por_mes_sede": {}, "total": 0.0, "meses": [], "personas": 0,
            "sin_contrato": 0, "horas": 0.0, "es_estimado": True}


def csv_mensual(db: Session, tienda_id: int, anio: int, mes: int) -> str:
    """Export plano para pasarle al contador. Una fila por barista con sus horas
    por categoría y la liquidación entera del mes.

    ESTA es la superficie que el contador lee de verdad —la pantalla la mira el
    dueño, el CSV lo abre quien arma la PILA—, así que lleva los cinco números y
    además las piezas con las que se auditan: la base de cotización, salud y
    pensión por separado (que es como van en la planilla) y la apertura del
    costo en aportes y prestaciones. Un `costo_empleador` sin sus partes no se
    puede verificar, y lo que no se puede verificar no se usa.

    La columna que antes se llamaba «Estimado ($)» ahora se llama «Devengado
    ($)»: es el mismo número, con el nombre que usa el resto del módulo. Tener
    «estimado» y «devengado» como dos columnas iguales al lado era la forma
    segura de que alguien sumara las dos.
    """
    r = resumen_mensual(db, tienda_id, anio, mes)
    cabecera = (["Barista", "Salario mensual", "Planeado (h)", "Real (h)", "Acreditado (h)"]
                + [ETIQUETAS[c] for c in CATEGORIAS]
                + ["Devengado ($)", "Auxilio transporte ($)", "Días con auxilio",
                   "Base IBC ($)", "Salud empleado ($)", "Pensión empleado ($)",
                   "Deducciones ($)", "Neto a pagar ($)", "Aportes empleador ($)",
                   "Prestaciones ($)", "Costo empleador ($)",
                   "Diferencia (h)", "Días sin marcación ni novedad",
                   "Tramos sin salida", "Novedades"])
    filas = [";".join(cabecera)]
    for b in r["baristas"]:
        novedades = " | ".join(
            f"{n['label']} {n['fecha_desde']}→{n['fecha_hasta']}" for n in b["novedades"])
        lq = b["liquidacion"]
        filas.append(";".join([
            b["nombre"], f"{b['salario_mensual']:.0f}",
            f"{b['total_planeado']:.2f}", f"{b['total_real']:.2f}",
            f"{b['total_acreditado']:.2f}",
            *[f"{b['horas_acreditadas'][c]:.2f}" for c in CATEGORIAS],
            f"{lq['devengado']:.0f}", f"{lq['auxilio']['total']:.0f}",
            str(lq["auxilio"]["dias"]),
            f"{lq['deducciones']['base_ibc']:.0f}",
            f"{lq['deducciones']['salud']:.0f}",
            f"{lq['deducciones']['pension']:.0f}",
            f"{lq['deducciones']['total']:.0f}", f"{lq['neto_a_pagar']:.0f}",
            f"{lq['aportes_empleador']['total']:.0f}",
            f"{lq['prestaciones']['total']:.0f}", f"{lq['costo_empleador']:.0f}",
            f"{b['diferencia_horas']:.2f}",
            str(len(b["dias_sin_marcacion"])), str(b["tramos_sin_salida"]),
            novedades,
        ]))
    filas.append("")
    # El pie viaja con el archivo porque el CSV se reenvía por WhatsApp sin la
    # pantalla que lo explica: quien lo abre no vio ninguna advertencia.
    filas.append("Los montos son un ESTIMADO. El devengado es tiempo acreditado por "
                 "los recargos cargados en el sistema; auxilio, deducciones, aportes "
                 "y prestaciones salen de los parámetros de nómina vigentes. NO "
                 "incluye retención en la fuente, embargos, libranzas ni el redondeo "
                 "de aportes de PILA (Decreto 1990/2016). Las incapacidades acreditan "
                 "el tiempo al 100%: acá no se reparte quién paga qué parte. Las "
                 "prestaciones son la provisión del mes, no el pago. Confirmalo con "
                 "tu contador.")
    return "\n".join(filas)
