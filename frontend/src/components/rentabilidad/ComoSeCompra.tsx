import { Link } from 'react-router-dom'
import { ArrowRight, Clock, Link2, Package } from 'lucide-react'
import { PulsoData, fmtK } from './helpers'

const rotuloHora = (h: number) => `${String(h).padStart(2, '0')}:00`

/**
 * «Cómo se compra acá» — tres datos que el backend ya calculaba y ninguna pantalla
 * mostraba, puestos donde SÍ terminan en una decisión:
 *
 *  - `top_pares` (qué se vende junto con qué) → la materia prima de un combo.
 *  - `attach` (qué proporción de las bebidas sale acompañada) → el termómetro que
 *    dice si ese combo hace falta.
 *  - `daypart` (a qué hora entra la plata) → a qué franja apuntarlo.
 *
 * POR QUÉ VIVEN EN CARTA Y NO EN PLATA·HOY. Estuvieron un rato al final de
 * Plata·Hoy y el diagnóstico fue correcto: eran contemplación. Tres bloques de
 * cifras bonitas sin un solo camino a una acción —ni a Carta, ni a Combos, ni a
 * cambiar un horario—, en la pantalla que el dueño abre para decidir el día.
 * Acá, al lado de la matriz de productos, cada uno cierra: el par frecuente y el
 * attach flojo se resuelven armando un combo, y la hora valle dice para cuándo.
 * Por eso todo el bloque termina en un link a Combos y no en un gráfico más.
 *
 * Todo sale del mismo `/rentabilidad/pulso` que Carta ya pedía: cero llamadas
 * nuevas.
 */
export default function ComoSeCompra({ pulso }: { pulso: PulsoData | null }) {
  const daypart = (pulso?.daypart ?? []).filter(d => d.tickets > 0)
  const attach = pulso?.attach
  const pares = (pulso?.top_pares ?? []).slice(0, 5)
  if (!daypart.length && !pares.length && !attach?.tickets_con_bebida) return null

  const maxVentas = Math.max(1, ...daypart.map(d => d.ventas))
  const totalDaypart = daypart.reduce((s, d) => s + d.ventas, 0)
  const pico = daypart.reduce<typeof daypart[number] | null>(
    (m, d) => (m == null || d.ventas > m.ventas ? d : m), null)
  const valle = daypart.reduce<typeof daypart[number] | null>(
    (m, d) => (m == null || d.ventas < m.ventas ? d : m), null)
  // El % de la venta que entra en la hora floja: sin él «la hora valle es 15:00»
  // es una curiosidad. Con él es el tamaño del agujero que un combo puede llenar.
  const pctValle = valle && totalDaypart > 0
    ? Math.round((valle.ventas / totalDaypart) * 100) : null
  const pctPico = pico && totalDaypart > 0
    ? Math.round((pico.ventas / totalDaypart) * 100) : null

  return (
    <div className="bg-white rounded-2xl border border-warm-200 overflow-hidden">
      <div className="px-4 py-3 border-b border-warm-100">
        <p className="text-sm font-bold text-warm-700">Cómo se compra acá</p>
        <p className="text-[11px] text-warm-500">
          Últimos 30 días, las dos sedes juntas. Es la materia prima de un combo: qué se lleva
          la gente junto y a qué hora falta venta.
        </p>
      </div>

      {/* ── A qué hora entra la plata ────────────────────────────────────────── */}
      {daypart.length > 1 && (
        <div className="px-4 py-3 border-b border-warm-100">
          <div className="flex items-center gap-1.5 mb-2">
            <Clock size={13} className="text-forest" />
            <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500">A qué hora entra la plata</p>
          </div>
          <div className="flex items-end gap-[3px] h-14" role="img"
            aria-label={`Ventas por hora. Pico ${pico ? rotuloHora(pico.hora) : '—'}, valle ${valle ? rotuloHora(valle.hora) : '—'}`}>
            {daypart.map(d => (
              <div key={d.hora} className="flex-1 flex flex-col justify-end h-full"
                title={`${rotuloHora(d.hora)} · ${fmtK(d.ventas)} · ${d.tickets} tickets`}>
                <div className="w-full rounded-t"
                  style={{
                    height: Math.max(3, Math.round((d.ventas / maxVentas) * 52)),
                    background: d.hora === pico?.hora ? '#5c7a4e'
                      : d.hora === valle?.hora ? '#d6bfa3' : '#a8bd9b',
                  }} />
              </div>
            ))}
          </div>
          <div className="flex items-center justify-between text-[10px] text-warm-400 mt-1">
            <span>{rotuloHora(daypart[0].hora)}</span>
            <span>{rotuloHora(daypart[daypart.length - 1].hora)}</span>
          </div>
          {valle && pico && pico.hora !== valle.hora && pctValle != null && (
            <p className="text-[11px] text-warm-500 mt-1.5 leading-relaxed">
              Tu hora floja es <b className="text-warm-700">{rotuloHora(valle.hora)}</b>: ahí entra el{' '}
              <b className="text-warm-700">{pctValle}%</b> de la venta del día
              {pctPico != null && <> — contra el <b className="text-warm-700">{pctPico}%</b> de las {rotuloHora(pico.hora)}</>}.
              Es la franja donde un combo o una promo mueven algo; en el pico solo regalás margen.
            </p>
          )}
        </div>
      )}

      {/* ── Cuánta bebida sale acompañada (el termómetro del upsell) ─────────── */}
      {attach && attach.tickets_con_bebida > 0 && (
        <div className="grid grid-cols-2 divide-x divide-warm-100 border-b border-warm-100">
          <div className="px-4 py-3">
            <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">Bebida + pastelería</p>
            <p className="text-lg font-bold font-mono text-warm-700 tabular-nums leading-tight mt-0.5">
              {attach.pct_bebida_con_pasteleria != null ? `${attach.pct_bebida_con_pasteleria}%` : '—'}
            </p>
            <p className="text-[10px] text-warm-400">de {attach.tickets_con_bebida} tickets con bebida</p>
          </div>
          <div className="px-4 py-3">
            <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">Bebida + porción</p>
            <p className="text-lg font-bold font-mono text-warm-700 tabular-nums leading-tight mt-0.5">
              {attach.pct_bebida_con_addon != null ? `${attach.pct_bebida_con_addon}%` : '—'}
            </p>
            <p className="text-[10px] text-warm-400">lo que deja el add-on de mostrador</p>
          </div>
        </div>
      )}

      {/* ── Qué se vende junto con qué (la materia prima de un combo) ────────── */}
      {pares.length > 0 && (
        <div className="px-4 py-3">
          <div className="flex items-center gap-1.5 mb-1.5">
            <Link2 size={13} className="text-forest" />
            <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500">Se venden juntos</p>
          </div>
          <div className="space-y-1">
            {pares.map(p => (
              <div key={`${p.a_id}-${p.b_id}`} className="flex items-center gap-2 text-xs">
                <span className="min-w-0 flex-1 truncate text-warm-600">{p.a} + {p.b}</span>
                <span className="shrink-0 font-mono font-bold text-warm-700 tabular-nums">{p.veces}</span>
              </div>
            ))}
          </div>
          <p className="text-[10px] text-warm-400 mt-1.5">
            Veces que aparecieron en el mismo ticket. Un par frecuente ya es un combo que la gente arma sola.
          </p>
        </div>
      )}

      {/* La salida. Sin esto el bloque entero vuelve a ser un gráfico lindo. */}
      <Link to="/combos"
        className="flex items-center gap-2 px-4 py-3 border-t border-warm-100 bg-forest-50/60">
        <Package size={15} className="text-forest shrink-0" />
        <span className="min-w-0 flex-1 text-[11px] text-forest leading-relaxed">
          <b>Armá el combo con el par de arriba.</b> El precio lo simulás desde «Simular costo»,
          en el encabezado de esta pantalla.
        </span>
        <ArrowRight size={14} className="text-forest shrink-0" />
      </Link>
    </div>
  )
}
