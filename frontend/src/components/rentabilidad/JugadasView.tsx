import { Wrench, Gift, Plus, Clock, ArrowUpRight, SlidersHorizontal } from 'lucide-react'
import { Jugada, PulsoData } from './helpers'

const TIPO_UI: Record<Jugada['tipo'], { Icon: typeof Wrench; label: string; cls: string }> = {
  costo: { Icon: Wrench, label: 'Costo', cls: 'bg-forest-50 text-forest border-forest-100' },
  combo: { Icon: Gift, label: 'Combo', cls: 'bg-gold-50 text-gold-700 border-gold-200' },
  addon: { Icon: Plus, label: 'Add-on', cls: 'bg-gold-50 text-gold-700 border-gold-200' },
  daypart: { Icon: Clock, label: 'Horario', cls: 'bg-warm-100 text-warm-600 border-warm-200' },
  precio: { Icon: ArrowUpRight, label: 'Precio', cls: 'bg-danger-50 text-danger-700 border-danger-200' },
}

export default function JugadasView({ jugadas, pulso, listo, onSimular }: {
  jugadas: Jugada[]
  pulso: PulsoData | null
  listo: boolean
  onSimular: (productoId: number) => void
}) {
  const attach = pulso?.attach
  return (
    <div className="space-y-3">
      <p className="text-xs text-warm-500 px-1">
        Ordenadas por la estrategia: primero <b className="text-warm-600">costo</b>, después combos y add-ons.
        Subir precio va al final y nunca toca el café del día a día.
      </p>

      {/* Línea base del attach (para medir si las jugadas funcionan) */}
      {attach && attach.tickets_con_bebida > 0 && (
        <div className="bg-white rounded-2xl border border-warm-200 p-3.5 flex items-center gap-4">
          <div className="flex-1">
            <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500">Línea base · attach real (30d)</p>
            <p className="text-xs text-warm-500 mt-0.5">De cada 100 tickets con bebida…</p>
          </div>
          <div className="text-center">
            <p className="text-lg font-mono font-bold text-warm-700 tabular-nums">{attach.pct_bebida_con_pasteleria ?? '—'}%</p>
            <p className="text-[10px] text-warm-400">+ pastelería</p>
          </div>
          <div className="text-center">
            <p className="text-lg font-mono font-bold text-warm-700 tabular-nums">{attach.pct_bebida_con_addon ?? '—'}%</p>
            <p className="text-[10px] text-warm-400">+ add-on</p>
          </div>
        </div>
      )}

      {jugadas.length === 0 && (
        <p className="text-sm text-warm-400 px-1">
          {listo ? 'Sin jugadas urgentes — todo en orden por ahora.' : 'Cargando datos…'}
        </p>
      )}

      {jugadas.map((j, i) => {
        const ui = TIPO_UI[j.tipo]
        return (
          <div key={j.id} className="bg-white rounded-2xl border border-warm-200 p-4">
            <div className="flex items-start gap-3">
              <span className="font-mono text-sm font-bold text-warm-400 mt-0.5 w-5 text-right shrink-0">{i + 1}</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-bold uppercase tracking-wide ${ui.cls}`}>
                    <ui.Icon size={10} /> {ui.label}
                  </span>
                  {j.riesgo && (
                    <span className="px-2 py-0.5 rounded-full bg-danger-50 border border-danger-200 text-danger-700 text-[10px] font-bold">
                      {j.riesgo}
                    </span>
                  )}
                </div>
                <p className="text-sm font-bold text-warm-700 mt-1.5 leading-snug">{j.titulo}</p>
                <p className="text-xs text-warm-500 mt-1 leading-relaxed">{j.detalle}</p>
                <div className="flex items-center justify-between gap-2 mt-2.5 pt-2.5 border-t border-warm-100">
                  <span className="text-xs font-mono font-bold text-success-600">{j.impacto}</span>
                  {j.simularProductoId != null && (
                    <button onClick={() => onSimular(j.simularProductoId as number)}
                      className="inline-flex items-center gap-1.5 min-h-[40px] px-3 rounded-lg bg-clay-500 text-white text-xs font-bold active:scale-[0.98] transition-transform">
                      <SlidersHorizontal size={13} /> Simular
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
