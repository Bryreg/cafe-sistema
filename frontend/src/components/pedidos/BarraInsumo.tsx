import { useId, useMemo } from 'react'
import type { Curva, PuntoCurva, ConteoCurva } from './FichaInsumo'
import { instanteCol } from '../../utils/fechaLocal'

/**
 * La vida de un insumo en una barra.
 *
 * La barra arranca con lo que había, baja con cada venta y deja la SOMBRA de lo
 * que se fue; cuando llega mercadería sube por encima y la sombra crece con
 * ella. Encima van los CONTEOS: la curva es lo que el sistema cree, el punto es
 * lo que alguien vio de verdad en el estante, y el palito que los une es la
 * diferencia, a escala. No hay que leer un número para saber si es grande.
 *
 * Tres decisiones de dibujo que no son cosméticas:
 *
 *  · ES UN ÁREA ESCALONADA, no una línea suave. El stock no cambia de a poquito:
 *    cambia de golpe con cada venta y con cada llegada. Una curva suave
 *    inventaría un movimiento continuo que nunca ocurrió.
 *
 *  · CADA FILA TIENE SU PROPIA ESCALA VERTICAL. Un insumo se mide en gramos y
 *    otro en unidades; una escala compartida diría que el café es mil veces más
 *    importante que las pulpas, que no es cierto — es otra unidad. Lo comparable
 *    entre filas es LA FORMA (si baja parejo, si se agota, si el conteo se
 *    despega siempre para el mismo lado); las cantidades van escritas.
 *
 *  · EL VALOR CONTADO ENTRA EN LA ESCALA. Si la barista vio 2.470 gr más de los
 *    que el sistema llegó a tener nunca, ese número es parte del dibujo:
 *    recortarlo para que la curva se vea linda escondería justo el hallazgo.
 *
 * Los puntos de conteo van en HTML y no en el SVG: el viewBox está estirado a lo
 * ancho (`preserveAspectRatio="none"`) y un <circle> saldría ovalado. La escala
 * vertical es 1:1 —52 unidades, 52 px— así que la Y del SVG ya es la posición en
 * píxeles del punto.
 */

const W = 1000, ALTO = 52, PAD = 3
const EPS = 0.001

/** Dónde cae, en % del ancho, un instante del rango (0 = arranque, 1 = cierre).
 *  La regla de tiempo y la barra tienen que usar exactamente esta función: si
 *  cada una hiciera su cuenta, los 3 px de PAD alcanzarían para que la raya del
 *  día quedara medio día corrida respecto del escalón que nombra. */
export const posPct = (u: number) =>
  ((PAD + Math.max(0, Math.min(1, u)) * (W - PAD * 2)) / W) * 100

const MESES_CORTO = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
                     'jul', 'ago', 'sep', 'oct', 'nov', 'dic']

export interface MarcaTiempo { u: number; texto: string }

/** Las marcas del eje horizontal: sin ellas la barra dice CUÁNDO en relación a
 *  sí misma —«bajó al principio y se llenó al final»— pero no contra el
 *  calendario, y la pregunta que uno le hace mirando es «¿qué día fue eso?».
 *
 *  El paso se elige para dejar unas diez etiquetas, sea el rango de un día o de
 *  ocho semanas: más se pisan entre ellas en la tablet, menos y hay que contar
 *  con el dedo. En un solo día la referencia son las horas de servicio y no la
 *  fecha, que es una sola. */
export function marcasTiempo(desdeUtc: string | undefined, span: number): MarcaTiempo[] {
  if (!desdeUtc || !(span > 0)) return []
  const t0 = instanteCol(desdeUtc).getTime()
  if (Number.isNaN(t0)) return []
  const marcas: MarcaTiempo[] = []

  if (span <= 1.6 * 86400) {
    for (let h = 0; h * 3600 <= span; h += 4) {
      marcas.push({
        u: (h * 3600) / span,
        texto: h === 0 ? '12am' : h === 12 ? '12m' : h < 12 ? `${h}am` : `${h - 12}pm`,
      })
    }
    return marcas
  }

  const dias = span / 86400
  // Once y no diez: con diez, el mes de 31 días saltaba al paso semanal y el de
  // 28 se quedaba en el de tres, así que dos rangos casi iguales se leían con
  // reglas distintas.
  const paso = [1, 2, 3, 7, 14, 28].find(p => dias / p <= 11) ?? 28
  // El día se lee en hora de COLOMBIA y no del dispositivo, por lo mismo que el
  // resto de la pantalla: la fecha del negocio es una sola.
  const fmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Bogota', year: 'numeric', month: '2-digit', day: '2-digit',
  })
  let mesPrevio = -1
  for (let k = 0; k * 86400 <= span + 1; k += paso) {
    const [, mm, dd] = fmt.format(new Date(t0 + k * 86400000)).split('-')
    const mes = Number(mm)
    // El mes se escribe sólo cuando cambia: repetirlo en las diez marcas es
    // ruido, y no ponerlo nunca deja «1» sin saber de qué mes es.
    const cambio = mes !== mesPrevio
    mesPrevio = mes
    marcas.push({
      u: (k * 86400) / span,
      texto: cambio ? `${Number(dd)} ${MESES_CORTO[mes - 1] ?? mm}` : `${Number(dd)}`,
    })
  }
  return marcas
}

/** La regla de tiempo. Va arriba y abajo de la lista, no en cada fila: son 110
 *  filas y repetir el calendario en todas taparía las barras. */
export function EjeTiempo({ desdeUtc, span }: { desdeUtc?: string; span: number }) {
  const marcas = useMemo(() => marcasTiempo(desdeUtc, span), [desdeUtc, span])
  if (marcas.length < 2) return null
  return (
    <div className="relative h-[17px] select-none" aria-hidden="true">
      {marcas.map((m, i) => {
        const p = posPct(m.u)
        const tira = i === 0 ? 'translateX(0)'
          : i === marcas.length - 1 ? 'translateX(-100%)' : 'translateX(-50%)'
        return (
          <span key={i} className="absolute top-0 flex flex-col items-start"
            style={{ left: `${p}%`, transform: tira }}>
            <i className="w-px h-[4px] bg-warm-300"
              style={{ marginLeft: i === 0 ? 0 : i === marcas.length - 1 ? '100%' : '50%' }} />
            <span className="font-mono text-[9.5px] leading-none text-warm-400 whitespace-nowrap mt-[3px]">
              {m.texto}
            </span>
          </span>
        )
      })}
    </div>
  )
}

/** Los tokens del `tailwind.config.js` resueltos a hex. Van literales y no como
 *  clases porque adentro del dibujo hacen falta alfas (`#00713e1a`) y Tailwind
 *  no sabe ponerle opacidad a un `oklch()` crudo: la clase no se genera y el
 *  relleno cae a NEGRO, que fue exactamente lo que pasó la primera vez. */
const C = {
  stock: '#00713e',          // forest-500 — lo que hay
  stockRelleno: '#00713e1a',
  sombra: '#e7e4e0',         // warm-200 — el hueco que dejó lo que salió
  sombraBorde: '#a8a3a0',    // warm-400
  entra: '#bf6700',          // gold-500 — llegó mercadería
  alerta: '#c64a3a',         // danger-500 — bajó de cero
  conteo: '#1e1a16',         // warm-700 — lo único que no sale del libro
  conteoAtajo: '#a8a3a0',    // warm-400 — «todo coincide»: un eco, no una mirada
  palito: '#7f7974',         // warm-500 — la diferencia, a escala
  papel: '#ffffff',
}

export const num = (v: number) => {
  const n = Number(v) || 0, a = Math.abs(n)
  return a < 10 && !Number.isInteger(n)
    ? n.toLocaleString('es-CO', { maximumFractionDigits: 2 })
    : Math.round(n).toLocaleString('es-CO')
}
export const firmado = (v: number) =>
  (v > EPS ? '+' : v < -EPS ? '−' : '') + num(Math.abs(v))

/** Un conteo no es una categoría más de movimiento: es la medición contra la que
 *  se juzga todo lo demás. Con siete miradas lo que importa no es cada
 *  diferencia sino si el desacuerdo va SIEMPRE para el mismo lado — eso separa
 *  una fuga de la forma de contar. */
export type ClaveVeredicto = 'cuadra' | 'sobra' | 'falta' | 'mixto' | 'medido'
export interface Veredicto {
  clave: ClaveVeredicto; texto: string
  n: number; mas: number; menos: number; tipico: number
}

export function veredicto(cs: ConteoCurva[] | undefined, opcional = false): Veredicto | null {
  if (!cs || !cs.length) return null
  const mas = cs.filter(c => c.dif > EPS).length
  const menos = cs.filter(c => c.dif < -EPS).length
  const abs = cs.map(c => Math.abs(c.dif)).filter(v => v > EPS).sort((a, b) => a - b)
  const tipico = abs.length ? abs[Math.floor(abs.length / 2)] : 0
  // EN UN INSUMO OPCIONAL EL DESACUERDO NO ES UNA FUGA. El cliente pide azúcar
  // en tubos o no lo pide, así que la caja nunca lo descuenta y el saldo del
  // sistema se queda quieto mientras el estante se vacía: cada conteo TIENE que
  // dar por debajo, y esa distancia es el consumo. Llamarlo «siempre falta»
  // mandaría al dueño a buscar un ladrón donde sólo hay clientes.
  //
  // Lo que sí es raro es al revés: si el conteo da POR ENCIMA, apareció
  // mercadería que nadie registró.
  if (opcional) {
    const clave: ClaveVeredicto = mas ? 'sobra' : 'medido'
    return { clave, n: cs.length, mas, menos, tipico,
             texto: mas ? 'entró sin registrar' : 'el conteo lo mide' }
  }
  const clave: ClaveVeredicto =
    !mas && !menos ? 'cuadra' : !menos ? 'sobra' : !mas ? 'falta' : 'mixto'
  const texto = { cuadra: 'el conteo cuadra', sobra: 'siempre sobra',
                  falta: 'siempre falta', mixto: 'va y viene' }[clave]
  return { clave, texto, n: cs.length, mas, menos, tipico }
}

export const CHIP_VEREDICTO: Record<ClaveVeredicto, string> = {
  cuadra: 'bg-forest-50 text-forest-500',
  medido: 'bg-forest-50 text-forest-500',
  sobra: 'bg-warm-100 text-warm-600',
  falta: 'bg-warm-100 text-warm-600',
  mixto: 'bg-warm-100 text-warm-600',
}

/** ¿El saldo estuvo por debajo de cero en el período?
 *
 *  No es lo mismo que `en_negativo`, que mira sólo cómo terminó. Un insumo puede
 *  hundirse a −5 el martes —se vendieron croissants antes de cargar la factura
 *  que los trajo— y volver a subir el jueves cuando alguien la registró. El
 *  saldo se arregla solo, pero el hecho no se borra: durante esos días el
 *  sistema no sabía lo que tenía, y cualquier pedido de esos días salió mal.
 *
 *  Se mira sólo DESPUÉS del último ajuste, porque antes de un ajuste el saldo es
 *  reconstrucción y un negativo puede ser de la reconstrucción, no del estante. */
export function bajoDeCero(curva: Curva | undefined): boolean {
  const pts = curva?.puntos
  if (!pts || !pts.length) return false
  // Cualquier punto FIRME por debajo de cero, esté antes o después de un ajuste.
  // Se excluyen los estimados porque ahí el negativo puede ser de la
  // reconstrucción («arrancó en cero») y no del estante.
  return pts.some(p => p.v < -EPS && !p.est)
}

interface Props {
  curva: Curva
  /** Segundos que dura el rango. Fija el eje horizontal para TODAS las filas:
   *  sin esto cada barra escalaría a su último movimiento y el miércoles de una
   *  fila caería en un sitio distinto que el de la otra. */
  span: number
  /** Dónde caen las marcas de la regla de tiempo, en 0..1. Se dibujan adentro
   *  de la barra para poder BAJAR LA VISTA desde un escalón hasta la fecha: con
   *  la regla sólo arriba, en una fila que está 40 cm más abajo hay que adivinar
   *  a ojo, y a ojo el miércoles y el jueves son el mismo píxel. */
  guias?: number[]
  /** Alto en px. En la lista son 52 —110 filas en una tablet—, pero en la ficha
   *  hay una sola barra y el ancho de la pantalla entera: a 52 px de alto y 830
   *  de ancho la curva queda planchada y deja de mostrar la forma, que es lo
   *  único que la barra tiene para decir. */
  alto?: number
  onConteo?: (c: ConteoCurva) => void
  onPunto?: (p: PuntoCurva) => void
}

export default function BarraInsumo({ curva, span, guias, alto = ALTO, onConteo, onPunto }: Props) {
  const uid = useId().replace(/:/g, '')
  const H = alto
  const g = useMemo(() => geometria(curva, span, H), [curva, span, H])
  if (!g) return <div style={{ height: H }} />

  const { paso, marcas, X, Y, piso, tope, ultAj, bajoCero, finEstimado } = g
  const escalones = (campo: 'v' | 'techo') => {
    let d = `M ${X(paso[0].x)} ${Y(paso[0][campo])}`
    for (let i = 1; i < paso.length; i++) {
      d += ` L ${X(paso[i].x)} ${Y(paso[i - 1][campo])} L ${X(paso[i].x)} ${Y(paso[i][campo])}`
    }
    return d
  }
  const area = (campo: 'v' | 'techo') =>
    `${escalones(campo)} L ${X(paso[paso.length - 1].x)} ${Y(piso)} L ${X(paso[0].x)} ${Y(piso)} Z`

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
        style={{ height: H }} className="block w-full overflow-visible"
        aria-label={`Arranca en ${num(paso[0].v)} y queda en ${num(paso[paso.length - 1].v)}`}>
        {/* La sombra: el espacio que el insumo llegó a ocupar y ya no ocupa. */}
        <path d={area('techo')} fill={C.sombra} />
        <path d={escalones('techo')} fill="none" strokeWidth="1.5" strokeDasharray="4 4"
          vectorEffect="non-scaling-stroke" stroke={C.sombraBorde} />
        <path d={area('v')} fill={C.stockRelleno} />

        {/* Las rayas del calendario. Van apagadísimas y por debajo de la curva:
            son la referencia contra la que se lee el dibujo, no parte de él. */}
        {guias?.map((u, i) => (
          <line key={`g${i}`} x1={(u * (W - PAD * 2)) + PAD} x2={(u * (W - PAD * 2)) + PAD}
            y1={0} y2={H} strokeWidth="1" vectorEffect="non-scaling-stroke"
            stroke={C.sombraBorde} opacity=".3" />
        ))}

        {/* EL TRAMO ESTIMADO. El saldo previo a un ajuste viejo no quedó
            registrado en ninguna parte, así que la escalera lo deduce suponiendo
            que el producto arrancó en cero. Sin esta marca el punto del conteo
            queda lejos de la curva y se lee como una fuga enorme, cuando lo que
            está lejos es la suposición: en producción son ~35 insumos por sede,
            casi todos desechables con un ajuste antiguo. */}
        {finEstimado !== null ? (
          <>
            <defs>
              <clipPath id={`est${uid}`}>
                <rect x={0} y={0} width={X(finEstimado)} height={H} />
              </clipPath>
              <clipPath id={`firme${uid}`}>
                <rect x={X(finEstimado)} y={0} width={W - X(finEstimado)} height={H} />
              </clipPath>
            </defs>
            <rect x={0} y={0} width={X(finEstimado)} height={H} fill={C.papel} opacity=".55" />
            <path d={escalones('v')} fill="none" strokeWidth="2" strokeLinejoin="round"
              vectorEffect="non-scaling-stroke" stroke={C.stock} clipPath={`url(#firme${uid})`} />
            <path d={escalones('v')} fill="none" strokeWidth="2" strokeLinejoin="round"
              strokeDasharray="5 4" opacity=".75"
              vectorEffect="non-scaling-stroke" stroke={C.stock} clipPath={`url(#est${uid})`} />
            <line x1={X(finEstimado)} x2={X(finEstimado)} y1={0} y2={H} strokeWidth="1.5"
              vectorEffect="non-scaling-stroke" stroke={C.sombraBorde} />
          </>
        ) : (
          <path d={escalones('v')} fill="none" strokeWidth="2" strokeLinejoin="round"
            vectorEffect="non-scaling-stroke" stroke={C.stock} />
        )}

        {/* Un conteo aplicado FIJA el saldo. Se marca el instante con una línea;
            apagar medio gráfico exageraría la duda hasta la forma, que sí es dato. */}
        {ultAj >= 0 && (
          <line x1={X(paso[ultAj].x)} x2={X(paso[ultAj].x)} y1={0} y2={H} strokeWidth="1.5"
            strokeDasharray="3 3" vectorEffect="non-scaling-stroke" stroke={C.sombraBorde} />
        )}

        {/* Bajo cero: imposible en el estante, así que es una certeza y no una sospecha. */}
        {/* LA RAYA DEL CERO SE DIBUJA SIEMPRE QUE HAYA ALGO DEBAJO. Antes sólo
            salía si el hundimiento era posterior al último ajuste, y con eso 23
            filas dibujaban curva bajo cero sin una sola marca: el café de Vida
            tocó −11.996 gr y la fila mostraba un tranquilo «6.024». El cero es
            la única referencia vertical del gráfico; apagarla justo donde hace
            falta es lo contrario de lo que debía hacer.
            El TINTE rojo sigue reservado al tramo posterior al último ajuste,
            que es donde el negativo es dato y no reconstrucción. */}
        {piso < 0 && (
          <>
            {bajoCero && (
              <rect x={X(0)} y={Y(0)} width={X(1) - X(0)} height={Y(piso) - Y(0)}
                fill={C.alerta} opacity=".14" />
            )}
            <line x1={X(0)} x2={X(1)} y1={Y(0)} y2={Y(0)} strokeWidth="1.5" strokeDasharray="4 3"
              vectorEffect="non-scaling-stroke" stroke={C.alerta} />
          </>
        )}

        {/* EL PALO MIDE LA ENTREGA, NO EL SALDO. Iba del piso hasta el nivel de
            después, y la altura —que es el canal que uno lee como cantidad—
            terminaba codificando el saldo resultante: siete entregas de 50
            unidades de almojábanas se dibujaban con alturas del 51% al 100%, y
            una entrega de 96 salía más alta que una de 12 por razones que no
            eran su tamaño. Ahora es sólo el escalón que subió. */}
        {paso.map((s, i) => (s.p.k !== 'entrada' ? null : (
          <line key={`e${i}`} x1={X(s.x)} x2={X(s.x)}
            y1={Y(i > 0 ? paso[i - 1].v : s.v)} y2={Y(s.v)}
            strokeWidth="2.5" vectorEffect="non-scaling-stroke" stroke={C.entra} />
        )))}

        {/* El palito entre la curva y el conteo: la diferencia, a escala. */}
        {marcas.filter(m => Math.abs(m.yr - m.yc) > 1.5).map((m, i) => (
          <line key={`c${i}`} x1={m.xp * 10} x2={m.xp * 10} y1={m.yc} y2={m.yr}
            strokeWidth="1.5" vectorEffect="non-scaling-stroke" stroke={C.palito} />
        ))}

        {/* El área para tocar cada escalón se reparte TODO el ancho: de la mitad
            del hueco con el punto anterior a la mitad del hueco con el
            siguiente. Eran 10 unidades fijas centradas en cada punto —el 1% del
            ancho—, y en un insumo con pocos movimientos eso deja el gráfico
            lleno de huecos muertos: en la ficha grande el dedo caía entre dos
            escalones y no pasaba nada. Ahora cada píxel pertenece a alguno. */}
        {onPunto && paso.map((s, i) => {
          const izq = i === 0 ? 0 : (X(paso[i - 1].x) + X(s.x)) / 2
          const der = i === paso.length - 1 ? W : (X(s.x) + X(paso[i + 1].x)) / 2
          return (
            <rect key={`h${i}`} x={izq} y={0} width={Math.max(1, der - izq)} height={H}
              fill="transparent" style={{ pointerEvents: 'all' }}
              onMouseEnter={() => onPunto(s.p)} />
          )
        })}
      </svg>

      {/* El punto lleva el tono más fuerte de la pantalla porque es lo único que
          no sale del libro: alguien miró el estante y anotó. El envoltorio de
          24 px es área de toque —en la tablet un círculo de 9 px no se acierta
          con el dedo— y el aro del color del papel lo despega de la curva. */}
      <span className="absolute inset-0 pointer-events-none">
        {marcas.map((m, i) => (
          <span key={i}
            onMouseEnter={onConteo ? () => onConteo(m.c) : undefined}
            className="absolute w-6 h-6 -translate-x-1/2 -translate-y-1/2 grid place-items-center pointer-events-auto"
            style={{ left: `${m.xp}%`, top: `${m.yr}px` }}>
            <i className="w-[9px] h-[9px] rounded-full"
              style={{ background: m.c.es_atajo ? C.conteoAtajo : C.conteo,
                       boxShadow: `0 0 0 2px ${C.papel}` }} />
          </span>
        ))}
      </span>
    </div>
  )
}

// ─── Geometría ────────────────────────────────────────────────────────────────

function geometria(curva: Curva, span: number, H: number) {
  const pts = curva.puntos
  if (!pts || pts.length < 2) return null
  const dur = span || 1

  // El TECHO es el máximo que el stock alcanzó HASTA cada momento: la sombra es
  // lo que queda entre el techo y la curva, o sea el hueco que dejó lo que salió.
  let techo = -Infinity
  const paso = pts.map(p => {
    techo = Math.max(techo, p.v)
    return { x: Math.max(0, Math.min(1, p.t / dur)), v: p.v, techo, p }
  })

  const reales = (curva.conteos ?? []).map(c => c.real)
  const tope = Math.max(...paso.map(s => s.techo), ...reales, 0.0001)
  const piso = Math.min(0, ...paso.map(s => s.v), ...reales)
  const rango = tope - piso || 1
  const X = (u: number) => PAD + u * (W - PAD * 2)
  const Y = (v: number) => H - PAD - ((v - piso) / rango) * (H - PAD * 2)

  const ultAj = paso.reduce((a, s, k) => (s.p.k === 'ajuste' ? k : a), -1)
  const bajoCero = paso.slice(ultAj + 1).some(s => s.v < -EPS)
  // Hasta dónde llega la reconstrucción. Es siempre un PREFIJO: la pasada
  // estimada cubre el tramo más viejo, antes del primer ajuste del libro.
  const ultEst = paso.reduce((a, s, k) => (s.p.est ? k : a), -1)
  const finEstimado = ultEst < 0 ? null
    : Math.min(1, ultEst + 1 < paso.length ? paso[ultEst + 1].x : 1)

  const marcas = (curva.conteos ?? []).map(c => {
    const u = Math.max(0, Math.min(1, c.t / dur))
    return { xp: (X(u) / W) * 100, yr: Y(c.real), yc: Y(c.curva), c }
  })

  return { paso, marcas, X, Y, piso, tope, ultAj, bajoCero, finEstimado }
}
