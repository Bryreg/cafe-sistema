import { TrendingUp } from 'lucide-react'
import { PulsoData, RentabilidadData } from '../rentabilidad/helpers'
import { plata } from './banco'
import { ComoSeCalcula } from './campos'

/**
 * Un solo trazo: cuánto se vendió cada día del mes.
 *
 * OJO CON LOS HUECOS: `pulso.ventas_diarias` trae SOLO los días que tuvieron
 * ventas (services/rentabilidad.py agrupa los tickets por día, así que un día
 * cerrado sencillamente no aparece). Los puntos se dibujan uno al lado del otro,
 * o sea que la línea es «venta por día CON ventas», no una línea de calendario.
 * Dibujar los huecos como cero sería inventar un día de $0 que nadie midió; por
 * eso el pie del banner dice cuántos días trae.
 */
function Sparkline({ dias }: { dias: { dia: string; ventas: number }[] }) {
  if (dias.length < 2) return null
  const W = 280, H = 40
  const max = Math.max(...dias.map(d => d.ventas), 1)
  const pts = dias.map((d, i) => {
    const x = (i / (dias.length - 1)) * (W - 4) + 2
    const y = H - 3 - (d.ventas / max) * (H - 8)
    return `${x},${y}`
  })
  const last = pts[pts.length - 1].split(',')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-10 text-success-500"
      preserveAspectRatio="none" aria-hidden="true">
      <polyline points={`2,${H - 3} ${pts.join(' ')} ${W - 2},${H - 3}`}
        fill="currentColor" fillOpacity="0.10" stroke="none" />
      <polyline points={pts.join(' ')} fill="none" stroke="currentColor" strokeWidth="2"
        strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={last[0]} cy={last[1]} r="3" fill="currentColor" />
    </svg>
  )
}

/**
 * ═════════════════════════════════════════════════════════════════════════════
 * LA VENTA DE HOY — la cabecera de «La plata»
 * ═════════════════════════════════════════════════════════════════════════════
 * Va acá y no en «Resultado» por una razón de plata, no de diseño: lo que se
 * vendió hoy es lo que entra mañana. Es el número que el dueño mira todos los
 * días, y tiene que leerse pegado al saldo del banco y a lo que hay que pagar.
 *
 * ── DE DÓNDE SALE CADA CIFRA, QUE ES LO QUE COSTÓ NUEVE RONDAS ──────────────
 * Los tres números son del DÍA DE HOY y salen de UNA sola consulta:
 * `/rentabilidad/?desde=hoy&hasta=hoy`, que devuelve `ventas` (Σ Ticket.total de
 * los tickets no anulados del día Colombia) y `n_tickets` (cuántos son).
 *
 * NO se reusan los KPIs que traía la pestaña «Hoy»: aquellos venían de
 * `/rentabilidad/pulso`, que es del MES A LA FECHA (get_pulso arranca en el día
 * 1). Mudarlos tal cual y rotularlos «hoy» habría sido, otra vez, decidir con un
 * dato que está CERCA del correcto.
 *
 * El ticket promedio es el único derivado, y se deriva con la MISMA fórmula del
 * backend sobre los MISMOS dos números del MISMO día: `round(ventas / n)`
 * (services/rentabilidad.py, `_ventana`). No es un dato de otra ventana
 * disfrazado: es la división de los dos que están al lado, y por eso se puede
 * verificar a ojo. Sin tickets no se divide: se pinta «—», nunca un cero.
 */
export default function BannerVentasHoy({ ventasHoy, pulso, cargando }: {
  /** `/rentabilidad/` pedido con desde = hasta = hoy (Colombia). */
  ventasHoy: RentabilidadData | null
  /** Solo para el trazo del mes: sus KPIs son del mes, no de hoy. */
  pulso: PulsoData | null
  cargando: boolean
}) {
  const r = ventasHoy?.resumen ?? null
  const n = r?.n_tickets ?? 0
  const total = r?.ventas ?? 0
  // Misma fórmula que el backend usa para el ticket promedio del mes. Sin
  // tickets no hay promedio: dividir por cero daría un cero que se leería como
  // «cada cliente gastó $0».
  const promedio = n > 0 ? Math.round(total / n) : null
  const dias = pulso?.ventas_diarias ?? []

  return (
    <section className="bg-white rounded-2xl border border-warm-200 overflow-hidden">
      <div className="grid grid-cols-3 divide-x divide-warm-100">
        <div className="px-3 py-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">Vendido hoy</p>
          <p className="text-xl font-bold font-mono tabular-nums text-warm-700 leading-tight mt-0.5">
            {cargando ? '…' : r ? plata(total) : '—'}
          </p>
        </div>
        <div className="px-3 py-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">Tickets</p>
          <p className="text-xl font-bold font-mono tabular-nums text-warm-700 leading-tight mt-0.5">
            {cargando ? '…' : r ? n.toLocaleString('es-CO') : '—'}
          </p>
        </div>
        <div className="px-3 py-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">Ticket promedio</p>
          <p className="text-xl font-bold font-mono tabular-nums text-warm-700 leading-tight mt-0.5">
            {cargando ? '…' : promedio != null ? plata(promedio) : '—'}
          </p>
        </div>
      </div>

      {/* El ritmo del mes, debajo de la venta del día: el último punto del trazo
          ES el día de hoy, así que los dos se leen juntos sin explicación. */}
      {dias.length >= 2 && (
        <div className="px-3 pb-2">
          <div className="flex items-baseline justify-between">
            <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500 flex items-center gap-1">
              <TrendingUp size={11} /> El mes, día por día
            </p>
            <p className="text-[10px] text-warm-400">{dias.length} días con venta</p>
          </div>
          <Sparkline dias={dias} />
        </div>
      )}

      <ComoSeCalcula titulo="¿De dónde salen estos tres números?">
        <p>
          Son del <b>día de hoy</b> según el reloj de Colombia: lo vendido es la suma de los
          tickets no anulados y «Tickets» es cuántos fueron. El ticket promedio es lo vendido
          dividido por los tickets — la misma división que podés hacer a ojo con los dos números
          de al lado.
        </p>
        <p>
          El trazo del mes muestra <b>solo los días que tuvieron ventas</b>: un día cerrado no
          aparece como cero, sencillamente no está. Por eso al lado dice cuántos días trae.
        </p>
        <p>
          Lo que se vende hoy es la plata que entra al banco mañana o pasado (el datáfono liquida
          con rezago y con la comisión ya descontada), así que este número <b>no</b> es el saldo
          de la cuenta: ese está en el banner de abajo.
        </p>
      </ComoSeCalcula>
    </section>
  )
}
