import { useRef, useState } from 'react'
import { X, ShieldAlert, ScanLine, Loader2, Trash2 } from 'lucide-react'
import api from '../../api/client'
import {
  PorProductoData, RentabilidadData,
  computeOutliers, computeInsumosSinCosto, fmt,
} from './helpers'

// Fila de GET /rentabilidad/aliases (administración mínima de la Fase 2).
interface AliasRow {
  id: number
  alias_original: string
  producto_nombre: string
  origen: string
  veces_visto: number
  actualizado_en: string | null
  barista_nombre: string | null
}

/** Bottom-sheet "Salud de datos": todo el mantenimiento de la calidad del
 *  costeo en un solo lugar — cobertura, márgenes atípicos, insumos sin costo,
 *  backfill OCR y metodología. Un margen falso lleva a decisiones falsas. */
export default function DatosSheet({ open, prodData, plMes, onClose, onRefresh }: {
  open: boolean
  prodData: PorProductoData | null
  plMes: RentabilidadData | null
  onClose: () => void
  onRefresh: () => void
}) {
  const [leyendo, setLeyendo] = useState(false)
  const [msg, setMsg] = useState('')
  const pararRef = useRef(false)

  // Aliases aprendidos (Fase 2): lista simple con borrar — un alias malo se
  // auto-refuerza en silencio con cada escaneo si no se puede eliminar.
  const [verAliases, setVerAliases] = useState(false)
  const [aliases, setAliases] = useState<AliasRow[] | null>(null)
  const [aliasMsg, setAliasMsg] = useState('')

  if (!open) return null

  const all = prodData?.productos ?? []
  const outliers = computeOutliers(all)
  const insumos = computeInsumosSinCosto(all)
  const completos = all.filter(p => p.costo_completo).length
  const cobertura = all.length ? Math.round((completos / all.length) * 100) : 0
  const pendientes = prodData?.facturas_pendientes_de_costos ?? 0

  const toggleAliases = async () => {
    const abrir = !verAliases
    setVerAliases(abrir)
    if (abrir && aliases === null) {
      try {
        const r = await api.get<AliasRow[]>('/rentabilidad/aliases')
        setAliases(r.data)
        setAliasMsg('')
      } catch (e: any) {
        setAliasMsg(e.response?.data?.detail || 'No se pudieron cargar los aliases.')
      }
    }
  }

  const borrarAlias = async (id: number) => {
    try {
      await api.delete(`/rentabilidad/aliases/${id}`)
      setAliases(a => (a ?? []).filter(x => x.id !== id))
    } catch (e: any) {
      setAliasMsg(e.response?.data?.detail || 'No se pudo eliminar el alias.')
    }
  }

  const leerFacturas = async () => {
    if (!prodData) return
    setLeyendo(true)
    pararRef.current = false
    let quedan = prodData.facturas_pendientes_de_costos
    try {
      while (quedan > 0 && !pararRef.current) {
        setMsg(`Leyendo facturas guardadas… quedan ${quedan}`)
        const r = await api.post('/rentabilidad/backfill-costos?limite=2', null, { timeout: 300000 })
        const d = r.data
        if (d.detenido_por) { setMsg(d.detenido_por); break }
        quedan = d.pendientes
        if (d.procesadas === 0) {
          if (quedan > 0) setMsg(`Quedan ${quedan} que no se pudieron leer solas — completá esos precios a mano en Pagos proveedores.`)
          break
        }
      }
      if (quedan === 0) setMsg('Listo: todas las facturas con foto quedaron leídas.')
    } catch (e: any) {
      setMsg(e.response?.data?.detail || 'Error leyendo facturas — intentá más tarde.')
    } finally {
      setLeyendo(false)
      onRefresh()
    }
  }

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label="Salud de datos">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="absolute inset-x-0 bottom-0 bg-white rounded-t-2xl shadow-lg max-h-[88vh] overflow-y-auto overscroll-contain">
        <div className="sticky top-0 bg-white flex items-center gap-2 px-4 py-3 border-b border-warm-100 z-10">
          <ShieldAlert size={16} className="text-gold-600" />
          <p className="flex-1 text-sm font-bold text-warm-700">Salud de datos</p>
          <button onClick={onClose} aria-label="Cerrar"
            className="p-3 -mr-1 rounded-lg text-warm-500 hover:bg-warm-50">
            <X size={18} />
          </button>
        </div>

        <div className="p-4 space-y-4 pb-8">
          {/* Cobertura de costeo */}
          <div className="rounded-xl border border-warm-200 p-4">
            <div className="flex items-baseline justify-between">
              <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500">Cobertura de costeo</p>
              <p className="text-lg font-mono font-extrabold text-warm-700 tabular-nums">{completos}/{all.length}</p>
            </div>
            <div className="h-2.5 rounded-full bg-warm-100 overflow-hidden mt-2">
              <div className={`h-full rounded-full ${cobertura >= 90 ? 'bg-success-500' : 'bg-gold-500'}`}
                style={{ width: `${cobertura}%` }} />
            </div>
            <p className="text-[11px] text-warm-400 mt-1.5">
              {cobertura}% de los productos con costo completo. Un producto sin costo tiene margen falso.
            </p>
            {typeof prodData?.aliases_conocidos === 'number' && (() => {
              const n = aliases !== null ? aliases.length : prodData.aliases_conocidos
              return (
                <div className="mt-1">
                  <p className="text-[11px] text-warm-400">
                    El sistema conoce {n} {n === 1 ? 'alias' : 'aliases'} de
                    proveedores — aprende con cada factura escaneada, corregida o leída.{' '}
                    {n > 0 && (
                      <button onClick={toggleAliases}
                        className="font-bold text-gold-700 underline decoration-dotted">
                        {verAliases ? 'ocultar' : 'ver y gestionar'}
                      </button>
                    )}
                  </p>
                  {verAliases && (
                    <div className="mt-2 rounded-lg border border-warm-100 divide-y divide-warm-100 max-h-56 overflow-y-auto">
                      {aliases === null ? (
                        <p className="text-[11px] text-warm-400 px-2.5 py-2">Cargando…</p>
                      ) : aliases.length === 0 ? (
                        <p className="text-[11px] text-warm-400 px-2.5 py-2">No queda ningún alias.</p>
                      ) : aliases.map(a => (
                        <div key={a.id} className="flex items-center gap-2 px-2.5 py-2">
                          <div className="flex-1 min-w-0">
                            <p className="text-[12px] text-warm-700 truncate">
                              <span className="font-mono">{a.alias_original}</span>
                              <span className="text-warm-400"> → </span>
                              <span className="font-semibold">{a.producto_nombre}</span>
                            </p>
                            <p className="text-[10px] text-warm-400">
                              {a.origen} · visto {a.veces_visto} {a.veces_visto === 1 ? 'vez' : 'veces'}
                              {a.barista_nombre ? ` · enseñó ${a.barista_nombre}` : ''}
                              {a.actualizado_en ? ` · ${String(a.actualizado_en).slice(0, 10)}` : ''}
                            </p>
                          </div>
                          <button onClick={() => borrarAlias(a.id)} aria-label={`Eliminar alias ${a.alias_original}`}
                            className="p-2 rounded-md text-warm-300 hover:text-danger-500 hover:bg-danger-50 shrink-0">
                            <Trash2 size={13} />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                  {aliasMsg && <p className="text-[11px] text-danger-500 mt-1">{aliasMsg}</p>}
                </div>
              )
            })()}
          </div>

          {/* Backfill OCR */}
          {pendientes > 0 && (
            <div className="rounded-xl border-l-[3px] border-clay-500 border border-warm-200 bg-clay-50 p-4">
              <p className="text-sm font-bold text-warm-700">{pendientes} facturas guardadas sin leer</p>
              <p className="text-xs text-warm-500 mt-0.5">Leerlas completa costos automáticamente desde las fotos.</p>
              <div className="flex items-center gap-2 mt-2.5">
                {leyendo ? (
                  <>
                    <span className="flex items-center gap-1.5 text-xs font-semibold text-gold-700">
                      <Loader2 size={13} className="animate-spin" /> {msg}
                    </span>
                    <button onClick={() => { pararRef.current = true }}
                      className="ml-auto min-h-[40px] px-3 rounded-lg text-xs font-bold border border-warm-200 text-warm-500 bg-white">
                      Parar
                    </button>
                  </>
                ) : (
                  <button onClick={leerFacturas}
                    className="flex items-center gap-1.5 min-h-[44px] px-4 rounded-lg text-xs font-bold text-white bg-clay-500 active:scale-[0.98] transition-transform">
                    <ScanLine size={14} /> Leer costos de {pendientes} facturas
                  </button>
                )}
              </div>
              {!leyendo && msg && <p className="text-[11px] text-warm-500 mt-2">{msg}</p>}
            </div>
          )}

          {/* Márgenes sospechosos */}
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500 mb-1.5">Márgenes sospechosos</p>
            {outliers.length === 0 ? (
              <p className="text-sm text-success-600 font-semibold">Ninguno — todos coherentes con su categoría ✓</p>
            ) : outliers.map(o => (
              <div key={o.p.producto_id} className="flex items-center gap-2 py-2 border-b border-warm-100 last:border-0">
                <span className="flex-1 min-w-0 text-sm text-warm-700 truncate">{o.p.nombre}</span>
                <span className={`text-xs font-mono font-bold ${o.alto ? 'text-danger-500' : 'text-gold-700'}`}>{o.p.pct_margen}%</span>
                <span className="text-[11px] text-warm-400 w-24 text-right capitalize truncate">{o.p.categoria} ~{o.mean}%</span>
              </div>
            ))}
            <p className="text-[11px] text-warm-400 mt-1.5">
              Un margen muy desviado del promedio de su categoría suele ser un costo mal cargado
              (así se cazó el helado de las malteadas y los omelettes).
            </p>
          </div>

          {/* Insumos sin costear */}
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500 mb-1.5">Insumos sin costear</p>
            {insumos.length === 0 ? (
              <p className="text-sm text-success-600 font-semibold">Todo costeado ✓</p>
            ) : insumos.map(i => (
              <div key={i.nombre} className="flex items-center gap-2 py-2 border-b border-warm-100 last:border-0">
                <span className="flex-1 min-w-0 text-sm text-warm-700 truncate">{i.nombre}</span>
                <span className="text-[11px] text-warm-400 shrink-0">{i.n} prod</span>
                <span className="text-xs font-mono text-gold-700 w-20 text-right shrink-0 tabular-nums">{fmt(i.venta)}</span>
              </div>
            ))}
          </div>

          {/* Metodología */}
          <details className="rounded-xl border border-warm-200 p-4">
            <summary className="text-sm font-bold text-warm-700 cursor-pointer select-none">¿Cómo se calcula esto?</summary>
            <div className="text-xs text-warm-500 leading-relaxed mt-2 space-y-2">
              {plMes?.nota && <p>{plMes.nota}</p>}
              {prodData?.nota && <p>{prodData.nota}</p>}
              <p>
                El "margen operativo de caja" NO incluye nómina, arriendo ni servicios — no es la utilidad real.
                El costo de lo vendido (COGS teórico) usa las recetas y costos confirmados, y complementa a
                "Compras", que va por recepción (un mes que stockea fuerte se ve peor de lo que fue).
              </p>
            </div>
          </details>
        </div>
      </div>
    </div>
  )
}
