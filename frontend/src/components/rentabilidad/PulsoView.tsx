import { TrendingUp, TrendingDown, ArrowRight } from 'lucide-react'
import {
  RentabilidadData, PorProductoData, PulsoData, Jugada,
  fmt, fmtK, pctDelta,
} from './helpers'

function Delta({ v }: { v: number | null }) {
  if (v == null) return null
  const up = v >= 0
  return (
    <span className={`inline-flex items-center gap-0.5 text-[11px] font-bold ${up ? 'text-success-600' : 'text-danger-500'}`}>
      {up ? <TrendingUp size={11} /> : <TrendingDown size={11} />}{up ? '+' : ''}{v}%
    </span>
  )
}

function Sparkline({ dias }: { dias: { dia: string; ventas: number }[] }) {
  if (dias.length < 2) return null
  const W = 280, H = 44
  const max = Math.max(...dias.map(d => d.ventas), 1)
  const pts = dias.map((d, i) => {
    const x = (i / (dias.length - 1)) * (W - 4) + 2
    const y = H - 3 - (d.ventas / max) * (H - 8)
    return `${x},${y}`
  })
  const last = pts[pts.length - 1].split(',')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-11 text-success-500" preserveAspectRatio="none" aria-hidden="true">
      <polyline points={`2,${H - 3} ${pts.join(' ')} ${W - 2},${H - 3}`}
        fill="currentColor" fillOpacity="0.10" stroke="none" />
      <polyline points={pts.join(' ')} fill="none" stroke="currentColor" strokeWidth="2"
        strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={last[0]} cy={last[1]} r="3" fill="currentColor" />
    </svg>
  )
}

const JUGADA_ICON: Record<Jugada['tipo'], string> = {
  costo: '🔧', combo: '🎁', addon: '➕', daypart: '🕒', precio: '⚠️',
}

export default function PulsoView({ pulso, plMes, jugadas, onVerJugadas }: {
  pulso: PulsoData | null
  plMes: RentabilidadData | null
  prodData: PorProductoData | null
  jugadas: Jugada[]
  onVerJugadas: () => void
}) {
  const r = plMes?.resumen
  const act = pulso?.mes_actual
  const ant = pulso?.mes_anterior
  const pct = r?.pct_margen_neto ?? null
  // Semáforo del margen operativo de caja (no incluye nómina/arriendo).
  const estado = pct == null ? null : pct >= 65 ? 'bien' : pct >= 50 ? 'ojo' : 'alerta'
  const estadoUi = {
    bien: { label: 'Sano', cls: 'bg-success-50 text-success-600 border-success-200' },
    ojo: { label: 'Ojo', cls: 'bg-gold-50 text-gold-700 border-gold-200' },
    alerta: { label: 'Alerta', cls: 'bg-danger-50 text-danger-700 border-danger-200' },
  } as const

  const dVentas = act && ant ? pctDelta(act.ventas, ant.ventas) : null
  const dTickets = act && ant ? pctDelta(act.tickets, ant.tickets) : null
  const dTicketProm = act?.ticket_promedio && ant?.ticket_promedio
    ? pctDelta(act.ticket_promedio, ant.ticket_promedio) : null

  const sedes = plMes?.por_sede ?? []
  const maxSedeVenta = Math.max(1, ...sedes.map(s => s.ventas))

  return (
    <div className="space-y-3">
      {/* Hero: margen operativo de caja del mes */}
      <div className="bg-white rounded-2xl border border-warm-200 shadow-sm p-5">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500">
              Margen operativo de caja · mes en curso
            </p>
            <p className="text-[32px] leading-tight font-extrabold font-mono text-warm-700 tabular-nums">
              {r ? fmt(r.margen_neto) : '—'}
            </p>
            <p className="text-xs text-warm-500 mt-0.5">
              {pct != null ? `${pct}% de la venta` : ''} · no incluye nómina ni arriendo
            </p>
          </div>
          {estado && (
            <span className={`px-2.5 py-1 rounded-full border text-xs font-bold ${estadoUi[estado].cls}`}>
              {estadoUi[estado].label}
            </span>
          )}
        </div>
        {pulso && <div className="mt-3"><Sparkline dias={pulso.ventas_diarias} /></div>}
        {dVentas != null && (
          <p className="text-xs text-warm-500 mt-1.5">
            Ventas <Delta v={dVentas} /> vs el mismo período del mes pasado
          </p>
        )}
      </div>

      {/* KPIs de la estrategia (ticket promedio = EL indicador) */}
      <div className="grid grid-cols-3 gap-2">
        <div className="bg-white rounded-2xl border border-warm-200 p-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">Ticket promedio</p>
          <p className="text-lg font-bold font-mono text-warm-700 tabular-nums leading-tight mt-0.5">
            {act?.ticket_promedio ? fmt(act.ticket_promedio) : '—'}
          </p>
          <Delta v={dTicketProm} />
        </div>
        <div className="bg-white rounded-2xl border border-warm-200 p-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">Tickets</p>
          <p className="text-lg font-bold font-mono text-warm-700 tabular-nums leading-tight mt-0.5">
            {act ? act.tickets.toLocaleString('es-CO') : '—'}
          </p>
          <Delta v={dTickets} />
        </div>
        <div className="bg-white rounded-2xl border border-warm-200 p-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">Ventas</p>
          <p className="text-lg font-bold font-mono text-warm-700 tabular-nums leading-tight mt-0.5">
            {act ? fmtK(act.ventas) : '—'}
          </p>
          <Delta v={dVentas} />
        </div>
      </div>

      {/* Duelo de sedes */}
      {sedes.length > 1 && (
        <div className="bg-white rounded-2xl border border-warm-200 p-4">
          <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500 mb-2.5">Sedes · mes en curso</p>
          <div className="space-y-2.5">
            {sedes.map(s => (
              <div key={s.tienda_id}>
                <div className="flex items-baseline justify-between text-sm">
                  <span className="font-semibold text-warm-700">{s.tienda}</span>
                  <span className="font-mono text-warm-600 tabular-nums">
                    {fmtK(s.ventas)} · <span className={s.margen_neto >= 0 ? 'text-success-600 font-bold' : 'text-danger-500 font-bold'}>{fmtK(s.margen_neto)}</span>
                    {s.pct_margen_neto != null && <span className="text-warm-400"> ({s.pct_margen_neto}%)</span>}
                  </span>
                </div>
                <div className="h-2 rounded-full bg-warm-100 overflow-hidden mt-1">
                  <div className="h-full rounded-full bg-forest-400" style={{ width: `${Math.max(4, (s.ventas / maxSedeVenta) * 100)}%` }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Teaser: tus próximas 3 jugadas */}
      {jugadas.length > 0 && (
        <div className="bg-white rounded-2xl border border-warm-200 overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-warm-100">
            <p className="text-sm font-bold text-warm-700">Tus próximas jugadas</p>
            <button onClick={onVerJugadas}
              className="flex items-center gap-1 text-xs font-bold text-forest min-h-[44px] px-2 -mr-2">
              Ver todas <ArrowRight size={13} />
            </button>
          </div>
          {jugadas.slice(0, 3).map(j => (
            <button key={j.id} onClick={onVerJugadas}
              className="w-full text-left flex items-center gap-3 px-4 py-2.5 border-b border-warm-100 last:border-0 active:scale-[0.99] transition-transform">
              <span className="text-lg" aria-hidden="true">{JUGADA_ICON[j.tipo]}</span>
              <span className="flex-1 min-w-0">
                <span className="block text-sm font-semibold text-warm-700 truncate">{j.titulo}</span>
                <span className="block text-[11px] text-success-600 font-bold">{j.impacto}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
