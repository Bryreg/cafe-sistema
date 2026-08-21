// ─── El libro del banco, del lado del cliente ────────────────────────────────
//
// Los tipos de acá son la forma EXACTA que devuelve `routers/banco.py` (que a su
// vez la relee de `services/banco.py`). No hay un tipo "de pantalla" distinto del
// tipo "de la API" a propósito: cada vez que la UI se inventa una forma propia
// aparece un lugar donde traducirla, y ese lugar es donde después se cuela un
// saldo calculado dos veces con dos reglas distintas. El saldo del banco tiene
// UNA sola matemática y vive en el backend.

/** Un riel por donde entra y sale la plata (Occidente, Bold). */
export interface CuentaBanco {
  id: number
  nombre: string
  activa: boolean
  nota: string | null
}

/** Un movimiento TECLEADO. El monto va siempre positivo: el signo lo pone `tipo`. */
export interface MovimientoBanco {
  id: number
  fecha: string                     // YYYY-MM-DD
  cuenta_id: number
  cuenta: string                    // nombre ya resuelto por el backend
  tipo: 'entrada' | 'salida'
  monto: number                     // SIEMPRE positivo
  concepto: string
  /** Lo marcó el sistema (GMF, comisión), no el dueño. Hoy nada lo prende. */
  automatico: boolean
  obligacion_id: number | null
  /**
   * La categoría del movimiento, ya resuelta a display por el backend. Los
   * cuatro van con `?` por la ventana de deploy (frontend y backend salen por
   * separado, y en la tablet la PWA la alarga): AUSENTE es «este servidor no
   * clasifica todavía», null es «sin clasificar» — y las dos se dibujan mudas,
   * nunca como una categoría inventada.
   */
  categoria_id?: number | null
  categoria?: string | null
  categoria_clave?: string | null
  categoria_ambito?: string | null
  /** Solo en la respuesta del POST: un aviso del backend (p.ej. una entrada de
   *  Occidente tecleada cuando las consignaciones ya entran solas). */
  advertencia?: string
  nota: string | null
}

/**
 * Una consignación PROYECTADA en el libro: entró al banco ese día, con su
 * comprobante, sin que nadie la tecleara. No es un movimiento del libro (no se
 * borra desde acá — se corrige en Consignaciones) y por eso viaja en su propia
 * lista, no adentro de `movimientos`.
 */
export interface ConsignacionLibro {
  consignacion_id: number
  tienda_id: number
  valor: number
  /** 'pendiente' = la barista la registró y el admin no la confirmó; la plata
   *  YA está en el banco igual (el comprobante es la boleta del depósito). */
  estado: 'pendiente' | 'realizada'
  barista_nombre: string | null
  imagen_url: string | null
}

/**
 * Un pago EN EFECTIVO que se muestra en su día del libro. Es INFORMATIVO:
 * esa plata salió del cajón o de la mano y nunca pasó por una cuenta, así que
 * NO está sumada en `salidas` ni mueve el saldo — sumarla rompería la
 * invariante inicial + entra − sale = final contra el extracto.
 */
export interface PagoEfectivoLibro {
  pago_id: number
  monto: number
  /** El concepto de la obligación o «Proveedor: X». null = el padre ya no
   *  existe y no se le inventa un nombre. */
  detalle: string | null
  nota: string | null
}

/** Una categoría en la serie anual de salidas: los doce meses, ene..dic. */
export interface CategoriaAnual {
  categoria_id: number | null
  clave: string | null
  /** «Sin clasificar» cuando la salida se tecleó sin categoría: un estado
   *  dicho, nunca un cero escondido. */
  nombre: string
  ambito: string | null
  meses: number[]
  total: number
}

export interface PorCategoriaAnual {
  anio: number
  /** Ordenadas por total desc por el backend: «qué me cuesta más este año». */
  categorias: CategoriaAnual[]
}

/**
 * Una fila del libro = un día. La invariante que la pantalla tiene que dejar
 * verificar a ojo, porque es la fórmula de la hoja del dueño:
 *
 *     inicial + total_entradas − total_salidas === final
 *
 * LA CADENA SE DECIDE POR DÍA, NO POR MES. `cadena` contesta la única pregunta
 * que importa para pintar un saldo: ¿se conoce el de ESTE día? Antes del ancla
 * no se sabe cuánta plata había, y el backend manda `inicial`/`final` en null
 * en vez de un número inventado (services/banco.py).
 *
 * Va tipado como UNIÓN DISCRIMINADA a propósito: `dia.cadena` es la única
 * puerta que abre el paso a los saldos, así que el compilador —y no la
 * disciplina de quien edite después— es el que impide pintar un número que el
 * backend declaró desconocido. Es exactamente el bug que se está arreglando:
 * la pantalla decidía por una bandera del MES y afirmaba saldos por fuera de
 * donde la cadena existe.
 */
interface DiaComun {
  fecha: string
  entradas: Record<string, number>   // por nombre de cuenta
  total_entradas: number
  salidas: Record<string, number>
  total_salidas: number
  /**
   * `cadena && final < 0`, calculado por el backend. No lo recalcules acá.
   * Sin cadena viene SIEMPRE en false: un saldo que no se conoce no puede
   * estar en negativo.
   */
  en_rojo: boolean
  movimientos: MovimientoBanco[]
  /**
   * Las consignaciones del día, YA sumadas en `entradas`/`total_entradas` por
   * el backend. Con `?`: un servidor de antes de la proyección no manda la
   * clave, y esa ausencia es «no sé si este día tuvo consignaciones
   * proyectadas», nunca «no tuvo».
   */
  consignaciones?: ConsignacionLibro[]
  /**
   * Los pagos EN EFECTIVO del día, para que la plata que salió del cajón o de
   * la mano se vea donde pasó. NO están en `salidas` ni en `total_salidas` y
   * no mueven el saldo. Con `?` por la ventana de deploy: ausente = «este
   * servidor no los cuenta», y no se dibuja nada.
   */
  pagos_efectivo?: PagoEfectivoLibro[]
}

/** Un día del ancla en adelante: el saldo es exacto. */
export interface DiaConSaldo extends DiaComun {
  cadena: true
  inicial: number
  final: number
}

/** Un día anterior al ancla: lo que se movió es real, el saldo no se sabe. */
export interface DiaSinSaldo extends DiaComun {
  cadena: false
  inicial: null
  final: null
}

export type DiaLibro = DiaConSaldo | DiaSinSaldo

export interface LibroMes {
  desde: string
  hasta: string
  cuentas: CuentaBanco[]
  /** El saldo del extracto que tecleó el dueño: de ahí arranca toda la cadena. */
  ancla: { saldo: number; fecha: string | null }
  /**
   * TODOS los días del rango tienen saldo.
   *
   * NO SIRVE PARA DECIDIR SI SE PINTAN LOS SALDOS. Con el ancla a mitad de mes
   * —que es el caso NORMAL, porque el editor propone hoy y el sistema pide
   * actualizar el extracto cada 7 días— esto es false y aun así del ancla en
   * adelante el saldo es exacto. Quien decide es el `cadena` de cada fila.
   */
  cadena_completa: boolean
  /** Cuántos días del rango sí tienen saldo. 0 = no hay ninguno que pintar. */
  dias_con_saldo: number
  /** Desde qué día se conoce el saldo (ISO). null = ninguno del rango. */
  primer_dia_con_saldo: string | null
  /**
   * Desde cuándo las consignaciones entran SOLAS al libro. null = el régimen
   * no se activó (todo tecleado, como siempre). AUSENTE (`undefined`) = el
   * servidor no conoce el régimen: no se ofrece activarlo, porque el botón
   * llamaría a un endpoint que no existe.
   */
  consignaciones_desde?: string | null
  /** Filas legacy sin fecha: NO están en ningún día del libro y se dicen. */
  consignaciones_sin_fecha?: { n: number; total: number }
  /** La tasa del GMF (4×1000) vigente, para SUGERIR la fila al cargar una
   *  salida. null/ausente = no se pudo leer: la sugerencia se apaga, no se
   *  inventa una tasa. */
  tasa_gmf?: number | null
  dias: DiaLibro[]
  totales: {
    entradas: number
    salidas: number
    /** null cuando el ÚLTIMO día del rango no tiene saldo: no se sabe. */
    final: number | null
    dias_en_rojo: number
    /** El cierre más bajo ENTRE LOS DÍAS CON SALDO. null si no hay ninguno. */
    dia_mas_bajo: number | null
    /** El día de ese cierre, dicho por el backend: no se busca por el monto. */
    fecha_dia_mas_bajo: string | null
  }
}

export interface MesSerie {
  mes: number                        // 1..12
  entradas: number
  salidas: number
  neto: number
  /** null = la cadena no llega hasta ese mes. NO es un cierre de cero. */
  cierre: number | null
}

export interface SerieAnual {
  anio: number
  meses: MesSerie[]
}

/** Lo que contesta `PUT /banco/ancla`, releído de la base (no lo que se mandó). */
export interface AnclaGuardada {
  saldo: number
  fecha: string | null
  dias_desde: number | null
  desactualizado: boolean
}

// ─── Fechas ───────────────────────────────────────────────────────────────────
// Todo en ISO 'YYYY-MM-DD', que es lo que devuelve el backend: comparar strings
// ISO es comparar fechas, y así ningún Date con hora corre un día por el huso.

export const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
  'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']

export const MESES_CORTOS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
  'jul', 'ago', 'sep', 'oct', 'nov', 'dic']

// Fijos y no `toLocaleDateString('es-CO', { weekday: 'short' })`: el navegador de
// la tablet no siempre trae el locale y devuelve "Fri" en media pantalla.
const DIAS_CORTOS = ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb']

/** Día de la semana ('lun'…'dom') de una fecha ISO, sin pasar por UTC. */
export const diaSemana = (iso: string) => DIAS_CORTOS[new Date(iso + 'T00:00:00').getDay()]

/** Sábado o domingo: se tiñen para que el ojo agarre las semanas de un golpe. */
export const esFinde = (iso: string) => {
  const d = new Date(iso + 'T00:00:00').getDay()
  return d === 0 || d === 6
}

export const fechaLarga = (iso: string) =>
  new Date(iso + 'T00:00:00').toLocaleDateString('es-CO',
    { weekday: 'long', day: 'numeric', month: 'long' })

export const fechaCorta = (iso: string) =>
  new Date(iso + 'T00:00:00').toLocaleDateString('es-CO')

/** Días completos entre dos fechas ISO. Aritmética, no una afirmación. */
export const diasEntre = (desde: string, hasta: string) =>
  Math.round((new Date(hasta + 'T00:00:00').getTime()
    - new Date(desde + 'T00:00:00').getTime()) / 86_400_000)

// ─── Plata ────────────────────────────────────────────────────────────────────

/**
 * Plata en una celda de la grilla: solo el orden de magnitud.
 *
 * El monto exacto vive en el detalle del día, que está a un click. Una tabla de
 * 31 días con cuatro columnas de nueve dígitos cada una no se lee "de un golpe",
 * y leer el mes de un golpe es exactamente lo que esta pantalla tiene que lograr.
 */
export const compacto = (v: number) => {
  const a = Math.abs(v)
  const signo = v < 0 ? '−' : ''
  if (a >= 1_000_000) return `${signo}${(a / 1_000_000).toFixed(1).replace('.', ',')}M`
  if (a >= 1_000) return `${signo}${Math.round(a / 1_000)}k`
  return `${signo}${Math.round(a)}`
}

/**
 * Plata exacta, con el signo ADELANTE del peso: −$250.000, no $-250.000.
 *
 * El `fmt` compartido pega el signo entre el símbolo y el número porque en el
 * resto del sistema los montos no se van a negativo. Acá sí: un saldo en rojo es
 * el número que esta pantalla existe para mostrar, y «$-250.000» se lee mal justo
 * en el renglón que más importa. Mismo criterio que `compacto`, que ya usa «−».
 */
export const plata = (v: number) =>
  (v < 0 ? '−' : '') + '$' + Math.abs(Math.round(v || 0)).toLocaleString('es-CO')

// El día que cerró más bajo del mes NO se busca acá: viene en
// `totales.fecha_dia_mas_bajo`. Antes se buscaba la primera fila cuyo `final`
// fuera igual al mínimo, y esa búsqueda dejó de tener sentido cuando los días
// sin cadena pasaron a traer `final: null` — es la misma familia de error que
// este módulo viene arrastrando: identificar un dato por su FORMA (un monto que
// coincide) en vez de preguntarle al backend cuál es.

/**
 * `detalleDeError` se mudó a `src/api/errores.ts`: la necesita `useDato`, y la
 * capa de datos no puede importar de `components/`. Se re-exporta acá para que
 * los diez archivos que ya la importan desde este módulo sigan igual.
 */
export { detalleDeError } from '../../api/errores'
