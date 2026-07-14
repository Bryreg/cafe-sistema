import { useEffect, useState } from 'react'
import { X, SlidersHorizontal } from 'lucide-react'
import { PorProductoData, fmt } from './helpers'

/** Bottom-sheet cost simulator: "how much do I gain by lowering the cost
 *  (renegotiating supplier / recipe / disposables) WITHOUT touching price". */
export default function SimuladorSheet({ prodData, productoId, onClose }: {
  prodData: PorProductoData | null
  productoId: number | null   // null = sheet closed
  onClose: () => void
}) {
  const [selId, setSelId] = useState<number | null>(null)
  const [reduccion, setReduccion] = useState(10)
  useEffect(() => { if (productoId != null) { setSelId(productoId); setReduccion(10) } }, [productoId])

  if (productoId == null || !prodData) return null

  const candidatos = prodData.productos
    .filter(p => p.unidades_30d > 0 && p.costo != null && p.costo > 0 && p.precio_venta > 0)
    .sort((a, b) => b.venta_30d - a.venta_30d)
  const prod = candidatos.find(p => p.producto_id === selId) ?? candidatos[0]
  if (!prod) return null

  const costoBase = prod.costo as number
  const costoNuevo = Math.round(costoBase * (1 - reduccion / 100))
  const ganancia = Math.round((costoBase - costoNuevo) * prod.unidades_30d)
  const margenNuevo = prod.precio_venta > 0 ? Math.round((1 - costoNuevo / prod.precio_venta) * 100) : 0

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label="Simulador de costo">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="absolute inset-x-0 bottom-0 bg-white rounded-t-2xl shadow-lg max-h-[85vh] overflow-y-auto overscroll-contain">
        <div className="sticky top-0 bg-white flex items-center gap-2 px-4 py-3 border-b border-warm-100">
          <SlidersHorizontal size={16} className="text-forest" />
          <p className="flex-1 text-sm font-bold text-warm-700">Simulador de costo</p>
          <button onClick={onClose} aria-label="Cerrar"
            className="p-3 -mr-1 rounded-lg text-warm-500 hover:bg-warm-50">
            <X size={18} />
          </button>
        </div>
        <div className="p-4 space-y-4 pb-8">
          <div>
            <label className="text-[11px] uppercase tracking-wide font-bold text-warm-500">Producto</label>
            <select value={prod.producto_id} onChange={e => setSelId(Number(e.target.value))}
              className="mt-1 w-full border border-warm-200 rounded-lg px-3 py-2.5 text-sm bg-white">
              {candidatos.slice(0, 60).map(p => (
                <option key={p.producto_id} value={p.producto_id}>
                  {p.nombre} — {p.pct_margen}% — {p.unidades_30d}u/mes
                </option>
              ))}
            </select>
          </div>
          <div>
            <div className="flex justify-between text-xs mb-1">
              <span className="text-warm-500 font-semibold">Bajar el costo</span>
              <span className="font-mono font-bold text-forest">−{reduccion}%</span>
            </div>
            <input type="range" min={0} max={30} step={1} value={reduccion}
              onChange={e => setReduccion(Number(e.target.value))}
              className="w-full accent-forest-500" />
            <p className="text-[11px] text-warm-400 mt-1">
              Renegociar el proveedor, ajustar la receta o reducir desechables — sin tocar el precio.
            </p>
          </div>
          <div className="rounded-xl border-l-[3px] border-success-500 bg-success-50 p-4 text-center">
            <p className="text-[11px] uppercase tracking-wide font-bold text-warm-500">Ganás / mes</p>
            <p className="text-[32px] font-mono font-extrabold text-success-600 leading-tight tabular-nums">
              +{fmt(ganancia)}
            </p>
            <p className="text-[11px] text-warm-500 mt-1.5 leading-relaxed">
              costo <span className="font-mono">{fmt(costoBase)}</span> → <span className="font-mono">{fmt(costoNuevo)}</span>
              {' · '}margen <span className="font-mono">{prod.pct_margen}%</span> → <span className="font-mono font-bold text-forest">{margenNuevo}%</span>
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
