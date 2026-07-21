import { useEffect, useState } from 'react'
import { X, Link2, AlertTriangle } from 'lucide-react'
import api from '../../api/client'

interface Par { producto_id: number; nombre: string; categoria: string; veces: number; pct: number }
export interface AttachData {
  producto: { id: number; nombre: string; categoria: string }
  dias: number
  tickets: number
  unidades: number
  tickets_multiples: number
  con_bebida: number
  pct_con_bebida: number | null
  sin_bebida: number
  por_categoria: Record<string, number>
  pares: Par[]
}

/** Con qué se vende junto un producto, medido ticket por ticket.
 *  Responde lo que el top-12 del Pulso no puede: el número exacto de UN par
 *  concreto, que es lo que hace falta para decidir o medir un combo. */
export default function AttachSheet({ productoId, onClose }: {
  productoId: number | null   // null = cerrado
  onClose: () => void
}) {
  const [data, setData] = useState<AttachData | null>(null)
  const [cargando, setCargando] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (productoId == null) { setData(null); setError(''); return }
    setCargando(true); setError(''); setData(null)
    api.get<AttachData>(`/rentabilidad/attach/${productoId}`)
      .then(r => setData(r.data))
      .catch(() => setError('No se pudo cargar el attach de este producto'))
      .finally(() => setCargando(false))
  }, [productoId])

  if (productoId == null) return null

  const maxPar = Math.max(1, ...(data?.pares ?? []).map(p => p.veces))
  // Llevarse 2+ del mismo producto es la señal que delata a un combo que empaqueta
  // de a dos algo que la gente YA compra de a dos (canibalización pura).
  const pctMultiples = data && data.tickets > 0
    ? Math.round((data.tickets_multiples / data.tickets) * 100) : 0
  const alertaDeADos = !!data && data.tickets_multiples >= 10 && pctMultiples >= 15

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label="Con qué se vende junto">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="absolute inset-x-0 bottom-0 bg-white rounded-t-2xl shadow-lg max-h-[85vh] overflow-y-auto overscroll-contain">
        <div className="sticky top-0 bg-white flex items-center gap-2 px-4 py-3 border-b border-warm-100">
          <Link2 size={16} className="text-forest" />
          <p className="flex-1 text-sm font-bold text-warm-700">
            Con qué se vende junto
            {data && <span className="block text-[11px] font-medium text-warm-400">{data.producto.nombre}</span>}
          </p>
          <button onClick={onClose} aria-label="Cerrar"
            className="p-3 -mr-1 rounded-lg text-warm-500 hover:bg-warm-50">
            <X size={18} />
          </button>
        </div>

        <div className="p-4 space-y-4 pb-8">
          {cargando && <p className="text-sm text-warm-400 py-8 text-center">Cargando…</p>}
          {error && (
            <div className="bg-danger-50 border border-danger-200 text-danger-700 text-sm px-4 py-3 rounded-xl">{error}</div>
          )}

          {data && data.tickets === 0 && !cargando && (
            <p className="text-sm text-warm-400 py-8 text-center">
              Sin ventas de este producto en los últimos {data.dias} días.
            </p>
          )}

          {data && data.tickets > 0 && (
            <>
              <div className="grid grid-cols-3 gap-2">
                <div className="bg-warm-50 rounded-xl px-3 py-2.5">
                  <p className="text-[10px] uppercase tracking-wide font-bold text-warm-400">Tickets</p>
                  <p className="text-lg font-bold font-mono tabular-nums text-warm-700">{data.tickets}</p>
                  <p className="text-[10px] text-warm-400">{data.unidades} unidades</p>
                </div>
                <div className="bg-warm-50 rounded-xl px-3 py-2.5">
                  <p className="text-[10px] uppercase tracking-wide font-bold text-warm-400">Con bebida</p>
                  <p className="text-lg font-bold font-mono tabular-nums text-success-600">
                    {data.pct_con_bebida != null ? `${data.pct_con_bebida}%` : '—'}
                  </p>
                  <p className="text-[10px] text-warm-400">{data.con_bebida} de {data.tickets}</p>
                </div>
                <div className="bg-warm-50 rounded-xl px-3 py-2.5">
                  <p className="text-[10px] uppercase tracking-wide font-bold text-warm-400">Se lleva 2+</p>
                  <p className={`text-lg font-bold font-mono tabular-nums ${alertaDeADos ? 'text-clay-600' : 'text-warm-700'}`}>
                    {data.tickets_multiples}
                  </p>
                  <p className="text-[10px] text-warm-400">{pctMultiples}% de los tickets</p>
                </div>
              </div>

              {alertaDeADos && (
                <div className="flex gap-2 bg-clay-50 border border-clay-200 rounded-xl px-3 py-2.5">
                  <AlertTriangle size={15} className="text-clay-600 shrink-0 mt-0.5" />
                  <p className="text-[12px] text-warm-700 leading-relaxed">
                    <span className="font-bold">Ojo con los combos de a dos.</span> En {data.tickets_multiples} tickets
                    el cliente ya se lleva 2 o más. Un combo que los empaquete con descuento le baja el margen a
                    una venta que <span className="font-semibold">ya tenías</span>.
                  </p>
                </div>
              )}

              {Object.keys(data.por_categoria).length > 0 && (
                <div>
                  <p className="text-[11px] uppercase tracking-wide font-bold text-warm-500 mb-1.5">Sale acompañado de</p>
                  <div className="flex flex-wrap gap-1.5">
                    {Object.entries(data.por_categoria).map(([cat, n]) => (
                      <span key={cat} className="text-[11px] bg-forest-50 text-forest-700 border border-forest-100 rounded-lg px-2 py-1">
                        {cat} <span className="font-mono font-bold tabular-nums">{n}</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div>
                <p className="text-[11px] uppercase tracking-wide font-bold text-warm-500 mb-1.5">
                  Pares exactos ({data.pares.length})
                </p>
                {data.pares.length === 0 ? (
                  <p className="text-sm text-warm-400">Siempre se vende solo.</p>
                ) : (
                  <div className="space-y-1">
                    {data.pares.slice(0, 25).map(par => (
                      <div key={par.producto_id} className="flex items-center gap-2">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-baseline justify-between gap-2">
                            <p className="text-[12px] text-warm-700 truncate">{par.nombre}</p>
                            <p className="text-[12px] font-mono font-bold tabular-nums text-warm-700 shrink-0">
                              {par.veces} <span className="text-warm-400 font-normal">· {par.pct}%</span>
                            </p>
                          </div>
                          <div className="h-1.5 bg-warm-100 rounded-full overflow-hidden mt-0.5">
                            <div className="h-full bg-forest-400 rounded-full"
                              style={{ width: `${Math.round((par.veces / maxPar) * 100)}%` }} />
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <p className="text-[11px] text-warm-400 leading-relaxed">
                Contado ticket por ticket sobre los últimos {data.dias} días, ambas sedes, sin truncar.
                Es el dato que hace falta para decidir un combo: cuántos clientes YA compran esa
                combinación a precio lleno.
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
