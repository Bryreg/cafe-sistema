// ─── La cascada del efectivo, del lado del cliente ───────────────────────────
//
// Un día que cierra con saldo EN CONTRA —de la registradora salió más efectivo
// del que entró— no abre un hueco nuevo: esa plata salió del cajón, o sea de la
// venta de un día anterior que todavía no viajó al banco. El backend ya lo
// resuelve con una cascada FIFO (`services/consignaciones.py`,
// `_saldos_consignacion`): el déficit se come el saldo de los turnos más viejos
// primero, y de ahí sale a quién se le cobra la plata de verdad.
//
// EL BUG QUE ESTE MÓDULO CIERRA: esa cascada alimentaba la imputación
// (`recoger`, `get_pendiente`, la apertura de caja) pero NO la pantalla, porque
// `get_resumen_admin` se calculaba su propio esperado sin ella. El dueño veía
// $400.000 en el domingo y el sistema le cobraba $222.300. Dos cuentas sobre la
// misma plata, y ninguna de las dos sabía de la otra.
//
// De ahí la regla de este archivo: **`saldoPendiente` viene del servidor y acá
// no se recalcula nunca**. Lo único que hace el cliente es agrupar los turnos en
// días de calendario y rotular las fechas del otro lado del cruce. Si mañana
// alguien tiene la tentación de derivar el saldo de `esperado − consignado`,
// está reabriendo exactamente el bug: esa resta es la cuenta vieja.

// ─── La forma que manda el backend ───────────────────────────────────────────

/**
 * Una punta de la cascada: el turno del OTRO lado y cuánta plata cruzó.
 *
 * Viene `fecha_cierre` y no la de apertura porque es la que ordena la cascada
 * en el backend. Para rotular preferimos la apertura del turno cuando lo
 * tenemos a la vista — ver `RotularCruce`, más abajo.
 */
export interface CruceCascada {
  turno_id: number
  fecha_cierre: string | null
  monto: number
}

/**
 * Los campos que `get_resumen_admin` agrega por turno. Van OPCIONALES a
 * propósito: son nuevos, y un frontend cacheado contra un backend que todavía
 * no los manda tiene que poder decir «no lo sé» en vez de leer un `undefined`
 * como si fuera cero. El `0` fabricado sería un «al día ✓» sobre plata que
 * falta, que es el peor error posible en esta pantalla.
 */
export interface CamposCascada {
  cubrio_faltante?: number
  cubrio?: CruceCascada[]
  cubierto_por?: CruceCascada[]
  faltante_sin_cubrir?: number
  saldo_pendiente?: number
}

// ─── La forma que consume la pantalla ────────────────────────────────────────

/** Cómo nombrar el día del otro lado del cruce, ya resuelto por la pantalla. */
export interface RotuloCruce {
  /** El día, rotulado igual que las tarjetas de la lista. */
  dia: string
  /** No está en el periodo filtrado: por eso no lo va a encontrar abajo. */
  fuera: boolean
}

export type RotularCruce = (ref: CruceCascada) => RotuloCruce

/** Una línea de la cuenta: «cubrió el faltante del lunes 17 · $177.700». */
export interface LineaCascada extends RotuloCruce {
  monto: number
}

/**
 * La cascada de UN día de calendario (uno o más turnos), lista para dibujar.
 *
 * Va tipada como UNIÓN DISCRIMINADA por la misma razón que `DiaLibro` en
 * `components/plata/banco.ts`: `legible` es la única puerta que abre el paso a
 * `saldoPendiente`, así que el compilador —y no la disciplina de quien edite
 * dentro de seis meses— impide pintar un número que el backend no mandó.
 */
export type Cascada =
  | { legible: false }
  | {
      legible: true
      /** Le tapó el hueco a otro día. Sale de este día, así que RESTA. */
      cubrio: LineaCascada[]
      cubrioTotal: number
      /** Otro día le tapó el suyo. Entra de afuera, así que no lo tiene que pagar. */
      cubiertoPor: LineaCascada[]
      cubiertoPorTotal: number
      /**
       * Faltó plata y ningún día anterior tenía saldo para taparla. El backend
       * la ignora para el saldo (ver el comentario «sobrepago histórico» en
       * `_saldos_consignacion`) y esa decisión no se toca acá — pero se muestra:
       * que se ignore en la cuenta es defendible, que no se pueda ver, no.
       */
      faltanteSinCubrir: number
      /** EL número: lo que de verdad falta consignar. Del backend, sin tocar. */
      saldoPendiente: number
      /** ¿Este día lo tocó la cascada? Si no, la fila se dibuja como siempre. */
      hubo: boolean
    }

/** Lo que este módulo necesita leer de un turno del resumen. */
interface TurnoConCascada extends CamposCascada {
  turno_id: number
}

// ─── Lectura ─────────────────────────────────────────────────────────────────

const esNumero = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

/**
 * Un cruce mal formado deja ILEGIBLE al turno entero en vez de saltearse la
 * línea: si dibujáramos tres de cuatro líneas, la suma de lo que el dueño ve
 * dejaría de dar el total que también ve, y volveríamos a tener dos cuentas —
 * esta vez dentro de la misma tarjeta.
 */
function leerCruces(v: unknown): CruceCascada[] | null {
  if (!Array.isArray(v)) return null
  const out: CruceCascada[] = []
  for (const r of v) {
    if (!r || typeof r !== 'object') return null
    const { turno_id, fecha_cierre, monto } = r as Partial<CruceCascada>
    if (!esNumero(turno_id) || !esNumero(monto)) return null
    out.push({
      turno_id,
      fecha_cierre: typeof fecha_cierre === 'string' ? fecha_cierre : null,
      monto,
    })
  }
  return out
}

/** Junta en una sola línea los cruces que caen en el mismo día rotulado. */
function agrupar(lineas: LineaCascada[]): LineaCascada[] {
  const map = new Map<string, LineaCascada>()
  for (const l of lineas) {
    const previa = map.get(l.dia)
    if (previa) previa.monto += l.monto
    else map.set(l.dia, { ...l })
  }
  return [...map.values()].sort((a, b) => b.monto - a.monto)
}

/**
 * La cascada de un día = la suma de la de sus turnos.
 *
 * SE DESCARTAN LOS CRUCES ENTRE TURNOS DEL MISMO DÍA. La cascada corre por
 * turno, así que el turno de la tarde puede haberle comido el saldo al de la
 * mañana; en una tarjeta que ya los muestra sumados, «cubrió el faltante del
 * martes 18» impreso adentro de la tarjeta del martes 18 no explica nada. Los
 * montos se restan de los dos totales a la vez, así que la aritmética de la
 * tarjeta queda igual: lo que entra por un turno sale por el otro.
 */
export function cascadaDelDia(turnos: TurnoConCascada[], rotular: RotularCruce): Cascada {
  const propios = new Set(turnos.map(t => t.turno_id))
  let cubrioTotal = 0
  let cubiertoPorTotal = 0
  let faltanteSinCubrir = 0
  let saldoPendiente = 0
  const cubrio: LineaCascada[] = []
  const cubiertoPor: LineaCascada[] = []

  for (const t of turnos) {
    const cruceCubrio = leerCruces(t.cubrio)
    const cruceCubierto = leerCruces(t.cubierto_por)
    if (
      !esNumero(t.cubrio_faltante) || !esNumero(t.faltante_sin_cubrir) ||
      !esNumero(t.saldo_pendiente) || !cruceCubrio || !cruceCubierto
    ) {
      return { legible: false }
    }

    cubrioTotal += t.cubrio_faltante
    faltanteSinCubrir += t.faltante_sin_cubrir
    saldoPendiente += t.saldo_pendiente

    for (const ref of cruceCubrio) {
      if (propios.has(ref.turno_id)) { cubrioTotal -= ref.monto; continue }
      cubrio.push({ ...rotular(ref), monto: ref.monto })
    }
    for (const ref of cruceCubierto) {
      if (propios.has(ref.turno_id)) continue
      cubiertoPorTotal += ref.monto
      cubiertoPor.push({ ...rotular(ref), monto: ref.monto })
    }
  }

  const lineasCubrio = agrupar(cubrio)
  const lineasCubierto = agrupar(cubiertoPor)
  return {
    legible: true,
    cubrio: lineasCubrio,
    cubrioTotal,
    cubiertoPor: lineasCubierto,
    cubiertoPorTotal,
    faltanteSinCubrir,
    saldoPendiente,
    // Un día que la cascada no tocó tiene que dibujarse EXACTAMENTE como antes:
    // la excepción no puede volver ruidoso al día normal, que son casi todos.
    hubo: lineasCubrio.length > 0 || lineasCubierto.length > 0 || faltanteSinCubrir > 0.5,
  }
}

// ─── Las dos cuentas que la pantalla necesita ────────────────────────────────

/**
 * Lo que de verdad falta consignar de este día.
 *
 * Sin cascada legible cae a la resta cruda —la misma que mostraba la pantalla
 * antes de esta entrega— en vez de fabricar un 0: un backend viejo hace que la
 * pantalla se equivoque como se equivocaba ayer, no que invente un «al día».
 */
export function faltaConsignar(c: Cascada, esperado: number, consignado: number): number {
  return c.legible ? c.saldoPendiente : Math.max(0, esperado - consignado)
}

/**
 * La diferencia del día YA CONTANDO la cascada, que es la que decide el rojo.
 *
 * Sin cascada da idéntica a la vieja (`consignado − esperado`), porque los tres
 * términos nuevos valen cero: por eso el día normal no cambia ni un píxel.
 *
 * `faltanteSinCubrir` NO se compensa acá a propósito. En un día que quedó con
 * faltante sin tapar esta cuenta da exactamente esa plata que falta, y así el
 * día se queda marcado en rojo por el monto justo. Compensarlo lo pintaría
 * cuadrado, que es precisamente el silencio que veníamos a romper.
 */
export function diferenciaEfectiva(c: Cascada, esperado: number, consignado: number): number {
  if (!c.legible) return consignado - esperado
  return consignado + c.cubrioTotal - c.cubiertoPorTotal - esperado
}

/** ¿El día cerró bien? Con plata faltante sin tapar, nunca. */
export function diaCuadrado(c: Cascada, esperado: number, consignado: number): boolean {
  if (Math.abs(diferenciaEfectiva(c, esperado, consignado)) > 0.5) return false
  return !c.legible || c.faltanteSinCubrir <= 0.5
}
