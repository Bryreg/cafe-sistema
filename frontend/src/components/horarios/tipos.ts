// Tipos compartidos del módulo Horarios & Nómina.
// Espejo de lo que devuelve app/routers/horarios.py: si cambia allá, cambia acá.

export interface TurnoProgramado {
  id: number
  usuario_id: number
  nombre: string
  fecha: string
  hora_inicio: string
  hora_fin: string
  /** Almuerzo: descanso no remunerado. null = el turno no tiene. */
  almuerzo_inicio: string | null
  almuerzo_minutos: number | null
  almuerzo_fin: string | null
  /** Horas TRABAJADAS: ya sin el almuerzo. Es lo que se paga. */
  horas: number
  /** Horas de PRESENCIA: de la entrada a la salida, almuerzo incluido. */
  horas_brutas: number
  cruza_medianoche: boolean
  estado: 'borrador' | 'publicado' | 'cancelado'
  nota: string | null
}

export interface BaristaSemana {
  usuario_id: number
  nombre: string
  activa: boolean
  turnos: TurnoProgramado[]
  /** Horas trabajadas de la semana: el almuerzo ya está descontado. */
  total_horas: number
  minutos_almuerzo: number
  excede_jornada: boolean
  horas_sobre_jornada: number
  publicados: number
  borradores: number
}

export interface Tasa {
  id: number
  vigente_desde: string
  jornada_max_semanal: number
  hora_inicio_nocturna: number
  hora_fin_nocturna: number
  recargo_nocturno: number
  recargo_dominical: number
  recargo_dominical_nocturno: number | null
  recargo_dominical_nocturno_efectivo: number
  extra_diurna: number
  extra_nocturna: number
  divisor_hora_mensual: number
  nota: string | null
  confirmar_contador: boolean
}

/**
 * Una vigencia de parámetros de nómina. Espejo EXACTO de
 * `parametros_nomina.a_dict()`: mismo nombre por campo, sin alias más lindos,
 * para que el número que el dueño ve en la pantalla sea grep-able hasta la
 * función que lo usa.
 *
 * TODOS los porcentajes viajan en FRACCIÓN (0.085 = 8,5%), igual que se
 * guardan. La pantalla los muestra y los recibe como porcentaje y convierte en
 * el borde; el tipo se queda con la unidad del backend a propósito, porque el
 * día que alguien pase una de estas filas a un cálculo no puede quedarle la
 * duda de si el 8,5 es un 8,5% o un 850%.
 */
export interface ParametroNomina {
  id: number
  /** No se puede mover: cada mes se liquida con la vigencia de SU fecha. */
  vigente_desde: string
  /** Pesos decretados cada diciembre, rigen desde el 1 de enero. */
  smmlv: number
  auxilio_transporte: number
  /** Divisor del auxilio por día: 30 fijo, no los días del mes. */
  dias_base_auxilio: number
  /** Tope del derecho al auxilio, EN SMMLV (2 = dos mínimos). */
  tope_auxilio_smmlv: number
  salud_empleado: number
  pension_empleado: number
  /** Desde cuántos SMMLV de IBC arranca el fondo de solidaridad. */
  fsp_desde_smmlv: number
  fsp_tarifa: number
  salud_empleador: number
  pension_empleador: number
  arl: number
  caja_compensacion: number
  sena: number
  icbf: number
  /** Art. 114-1 ET: apaga salud patronal, SENA e ICBF. NUNCA la caja. */
  exonerado_114_1: boolean
  prima: number
  cesantias: number
  intereses_cesantias: number
  vacaciones: number
  nota: string | null
  /** true = todavía sin confirmar con el contador. */
  confirmar_contador: boolean
}

export interface Semana {
  tienda_id: number
  lunes: string
  domingo: string
  dias: { fecha: string; nombre: string }[]
  jornada_max_semanal: number
  tasa: Tasa
  baristas: BaristaSemana[]
  hay_borradores: boolean
}

export interface TipoNovedad {
  tipo: string
  label: string
  remunerada: boolean
  acredita_horas: boolean
  justifica: boolean
  razon: string
}

export interface Novedad {
  id: number
  usuario_id: number
  nombre: string
  tipo: string
  label: string
  fecha_desde: string
  fecha_hasta: string
  dias: number
  remunerada: boolean
  acredita_horas: boolean
  razon: string
  nota: string | null
  soporte_url: string | null
  created_at: string | null
}

export type EstadoDia =
  | 'ok' | 'no_programado' | 'sin_marcacion' | 'cubrio_otra_sede'
  | 'novedad_remunerada' | 'novedad_no_remunerada' | 'libre'

export interface DiaResumen {
  fecha: string
  horas_planeadas: number
  horas_reales: number
  novedad: Novedad | null
  estado: EstadoDia
}

export interface Estimado {
  valor_hora_ordinaria: number
  detalle: Record<string, number>
  total: number
  es_estimado: boolean
}

// ─── Liquidación colombiana ────────────────────────────────────────────────
// Espejo EXACTO de lo que devuelve app/services/liquidacion.py::liquidar().
// Cada campo se tipa con el mismo nombre que allá a propósito: cuando la
// pantalla dice «auxilio», que sea grep-able hasta la función que lo calcula.
// Si acá se le pone un alias más lindo, en seis meses nadie sabe si el número
// de la pantalla es el que el contador está mirando.

/**
 * Auxilio de transporte del período. Se prorratea por DÍA (divisor 30 fijo) y
 * lo suspenden incapacidad, vacaciones, licencia y permiso no remunerado.
 * `razon` viene con texto SOLO cuando no hay derecho (sueldo sobre el tope).
 */
export interface AuxilioTransporte {
  tiene_derecho: boolean
  dias: number
  por_dia: number
  total: number
  razon: string | null
}

/** Lo que se le DESCUENTA a la barista de su propio sueldo. */
export interface Deducciones {
  /** Base de cotización: el devengado con piso de 1 SMMLV. El auxilio NO entra. */
  base_ibc: number
  salud: number
  pension: number
  /** Fondo de Solidaridad Pensional: solo desde 4 SMMLV. En el mínimo da 0. */
  fondo_solidaridad: number
  total: number
}

/** Lo que el NEGOCIO paga por encima del sueldo, sin contar prestaciones. */
export interface AportesEmpleador {
  /** Base de salud, pensión y ARL del empleador: el devengado con piso de 1 SMMLV. */
  base_ibc: number
  /**
   * Base de los PARAFISCALES (SENA, ICBF, caja): lo realmente devengado, SIN el
   * piso del mínimo. Es un campo aparte y no un alias de `base_ibc` porque las
   * dos se separan cuando alguien devenga menos de un mínimo —o sea en medio
   * tiempo— y ahí es donde se cobra de más. La pantalla tiene que poder
   * nombrarlas por separado en vez de hablar de «la base» como si fuera una.
   */
  base_parafiscales: number
  /** Si el negocio está exonerado del art. 114-1 según los parámetros cargados. */
  exonerado: boolean
  salud: number
  pension: number
  arl: number
  /** La caja se paga SIEMPRE: la exoneración del 114-1 nunca la apaga. */
  caja_compensacion: number
  sena: number
  icbf: number
  total: number
  /**
   * Salud patronal (sobre el IBC) + SENA + ICBF (sobre los parafiscales):
   * exactamente lo que se dejaría de pagar si la exoneración aplicara. Cuando
   * `exonerado` es false, este número es plata que HOY está saliendo.
   */
  ahorro_por_exoneracion: number
}

/** Provisión mensual. Prima/cesantías/intereses llevan auxilio; vacaciones no. */
export interface Prestaciones {
  base_con_auxilio: number
  base_sin_auxilio: number
  prima: number
  cesantias: number
  intereses_cesantias: number
  vacaciones: number
  total: number
}

export interface Liquidacion {
  /** Tiempo trabajado con recargos. Es el mismo número que `estimado.total`. */
  devengado: number
  auxilio: AuxilioTransporte
  deducciones: Deducciones
  /** devengado + auxilio − deducciones. Lo que la barista recibe. */
  neto_a_pagar: number
  aportes_empleador: AportesEmpleador
  prestaciones: Prestaciones
  /** devengado + auxilio + aportes + prestaciones. Lo que sale del negocio. */
  costo_empleador: number
  /** costo_empleador ÷ devengado. 0 si no hubo devengado. */
  factor_costo: number
  /**
   * Desde cuándo rigen los parámetros con los que se liquidó.
   *
   * NULL cuando no hay NINGUNA vigencia cargada: ahí el backend devuelve la
   * liquidación vacía (todo en cero y `confirmar_contador` en true) para no
   * romper a quien lee estos campos sin preguntar. Estaba tipado `string` y por
   * eso la pantalla escribía «vigentes desde ,» sobre una liquidación que no se
   * calculó con ningún parámetro: el tipo tapaba el único caso que importaba.
   * Antes de mostrar la vigencia hay que mirar ESTE campo, no `confirmar_contador`.
   */
  vigencia_parametros: string | null
  /** Lo que esta persona devengó EN ESTA SEDE. El resto de las cifras de plata
   *  son de su mes COMPLETO: el auxilio, la base de cotización, los aportes y
   *  las prestaciones son mensuales por trabajador y no se parten por local. */
  devengado_en_esta_sede: number
  /** Trabajó además en otra sede: aparece con las mismas cifras allá. */
  en_varias_sedes: boolean
  confirmar_contador: boolean
  es_estimado: boolean
}

export interface BaristaResumen {
  usuario_id: number
  nombre: string
  activa: boolean
  /** Existe la FILA de contrato. No dice si hay plata adentro: para eso está
   *  `tiene_sueldo`. Confundirlas hace que una barista con contrato en $0 no
   *  aparezca en el aviso de «sin sueldo cargado». */
  tiene_contrato: boolean
  /** El sueldo resuelto de esa persona es > 0. Es el que decide las frases. */
  tiene_sueldo: boolean
  salario_mensual: number
  horas_planeadas: Record<string, number>
  total_planeado: number
  horas_reales: Record<string, number>
  total_real: number
  horas_acreditadas: Record<string, number>
  total_acreditado: number
  diferencia_horas: number
  tramos_sin_salida: number
  novedades: Novedad[]
  dias_sin_marcacion: string[]
  dias: DiaResumen[]
  estimado: Estimado
  liquidacion: Liquidacion
}

export interface Resumen {
  tienda_id: number
  anio: number
  mes: number
  desde: string
  hasta: string
  base_liquidacion: string
  base_liquidacion_detalle: string
  advertencias: string[]
  categorias: { clave: string; label: string }[]
  semanas: {
    lunes: string; domingo: string; jornada_max_semanal: number
    vigente_desde: string; confirmar_contador: boolean
  }[]
  baristas: BaristaResumen[]
  totales: {
    total_planeado: number
    total_real: number
    total_acreditado: number
    estimado: number
    dias_sin_marcacion: number
    tramos_sin_salida: number
    sin_contrato: number
    /** Las que no tienen SUELDO (con o sin fila de contrato). Es el que va en
     *  el aviso: contando solo las filas faltantes, el dueño leía «2 sin
     *  sueldo» cuando eran 3. */
    sin_sueldo: number
    /** Cuántas personas del mes trabajaron también en la otra sede. Su fila
     *  muestra la liquidación ENTERA de su mes (es una sola obligación, mirada
     *  desde dos pantallas), así que dos resúmenes NO se suman. */
    en_varias_sedes: number
    // Los cinco números de la nómina, sumados sobre todas las baristas del mes.
    // `total_devengado` es el mismo valor que `estimado`: convive con él para
    // que la pantalla pueda nombrarlo por lo que es dentro de la cuenta.
    total_devengado: number
    total_auxilio: number
    total_deducciones: number
    total_neto: number
    total_costo_empleador: number
  }
}

export interface Contrato {
  usuario_id: number
  nombre: string
  /** Pesos tecleados a mano. Se IGNORA cuando `salario_en_smmlv` tiene valor. */
  salario_mensual: number
  /**
   * Sueldo expresado en salarios mínimos: 1 = "un mínimo", 1.5 = "uno y medio".
   * null = el sueldo son los pesos fijos de `salario_mensual`.
   * Cuando tiene valor, el sueldo se resuelve contra el mínimo VIGENTE en el
   * mes que se liquida, así que cada enero sube solo. Ese es el punto.
   */
  salario_en_smmlv: number | null
  /**
   * El sueldo que el backend realmente va a usar hoy, ya resuelto:
   * `salario_en_smmlv × SMMLV vigente` si está en mínimos, si no
   * `salario_mensual`. Nunca lo recalcules a partir de los otros dos para
   * mostrarlo como si fuera lo guardado: este es el que manda.
   */
  salario_resuelto: number
  /** SMMLV vigente hoy. `null` cuando no hay ninguna vigencia de parámetros
   *  cargada — el backend manda null, no 0, y tiparlo `number` escondía el
   *  único caso que importa (el mismo bug que tenía `vigencia_parametros`). */
  smmlv_vigente: number | null
  horas_semana_pactadas: number | null
  fecha_ingreso: string | null
  activo: boolean
  nota: string | null
  tiene_contrato: boolean
}

export interface FestivoRow {
  fecha: string
  nombre: string
  es_festivo: boolean
  origen: string
}

// ─── Helpers de fecha en HORA LOCAL ────────────────────────────────────────
// `new Date('2026-08-10')` se parsea como UTC y en Colombia (UTC-5) retrocede
// un día. Todo el módulo arma las fechas a mano para que el 10 sea el 10.

export function aFecha(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d)
}

export function aISO(d: Date): string {
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mm}-${dd}`
}

export function lunesDe(d: Date): Date {
  const copia = new Date(d)
  const dow = (copia.getDay() + 6) % 7 // 0 = lunes
  copia.setDate(copia.getDate() - dow)
  return copia
}

export function sumarDias(d: Date, n: number): Date {
  const copia = new Date(d)
  copia.setDate(copia.getDate() + n)
  return copia
}

export const fmtHoras = (h: number) =>
  Number.isInteger(h) ? `${h} h` : `${h.toFixed(1)} h`

export const fmtPesos = (v: number) =>
  `$${Math.round(v || 0).toLocaleString('es-CO')}`

export const fmtPct = (v: number) => `${Math.round((v || 0) * 100)}%`

export const fmtDia = (iso: string) => {
  const d = aFecha(iso)
  return `${d.getDate()}/${d.getMonth() + 1}`
}

export const MESES = [
  'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
  'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre',
]
