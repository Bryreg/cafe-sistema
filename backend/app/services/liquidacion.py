"""De horas trabajadas a los CINCO números de una nómina colombiana.

Hasta acá el sistema tenía UNO solo —`estimado`, que es tiempo × recargos— y lo
decía en pantalla. Pero ese número no es ninguna de las cosas que el dueño
necesita saber, y confundirlas cuesta plata de verdad:

    1. DEVENGADO ......... el sueldo por el tiempo trabajado, con recargos.
    2. AUXILIO ........... de transporte. No es salario, pero se paga.
    3. DEDUCCIONES ....... salud 4% + pensión 4%, que salen del sueldo de ella.
    4. NETO .............. lo que la barista recibe:  1 + 2 − 3.
    5. COSTO EMPLEADOR ... lo que sale del negocio: 1 + 2 + aportes + prestaciones.
       Es ~1,55 a 1,69 veces el sueldo. NO es el neto, ni parecido.

═══════════════════════════════════════════════════════════════════════════════
LAS TRES BASES. Acá está el error clásico y por eso se separan explícitamente.
═══════════════════════════════════════════════════════════════════════════════
El auxilio de transporte NO es salario (art. 128 CST): reembolsa un gasto, no
remunera el servicio. Pero el art. 7 de la Ley 1ª de 1963 lo mete POR EXCEPCIÓN
en la base de prima, cesantías e intereses. Entonces conviven tres bases:

  base_ibc      = devengado             → aportes, deducciones, parafiscales.
                                          El auxilio NO entra. El IBC sí
                                          incluye recargos y extras.
  base_prestac  = devengado + auxilio   → prima, cesantías, intereses.
  base_vacac    = devengado             → vacaciones (el auxilio NO entra).

Usar una sola base para todo se equivoca en los dos sentidos a la vez: cobra
aportes sobre plata que no cotiza y liquida prima sobre una base más chica de
la que manda la ley.

═══════════════════════════════════════════════════════════════════════════════
EL PISO DEL IBC ES EL GOTCHA MÁS CARO DE ESTA CAFETERÍA.
═══════════════════════════════════════════════════════════════════════════════
El IBC de un trabajador dependiente NO puede ser menor a 1 SMMLV (Ley 100 art.
18 para pensión; art. 204 y Decreto 780/2016 para salud). O sea que una barista
de MEDIO TIEMPO que devenga $875.000 igual cotiza sobre $1.750.905: los aportes
NO se parten a la mitad con la jornada. Quien planee medio tiempo pensando que
el costo se divide por dos se lleva una sorpresa de varios cientos de miles.

Los parafiscales (SENA/ICBF/caja) sí se liquidan sobre lo realmente devengado.

Todo lo de acá es PURO: recibe números y parámetros, no toca la base. Los
porcentajes viven en `parametros_nomina` con vigencia — ni uno está quemado.
"""
from app.services.parametros_nomina import Parametros

# Las novedades que SUSPENDEN el auxilio de transporte: sin desplazamiento no
# hay pasaje que reembolsar. Se nombran por la clave de `novedades_nomina.TIPOS`.
NOVEDADES_SIN_AUXILIO = frozenset({
    "incapacidad", "vacaciones", "permiso_no_remunerado", "licencia_no_remunerada",
    "licencia_maternidad", "suspension",
})


def dias_con_auxilio(dias_del_periodo: int, dias_sin_derecho: int = 0) -> int:
    """Días que generan auxilio: los del período menos los que lo suspenden.

    Los descansos normales (el domingo libre, el festivo de la programación)
    NO se descuentan: entran dentro de los 30 días de la base. Lo que sí
    descuenta es incapacidad, vacaciones, licencia y permiso no remunerado.
    """
    return max(0, int(dias_del_periodo or 0) - int(dias_sin_derecho or 0))


def auxilio_del_periodo(params: Parametros, salario_mensual: float,
                        dias: int) -> dict:
    """Auxilio de transporte proporcional a los días con derecho.

    DOS reglas que sorprenden y que están acá a propósito:

    - Se prorratea por DÍA con divisor 30 fijo, no por los días calendario del
      mes: un febrero no paga el día más caro que un enero.
    - Al de MEDIO TIEMPO se le paga el día COMPLETO, sin prorratear por horas
      (Concepto Mintrabajo 257 de 2020): quien va medio día gasta el mismo
      pasaje que quien va la jornada entera. Por eso esta función mira DÍAS y
      nunca horas — pasarle horas sería el bug.
    """
    tope = params.tope_auxilio_pesos
    tiene_derecho = tope > 0 and float(salario_mensual or 0.0) <= tope
    if not tiene_derecho:
        return {"tiene_derecho": False, "dias": 0, "por_dia": 0.0, "total": 0.0,
                "razon": f"El sueldo supera el tope de {params.tope_auxilio_smmlv:g} SMMLV"}
    d = max(0, int(dias or 0))
    return {
        "tiene_derecho": True,
        "dias": d,
        "por_dia": round(params.auxilio_por_dia, 2),
        "total": round(params.auxilio_por_dia * d, 2),
        "razon": None,
    }


def ibc(params: Parametros, devengado: float) -> float:
    """Base de cotización: lo devengado, pero nunca por debajo de 1 SMMLV.

    El piso aplica a quien TRABAJA en el período. Un devengado de 0 —nadie
    trabajó— no cotiza nada: poner el piso ahí inventaría un aporte por una
    persona que no tuvo jornada.
    """
    d = float(devengado or 0.0)
    if d <= 0:
        return 0.0
    return max(d, float(params.smmlv or 0.0))


def deducciones(params: Parametros, devengado: float) -> dict:
    """Lo que se le DESCUENTA a la barista de su sueldo.

    Sobre el IBC, que incluye recargos y extras pero no el auxilio. El Fondo de
    Solidaridad Pensional solo arranca en 4 SMMLV, así que a un sueldo mínimo
    no le toca — se calcula igual para que el día que haya un sueldo alto el
    sistema no lo ignore en silencio.
    """
    base = ibc(params, devengado)
    salud = round(base * params.salud_empleado, 2)
    pension = round(base * params.pension_empleado, 2)
    umbral_fsp = float(params.smmlv or 0.0) * float(params.fsp_desde_smmlv or 0.0)
    aplica_fsp = umbral_fsp > 0 and base >= umbral_fsp
    fsp = round(base * params.fsp_tarifa, 2) if aplica_fsp else 0.0
    return {
        "base_ibc": round(base, 2),
        "salud": salud,
        "pension": pension,
        "fondo_solidaridad": fsp,
        "total": round(salud + pension + fsp, 2),
    }


def aportes_empleador(params: Parametros, devengado: float) -> dict:
    """Lo que el negocio paga POR ENCIMA del sueldo, sin las prestaciones.

    La exoneración del art. 114-1 apaga salud patronal, SENA e ICBF. NO apaga
    la caja de compensación (4%), que se paga siempre y en todos los
    escenarios: es el error que más se ve cuando alguien dice «estoy exonerado
    de parafiscales».
    """
    base = ibc(params, devengado)
    exo = bool(params.exonerado_114_1)
    salud = 0.0 if exo else round(base * params.salud_empleador, 2)
    sena = 0.0 if exo else round(base * params.sena, 2)
    icbf = 0.0 if exo else round(base * params.icbf, 2)
    pension = round(base * params.pension_empleador, 2)
    arl = round(base * params.arl, 2)
    caja = round(base * params.caja_compensacion, 2)
    return {
        "base_ibc": round(base, 2),
        "exonerado": exo,
        "salud": salud,
        "pension": pension,
        "arl": arl,
        "caja_compensacion": caja,
        "sena": sena,
        "icbf": icbf,
        "total": round(salud + pension + arl + caja + sena + icbf, 2),
        # Cuánto costaría el error de tenerlo mal puesto. Va al payload para que
        # la pantalla pueda decirlo con un número en vez de con un "confirmá".
        "ahorro_por_exoneracion": round(
            base * (params.salud_empleador + params.sena + params.icbf), 2),
    }


def prestaciones(params: Parametros, devengado: float, auxilio: float) -> dict:
    """Provisión mensual de prima, cesantías, intereses y vacaciones.

    DOS BASES DISTINTAS, y no es un detalle: prima, cesantías e intereses van
    sobre devengado + auxilio (Ley 1ª de 1963 art. 7); las vacaciones SOLO
    sobre el devengado, porque son descanso remunerado y el auxilio reembolsa
    un desplazamiento que durante las vacaciones no ocurre.
    """
    con_aux = float(devengado or 0.0) + float(auxilio or 0.0)
    solo_sueldo = float(devengado or 0.0)
    prima = round(con_aux * params.prima, 2)
    cesantias = round(con_aux * params.cesantias, 2)
    intereses = round(con_aux * params.intereses_cesantias, 2)
    vacaciones = round(solo_sueldo * params.vacaciones, 2)
    return {
        "base_con_auxilio": round(con_aux, 2),
        "base_sin_auxilio": round(solo_sueldo, 2),
        "prima": prima,
        "cesantias": cesantias,
        "intereses_cesantias": intereses,
        "vacaciones": vacaciones,
        "total": round(prima + cesantias + intereses + vacaciones, 2),
    }


def liquidar(params: Parametros, devengado: float, salario_mensual: float,
             dias_con_derecho_a_auxilio: int) -> dict:
    """Los cinco números, calculados una sola vez y nombrados sin ambigüedad.

    `devengado` es lo que ya calcula `horas.valorizar`: tiempo trabajado con
    sus recargos. `salario_mensual` se usa SOLO para decidir el derecho al
    auxilio (el tope es sobre el sueldo pactado, no sobre lo devengado del mes).

    Nada de esto reemplaza al contador: no hay retención en la fuente, ni
    embargos, ni libranzas, ni el redondeo de PILA (Decreto 1990/2016, que
    aproxima los aportes al múltiplo de 100 superior y mueve el neto unos
    pesos). Es un piso verificable, y la pantalla lo dice.
    """
    dev = round(float(devengado or 0.0), 2)
    aux = auxilio_del_periodo(params, salario_mensual, dias_con_derecho_a_auxilio)
    ded = deducciones(params, dev)
    ap = aportes_empleador(params, dev)
    pr = prestaciones(params, dev, aux["total"])

    neto = round(dev + aux["total"] - ded["total"], 2)
    costo = round(dev + aux["total"] + ap["total"] + pr["total"], 2)
    return {
        "devengado": dev,
        "auxilio": aux,
        "deducciones": ded,
        "neto_a_pagar": neto,
        "aportes_empleador": ap,
        "prestaciones": pr,
        "costo_empleador": costo,
        # Cuántas veces el devengado termina costando el empleado. Es el número
        # que hace visible de un vistazo que el sueldo no es lo que se paga.
        "factor_costo": round(costo / dev, 4) if dev > 0 else 0.0,
        "vigencia_parametros": params.vigente_desde.isoformat(),
        "confirmar_contador": params.confirmar_contador,
        "es_estimado": True,
    }
