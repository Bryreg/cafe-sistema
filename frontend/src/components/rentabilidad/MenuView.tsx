import { useState } from 'react'
import { TrendingUp, TrendingDown, Layers } from 'lucide-react'
import {
  PorProductoData, PulsoData, ProdMargen, Quad,
  buildMatrix, prodUtil, fmt, fmtK,
} from './helpers'

const QUAD_UI: Record<Quad, { nombre: string; accion: string; dot: string; chipOn: string }> = {
  estrella: { nombre: 'Estrellas', accion: 'Proteger', dot: 'bg-success-500', chipOn: 'bg-success-500 text-white border-success-500' },
  caballo: { nombre: 'Caballos', accion: 'Bajar costo', dot: 'bg-gold-500', chipOn: 'bg-gold-600 text-white border-gold-600' },
  puzzle: { nombre: 'Puzzles', accion: 'Empujar', dot: 'bg-forest-400', chipOn: 'bg-forest text-white border-forest' },
  perro: { nombre: 'Perros', accion: 'Podar', dot: 'bg-danger-500', chipOn: 'bg-danger-500 text-white border-danger-500' },
}

function MargenBadge({ pct, incompleto }: { pct: number | null; incompleto?: boolean }) {
  if (pct == null) return <span className="text-warm-300">—</span>
  const cls = pct >= 60 ? 'bg-success-50 text-success-600 border-success-200'
    : pct >= 40 ? 'bg-gold-50 text-gold-700 border-gold-200'
    : 'bg-danger-50 text-danger-700 border-danger-200'
  return (
    <span title={incompleto ? 'costo incompleto — margen parcial' : undefined}
      className={`px-1.5 py-0.5 rounded-full border text-[11px] font-mono font-bold ${cls} ${incompleto ? 'border-dashed' : ''}`}>
      {pct}%{incompleto ? '*' : ''}
    </span>
  )
}

export default function MenuView({ prodData, pulso }: {
  prodData: PorProductoData | null
  pulso: PulsoData | null
}) {
  const [quad, setQuad] = useState<Quad>('caballo')
  const [cat, setCat] = useState('todas')
  const [sort, setSort] = useState<'utilidad' | 'margen' | 'unidades'>('utilidad')
  const [verTodos, setVerTodos] = useState(false)

  if (!prodData) return <p className="text-sm text-warm-400 px-1">Cargando…</p>
  const all = prodData.productos
  const matrix = buildMatrix(all)
  const enQuad = matrix.prods.filter(p => matrix.quadOf(p) === quad)
    .sort((a, b) => prodUtil(b) - prodUtil(a)).slice(0, 8)

  const movers = pulso?.top_movers

  // Utilidad por categoría.
  const catMap = new Map<string, number>()
  for (const p of all.filter(x => x.unidades_30d > 0 && x.margen != null)) {
    catMap.set(p.categoria || 'otros', (catMap.get(p.categoria || 'otros') ?? 0) + prodUtil(p))
  }
  const cats = [...catMap.entries()].sort((a, b) => b[1] - a[1])
  const maxCat = Math.max(1, ...cats.map(c => c[1]))

  // Tabla: por defecto SOLO vendidos (los de 0 unidades viven en el sheet Datos).
  const catChips = ['todas', ...Array.from(new Set(all.map(p => p.categoria).filter(Boolean)))]
  const filtered = all
    .filter(p => (verTodos || p.unidades_30d > 0))
    .filter(p => cat === 'todas' || p.categoria === cat)
  const sorted = [...filtered].sort((a, b) => {
    if (sort === 'unidades') return b.unidades_30d - a.unidades_30d
    if (sort === 'margen') return (b.pct_margen ?? -Infinity) - (a.pct_margen ?? -Infinity)
    return prodUtil(b) - prodUtil(a)
  })

  return (
    <div className="space-y-3">
      {/* Cuadrantes Kasavana-Smith, mobile-first: chips-filtro + lista */}
      <div className="bg-white rounded-2xl border border-warm-200 overflow-hidden">
        <p className="px-4 py-3 text-sm font-bold text-warm-700 border-b border-warm-100">
          Matriz de menú <span className="text-xs font-normal text-warm-400">· popularidad × rentabilidad</span>
        </p>
        <div className="flex gap-1.5 px-3 py-2.5 overflow-x-auto">
          {(Object.keys(QUAD_UI) as Quad[]).map(q => {
            const n = matrix.prods.filter(p => matrix.quadOf(p) === q).length
            const ui = QUAD_UI[q]
            return (
              <button key={q} onClick={() => setQuad(q)}
                className={`shrink-0 inline-flex items-center gap-1.5 min-h-[40px] px-3 rounded-full border text-xs font-bold transition-colors ${
                  quad === q ? ui.chipOn : 'bg-white text-warm-600 border-warm-200'}`}>
                <span className={`w-2 h-2 rounded-full ${quad === q ? 'bg-white/80' : ui.dot}`} />
                {ui.nombre} {n}
              </button>
            )
          })}
        </div>
        <p className="px-4 pb-1 text-[11px] text-warm-500">
          <b className="text-warm-600">{QUAD_UI[quad].nombre}</b> → acción: <b className="text-warm-600">{QUAD_UI[quad].accion}</b>
        </p>
        <div>
          {enQuad.map(p => (
            <div key={p.producto_id} className="flex items-center gap-2.5 px-4 py-2 border-b border-warm-100 last:border-0">
              <span className="flex-1 min-w-0 text-sm font-semibold text-warm-700 truncate">{p.nombre}</span>
              <span className="text-[11px] text-warm-400 shrink-0">{p.unidades_30d}u</span>
              <MargenBadge pct={p.pct_margen} incompleto={!p.costo_completo} />
              <span className="w-16 text-right text-xs font-mono font-bold text-warm-600 shrink-0">{fmtK(prodUtil(p))}</span>
            </div>
          ))}
          {enQuad.length === 0 && <p className="px-4 py-3 text-sm text-warm-400">Nada en este cuadrante.</p>}
        </div>
      </div>

      {/* Top movers: qué subió y qué cayó vs los 30 días anteriores */}
      {movers && (movers.subiendo.length > 0 || movers.bajando.length > 0) && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="bg-white rounded-2xl border border-warm-200 overflow-hidden">
            <p className="px-4 py-2.5 text-xs font-bold text-success-600 border-b border-warm-100 flex items-center gap-1.5">
              <TrendingUp size={13} /> SUBIENDO vs 30d anteriores
            </p>
            {movers.subiendo.map(m => (
              <div key={m.producto_id} className="flex items-center gap-2 px-4 py-1.5 border-b border-warm-100 last:border-0">
                <span className="flex-1 min-w-0 text-sm text-warm-700 truncate">{m.nombre}</span>
                <span className="text-[11px] text-warm-400">{m.unidades_prev}→{m.unidades}u</span>
                <span className="text-xs font-mono font-bold text-success-600 w-16 text-right">+{fmtK(m.delta_venta)}</span>
              </div>
            ))}
            {movers.subiendo.length === 0 && <p className="px-4 py-2.5 text-xs text-warm-400">Sin subas relevantes.</p>}
          </div>
          <div className="bg-white rounded-2xl border border-warm-200 overflow-hidden">
            <p className="px-4 py-2.5 text-xs font-bold text-danger-700 border-b border-warm-100 flex items-center gap-1.5">
              <TrendingDown size={13} /> CAYENDO vs 30d anteriores
            </p>
            {movers.bajando.map(m => (
              <div key={m.producto_id} className="flex items-center gap-2 px-4 py-1.5 border-b border-warm-100 last:border-0">
                <span className="flex-1 min-w-0 text-sm text-warm-700 truncate">{m.nombre}</span>
                <span className="text-[11px] text-warm-400">{m.unidades_prev}→{m.unidades}u</span>
                <span className="text-xs font-mono font-bold text-danger-500 w-16 text-right">{fmtK(m.delta_venta)}</span>
              </div>
            ))}
            {movers.bajando.length === 0 && <p className="px-4 py-2.5 text-xs text-warm-400">Sin caídas relevantes.</p>}
          </div>
        </div>
      )}

      {/* Utilidad por categoría */}
      {cats.length > 0 && (
        <div className="bg-white rounded-2xl border border-warm-200 p-4">
          <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500 mb-2 flex items-center gap-1.5">
            <Layers size={12} /> Utilidad por categoría · 30d
          </p>
          <div className="space-y-2">
            {cats.map(([c, v]) => (
              <div key={c} className="flex items-center gap-3">
                <span className="w-24 text-sm font-semibold text-warm-700 capitalize truncate">{c}</span>
                <div className="flex-1 h-3.5 rounded-full bg-warm-100 overflow-hidden">
                  <div className="h-full rounded-full bg-forest-400" style={{ width: `${Math.max(3, (v / maxCat) * 100)}%` }} />
                </div>
                <span className="w-16 text-right text-xs font-mono font-bold text-warm-600">{fmtK(v)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Detalle por producto */}
      <div className="bg-white rounded-2xl border border-warm-200 overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 px-4 py-3 border-b border-warm-100">
          <p className="text-sm font-bold text-warm-700">Detalle por producto</p>
          <label className="ml-auto flex items-center gap-1.5 text-[11px] text-warm-500 font-semibold">
            <input type="checkbox" checked={verTodos} onChange={e => setVerTodos(e.target.checked)}
              className="accent-forest-500" />
            incluir sin ventas
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 px-3 py-2 border-b border-warm-100 bg-warm-50">
          {catChips.map(c => (
            <button key={c} onClick={() => setCat(c)}
              className={`min-h-[36px] px-2.5 rounded-full text-[11px] font-bold capitalize border transition-colors ${
                cat === c ? 'bg-forest text-white border-forest' : 'bg-white text-warm-500 border-warm-200'}`}>
              {c}
            </button>
          ))}
          <div className="ml-auto flex items-center gap-1">
            {(([['utilidad', 'Utilidad'], ['margen', '%'], ['unidades', 'Vendidos']]) as [typeof sort, string][]).map(([s, lbl]) => (
              <button key={s} onClick={() => setSort(s)}
                className={`min-h-[36px] px-2.5 rounded-full text-[11px] font-bold border transition-colors ${
                  sort === s ? 'bg-warm-700 text-white border-warm-700' : 'bg-white text-warm-500 border-warm-200'}`}>
                {lbl}
              </button>
            ))}
          </div>
        </div>

        {/* Mobile: cards · Desktop: tabla */}
        <div className="sm:hidden">
          {sorted.slice(0, 60).map(p => (
            <div key={p.producto_id} className="px-4 py-2.5 border-b border-warm-100 last:border-0">
              <div className="flex items-center gap-2">
                <span className="flex-1 min-w-0 text-sm font-semibold text-warm-700 truncate">{p.nombre}</span>
                <MargenBadge pct={p.pct_margen} incompleto={!p.costo_completo} />
              </div>
              <div className="flex items-center gap-3 mt-1 text-[11px] text-warm-500 font-mono tabular-nums">
                <span>{p.unidades_30d}u</span>
                <span>{fmt(p.precio_venta)}</span>
                <span>costo {p.costo != null ? fmt(p.costo) : '—'}</span>
                <span className="ml-auto font-bold text-warm-600">{p.margen != null && p.unidades_30d > 0 ? fmtK(prodUtil(p)) : '—'}</span>
              </div>
              {!p.costo_completo && p.insumos_sin_costo.length > 0 && (
                <p className="text-[10px] text-gold-700 mt-0.5">falta costo: {p.insumos_sin_costo.slice(0, 2).join(', ')}</p>
              )}
            </div>
          ))}
        </div>
        <div className="hidden sm:block overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[11px] uppercase tracking-wide text-warm-400 border-b border-warm-100">
                <th className="text-left px-4 py-2 font-bold">Producto</th>
                <th className="text-right px-3 py-2 font-bold">Vend 30d</th>
                <th className="text-right px-3 py-2 font-bold">Precio</th>
                <th className="text-right px-3 py-2 font-bold">Costo</th>
                <th className="text-right px-3 py-2 font-bold">Margen</th>
                <th className="text-right px-4 py-2 font-bold">Utilidad 30d</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map(p => {
                const hayDesech = p.costo_con_desechables != null && p.costo != null && p.costo_con_desechables !== p.costo
                return (
                  <tr key={p.producto_id} className="border-b border-warm-100 last:border-0">
                    <td className="px-4 py-2">
                      <p className="font-semibold text-warm-700">{p.nombre}</p>
                      {!p.costo_completo && p.insumos_sin_costo.length > 0 && (
                        <p className="text-[11px] text-gold-700">falta costo de: {p.insumos_sin_costo.slice(0, 3).join(', ')}</p>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-warm-500 tabular-nums">{p.unidades_30d > 0 ? p.unidades_30d : '—'}</td>
                    <td className="px-3 py-2 text-right font-mono text-warm-700 tabular-nums">{fmt(p.precio_venta)}</td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums">
                      <span className={p.costo_completo ? 'text-warm-500' : 'text-gold-700'}>
                        {p.costo != null ? `${p.costo_completo ? '' : '≥ '}${fmt(p.costo)}` : '—'}
                      </span>
                      {hayDesech && <span className="block text-[11px] text-clay-600">p/llevar {fmt(p.costo_con_desechables!)}</span>}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <MargenBadge pct={p.pct_margen} incompleto={!p.costo_completo} />
                      {hayDesech && p.pct_margen_con_desechables != null && (
                        <span className="block text-[11px] text-clay-600 font-mono">llevar {p.pct_margen_con_desechables}%</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right font-mono font-bold text-warm-700 tabular-nums">
                      {p.unidades_30d > 0 && p.margen != null ? fmt(prodUtil(p)) : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <p className="px-4 py-2 text-[11px] text-warm-400 border-t border-warm-100">
          Utilidad 30d = margen × unidades: lo que el producto APORTA al mes. "p/llevar" suma los desechables.
          Ventana: últimos 30 días, ambas sedes.
        </p>
      </div>
    </div>
  )
}
