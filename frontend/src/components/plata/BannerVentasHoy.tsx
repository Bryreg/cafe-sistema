import { ReactNode } from 'react'
import { TrendingUp } from 'lucide-react'
import type { Fuente } from '../../api/useDato'
import { PulsoData, RentabilidadData } from '../rentabilidad/helpers'
import { SegunDato, NoSeSabe } from '../ui'
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
 * Una de las tres celdas de arriba.
 *
 * `apagado` tiñe el número de gris: es lo que separa «todavía no llegó» y «no
 * volvió» de una cifra medida. Un «—» en negro del mismo peso que $1.240.000 se
 * lee como un dato, y acá es justo lo contrario.
 */
function Celda({ label, valor, apagado = false }: {
  label: string; valor: ReactNode; apagado?: boolean
}) {
  return (
    <div className="px-3 py-3">
      <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">{label}</p>
      <p className={`text-xl font-bold font-mono tabular-nums leading-tight mt-0.5 ${
        apagado ? 'text-warm-400' : 'text-warm-700'}`}>
        {valor}
      </p>
    </div>
  )
}

const ROTULOS = ['Vendido hoy', 'Tickets', 'Ticket promedio']

/** Los tres números sin número: «…» mientras se pide, «—» cuando no volvió. */
function TrioMudo({ marca }: { marca: string }) {
  return (
    <div className="grid grid-cols-3 divide-x divide-warm-100">
      {ROTULOS.map(l => <Celda key={l} label={l} valor={marca} apagado />)}
    </div>
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
 *
 * ── DOS FUENTES, DOS VEREDICTOS ────────────────────────────────────────────
 * La venta del día y el trazo del mes son DOS fetch distintos y cada uno tiene
 * su propio estado: con el pulso caído los tres números de arriba siguen siendo
 * buenos, y con la venta de hoy caída el trazo del mes sigue siendo bueno. El
 * viejo `dias.length >= 2` los mezclaba en un solo silencio — un pulso que no
 * volvió se dibujaba idéntico a un mes con un solo día de venta, o sea que la
 * ausencia del trazo se leía como «todavía no vendiste lo suficiente».
 */
export default function BannerVentasHoy({ ventasHoy, pulso }: {
  /** `/rentabilidad/` pedido con desde = hasta = hoy (Colombia). */
  ventasHoy: Fuente<RentabilidadData>
  /** Solo para el trazo del mes: sus KPIs son del mes, no de hoy. */
  pulso: Fuente<PulsoData>
}) {
  return (
    <section className="bg-white rounded-2xl border border-warm-200 overflow-hidden">
      <SegunDato
        dato={ventasHoy.dato}
        cargando={<TrioMudo marca="…" />}
        falla={m => (<>
          <TrioMudo marca="—" />
          {/* El hueco habla. Sin este renglón, tres guiones en gris se leen como
              «hoy no se vendió nada» — que es la conclusión más cara posible a
              las 8 de la mañana. */}
          <div className="px-3 pb-3">
            <NoSeSabe mensaje={`${m} — no se sabe cuánto se vendió hoy.`}
              onReintentar={ventasHoy.recargar} />
          </div>
        </>)}
        listo={r => {
          const n = r.resumen.n_tickets
          const total = r.resumen.ventas
          // Misma fórmula que el backend usa para el ticket promedio del mes. Sin
          // tickets no hay promedio: dividir por cero daría un cero que se leería
          // como «cada cliente gastó $0».
          const promedio = n > 0 ? Math.round(total / n) : null
          return (
            <div className="grid grid-cols-3 divide-x divide-warm-100">
              <Celda label="Vendido hoy" valor={plata(total)} />
              <Celda label="Tickets" valor={n.toLocaleString('es-CO')} />
              <Celda label="Ticket promedio" apagado={promedio == null}
                valor={promedio != null ? plata(promedio) : '—'} />
            </div>
          )
        }}
      />

      {/* El ritmo del mes, debajo de la venta del día: el último punto del trazo
          ES el día de hoy, así que los dos se leen juntos sin explicación. */}
      <div className="px-3 pb-2">
        <SegunDato
          dato={pulso.dato}
          cargando={
            <p className="text-[10px] font-bold uppercase tracking-wide text-warm-400 py-2">
              Cargando el mes, día por día…
            </p>
          }
          falla={m => (
            <NoSeSabe mensaje={`${m} — no se sabe cómo viene el ritmo del mes.`}
              onReintentar={pulso.recargar} />
          )}
          listo={p => {
            const dias = p.ventas_diarias
            // «Un solo día» es una respuesta del backend, y por eso se dice con
            // palabras en vez de dejar el espacio vacío: con menos de dos puntos
            // no hay línea que dibujar, pero sí algo que contar.
            if (dias.length < 2) {
              return (
                <p className="text-[11px] text-warm-500 leading-relaxed py-1">
                  {dias.length === 0
                    ? 'Este mes todavía no hay ningún día con venta registrada, así que no hay ritmo que dibujar.'
                    : 'Este mes hay un solo día con venta: el trazo aparece cuando haya dos.'}
                </p>
              )
            }
            return (<>
              <div className="flex items-baseline justify-between">
                <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500 flex items-center gap-1">
                  <TrendingUp size={11} /> El mes, día por día
                </p>
                <p className="text-[10px] text-warm-400">{dias.length} días con venta</p>
              </div>
              <Sparkline dias={dias} />
            </>)
          }}
        />
      </div>

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
