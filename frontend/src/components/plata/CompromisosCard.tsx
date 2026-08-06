import { AlertCircle, ArrowRight, CalendarDays, TrendingDown } from 'lucide-react'
import { Agenda, Flujo } from '../../pages/Costos'
import { fmt } from '../rentabilidad/helpers'

// "Hoy" según el reloj de COLOMBIA (el negocio), no el del navegador.
const hoyBogota = () => new Date().toLocaleDateString('en-CA', { timeZone: 'America/Bogota' })
const sumarDias = (iso: string, n: number) => {
  const d = new Date(iso + 'T00:00:00')
  d.setDate(d.getDate() + n)
  return d.toLocaleDateString('en-CA')
}
const fechaCorta = (s: string) =>
  new Date(s + 'T00:00:00').toLocaleDateString('es-CO', { day: 'numeric', month: 'short' })

/**
 * «Lo que se viene»: cuánta plata hay que pagar en los próximos 7 y 30 días, y el
 * día en que la proyección se queda sin plata.
 *
 * Es el bloque que la fusión existe para crear. Estos números ya se calculaban,
 * pero vivían en OTRA pantalla que el dueño nunca abría junto al margen — así que
 * el margen del mes y la plata que se va la semana que viene nunca se leían
 * juntos, que es la única forma en que sirven para decidir algo.
 */
export default function CompromisosCard({ agenda, flujo, onVerCalendario }: {
  agenda: Agenda | null
  flujo: Flujo | null
  onVerCalendario: () => void
}) {
  const hoy = flujo?.hoy ?? hoyBogota()
  const tope7 = sumarDias(hoy, 7)
  const tope30 = sumarDias(hoy, 30)
  const items = agenda?.items ?? []
  // Lo vencido NO entra en «próximos días»: se debe AHORA, y mezclarlo con lo que
  // falta pagar más adelante hace que una mora vieja se lea como un pago futuro.
  const porVencer = items.filter(i => !i.vencida)
  const prox7 = porVencer.filter(i => i.fecha <= tope7).reduce((s, i) => s + i.monto, 0)
  const prox30 = porVencer.filter(i => i.fecha <= tope30).reduce((s, i) => s + i.monto, 0)
  const vencido = agenda?.totales.vencido ?? 0

  const quiebre = flujo?.punto_de_quiebre ?? null
  const a = flujo?.advertencias
  // Sin salidas cargadas o sin historia de ventas, la AUSENCIA de quiebre no
  // afirma nada: el silencio verde sería la mentira más cara de la pantalla.
  const proyeccionCiega = !!a && (a.sin_salidas_cargadas || a.sin_historia_ventas)

  return (
    <div className="bg-white rounded-2xl border border-warm-200 shadow-sm overflow-hidden">
      <button onClick={onVerCalendario}
        className="w-full flex items-center gap-2 px-4 py-3 border-b border-warm-100 text-left">
        <CalendarDays size={15} className="text-forest shrink-0" />
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-bold text-warm-700">Lo que se viene</span>
          <span className="block text-[11px] text-warm-500">Facturas de proveedor + costos fijos con fecha</span>
        </span>
        <ArrowRight size={15} className="text-warm-400 shrink-0" />
      </button>

      <div className="grid grid-cols-2 divide-x divide-warm-100">
        <div className="px-4 py-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">Próximos 7 días</p>
          <p className="text-xl font-bold font-mono text-warm-700 tabular-nums leading-tight mt-0.5">
            {fmt(prox7)}
          </p>
        </div>
        <div className="px-4 py-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">Próximos 30 días</p>
          <p className="text-xl font-bold font-mono text-warm-700 tabular-nums leading-tight mt-0.5">
            {fmt(prox30)}
          </p>
        </div>
      </div>

      {/* Lo vencido va aparte y en rojo: no es "lo que viene", es lo que ya pasó. */}
      {vencido > 0 && (
        <button onClick={onVerCalendario}
          className="w-full flex items-center gap-2 px-4 py-2.5 border-t border-warm-100 bg-danger-50 text-left">
          <AlertCircle size={14} className="text-danger-600 shrink-0" />
          <span className="text-xs font-bold text-danger-700 flex-1">Vencido — pagalo ya</span>
          <span className="font-mono font-bold text-sm text-danger-700 tabular-nums">{fmt(vencido)}</span>
        </button>
      )}

      {/* El punto de quiebre: el día en que te quedás sin plata, ANTES de que pase. */}
      {quiebre && (
        <div className="flex items-start gap-2 px-4 py-2.5 border-t border-warm-100 bg-danger-50">
          <TrendingDown size={14} className="text-danger-600 mt-0.5 shrink-0" />
          <p className="text-xs font-bold text-danger-700 leading-relaxed">
            Te quedás sin plata el {fechaCorta(quiebre)}
            {flujo?.dias_hasta_quiebre != null && ` — en ${flujo.dias_hasta_quiebre} día${flujo.dias_hasta_quiebre !== 1 ? 's' : ''}`}
          </p>
        </div>
      )}
      {!quiebre && proyeccionCiega && (
        <button onClick={onVerCalendario}
          className="w-full flex items-start gap-2 px-4 py-2.5 border-t border-warm-100 bg-gold-50 text-left">
          <AlertCircle size={14} className="text-gold-700 mt-0.5 shrink-0" />
          <span className="text-[11px] text-gold-700 leading-relaxed">
            <b>La proyección no alcanza para afirmar nada todavía.</b>{' '}
            {a?.sin_salidas_cargadas
              ? 'No hay ni un pago cargado en el horizonte: lo que sale solo existe si alguien lo tecleó.'
              : 'No hay ventas de las últimas 8 semanas para estimar lo que entra.'}
          </span>
        </button>
      )}
    </div>
  )
}
