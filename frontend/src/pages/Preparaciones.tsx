import { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { FlaskConical, Check, Minus, Plus } from 'lucide-react'
import BaristaLayout from '../components/BaristaLayout'

interface Insumo { insumo_id: number; nombre: string; cantidad: number; unidad_medida: string }
interface Preparable {
  producto_id: number; nombre: string; unidad_medida: string
  rendimiento: number | null; stock_actual: number; insumos: Insumo[]
}

export default function Preparaciones() {
  const { user } = useAuth()
  const [preparables, setPreparables] = useState<Preparable[]>([])
  const [loading, setLoading] = useState(true)
  const [tandas, setTandas] = useState<Record<number, number>>({})
  const [enviando, setEnviando] = useState<number | null>(null)
  const [ok, setOk] = useState('')
  const [error, setError] = useState('')

  const cargar = () => {
    if (!user?.tienda_id) return
    api.get<Preparable[]>(`/inventario/preparables/${user.tienda_id}`)
      .then(r => setPreparables(r.data))
      .catch(() => setPreparables([]))
      .finally(() => setLoading(false))
  }
  useEffect(cargar, [user?.tienda_id])

  const registrar = async (p: Preparable) => {
    const n = tandas[p.producto_id] ?? 1
    setEnviando(p.producto_id); setError(''); setOk('')
    try {
      const r = await api.post('/inventario/preparaciones', {
        producto_id: p.producto_id, tienda_id: user?.tienda_id, cantidad: n,
      })
      setOk(`Listo: ${p.nombre} +${Math.round(r.data.producido)} ${p.unidad_medida}. Ya quedó descontada la materia prima.`)
      cargar()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'No se pudo registrar la preparación')
    } finally { setEnviando(null) }
  }

  return (
    <BaristaLayout title="Preparaciones">
    <div className="space-y-4">
      <div>
        <h1 className="text-base font-bold text-gray-800">Preparaciones</h1>
        <p className="text-xs text-gray-500 mt-0.5">
          Registrá acá cada vez que prepares una tanda (ej. mezcla de granizado).
          El sistema descuenta la materia prima y suma lo preparado.
        </p>
      </div>

      {ok && <div className="bg-green-50 border border-green-200 text-green-700 text-sm px-4 py-3 rounded-xl">{ok}</div>}
      {error && <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl">{error}</div>}

      {loading ? (
        <p className="text-sm text-gray-400 py-8 text-center">Cargando…</p>
      ) : preparables.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 px-4 py-10 text-center">
          <FlaskConical size={26} className="text-gray-300 mx-auto mb-2" />
          <p className="text-sm text-gray-500">No hay preparaciones configuradas</p>
        </div>
      ) : preparables.map(p => {
        const n = tandas[p.producto_id] ?? 1
        return (
          <div key={p.producto_id} className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <FlaskConical size={16} className="text-amber-600 shrink-0" />
                <p className="text-sm font-bold text-gray-800 truncate">{p.nombre}</p>
              </div>
              <span className="text-xs text-gray-400 shrink-0">
                hay {Math.round(p.stock_actual)} {p.unidad_medida}
              </span>
            </div>

            <div className="px-4 py-3 space-y-1">
              <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wide">Cada tanda usa</p>
              {p.insumos.map(i => (
                <div key={i.insumo_id} className="flex items-center justify-between text-xs">
                  <span className="text-gray-600">{i.nombre}</span>
                  <span className="font-mono font-semibold text-gray-800">
                    {Math.round(i.cantidad * n * 100) / 100} {i.unidad_medida}
                  </span>
                </div>
              ))}
              {p.rendimiento && (
                <div className="flex items-center justify-between text-xs pt-1 border-t border-gray-50">
                  <span className="text-gray-600 font-semibold">Produce</span>
                  <span className="font-mono font-bold text-green-700">
                    +{Math.round(p.rendimiento * n)} {p.unidad_medida}
                  </span>
                </div>
              )}
            </div>

            <div className="px-4 py-3 border-t border-gray-100 flex items-center gap-3">
              <div className="flex items-center gap-1 rounded-xl border-2 border-gray-200 px-1 py-0.5">
                <button onClick={() => setTandas(t => ({ ...t, [p.producto_id]: Math.max(0.5, n - 0.5) }))}
                  className="p-1.5 text-gray-500 hover:text-gray-800" aria-label="Menos"><Minus size={14} /></button>
                <span className="w-10 text-center text-sm font-bold font-mono">{n}</span>
                <button onClick={() => setTandas(t => ({ ...t, [p.producto_id]: n + 0.5 }))}
                  className="p-1.5 text-gray-500 hover:text-gray-800" aria-label="Más"><Plus size={14} /></button>
              </div>
              <span className="text-xs text-gray-400">tanda{n !== 1 ? 's' : ''}</span>
              <button onClick={() => registrar(p)} disabled={enviando === p.producto_id}
                className="ml-auto flex items-center gap-1.5 bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white text-sm font-bold px-4 py-2 rounded-xl">
                <Check size={15} /> {enviando === p.producto_id ? 'Registrando…' : 'Registrar'}
              </button>
            </div>
          </div>
        )
      })}
    </div>
    </BaristaLayout>
  )
}
