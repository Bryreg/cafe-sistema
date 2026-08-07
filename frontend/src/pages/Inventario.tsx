import { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { Plus, Minus, X, RefreshCw, AlertTriangle, Search } from 'lucide-react'
import BaristaLayout from '../components/BaristaLayout'
import { useEmbedded } from '../contexts/PanelContext'

// ─── Tipos ────────────────────────────────────────────────────────────────────

interface InvItem {
  id: number; producto_id: number; producto_nombre: string; categoria: string
  unidad_medida: string; stock_actual: number; stock_minimo: number; alerta: boolean
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function stockColor(item: InvItem) {
  if (item.stock_actual === 0) return { bg: 'bg-red-100', border: 'border-red-300', text: 'text-red-700', dot: 'bg-red-500' }
  if (item.alerta) return { bg: 'bg-amber-50', border: 'border-amber-200', text: 'text-amber-700', dot: 'bg-amber-400' }
  return { bg: 'bg-white', border: 'border-gray-200', text: 'text-gray-700', dot: 'bg-green-400' }
}

// ─── Vista barista ────────────────────────────────────────────────────────────

function InventarioBarista() {
  const { user } = useAuth()
  const embedded = useEmbedded()
  const [items, setItems] = useState<InvItem[]>([])
  const [busqueda, setBusqueda] = useState('')
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<InvItem | null>(null)
  const [tipo, setTipo] = useState<'entrada' | 'salida' | 'ajuste'>('entrada')
  const [cantidad, setCantidad] = useState('')
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const load = async () => {
    if (!user?.tienda_id) return
    try {
      const { data } = await api.get(`/inventario/tienda/${user.tienda_id}`)
      setItems(data)
    } finally { setLoading(false) }
  }

  const POLL_MS = 30_000

  useEffect(() => {
    load()
    const id = setInterval(load, POLL_MS)
    return () => clearInterval(id)
  }, [user])

  const registrar = async () => {
    if (!selected || !user?.tienda_id) return
    setError(''); setSaving(true)
    try {
      await api.post('/inventario/movimiento', {
        producto_id: selected.producto_id, tienda_id: user.tienda_id,
        tipo, cantidad: Number(cantidad), motivo: motivo || null,
      })
      setCantidad(''); setMotivo(''); setSelected(null)
      load()
    } catch (e: any) {
      const raw = e.response?.data?.detail
      const detail = Array.isArray(raw) ? (raw[0]?.msg ?? 'Error de validación') : (raw || '')
      const isInsuficiente = e.response?.status === 400 && typeof detail === 'string' && detail.toLowerCase().includes('insuficiente')
      setError(isInsuficiente
        ? 'Stock insuficiente. Los datos se actualizaron — verificá el stock actual.'
        : detail || (e.message ? `Error: ${e.message}` : 'Error al conectar con el servidor'))
    } finally { setSaving(false) }
  }

  const criticos = items.filter(i => i.stock_actual === 0)
  const bajos = items.filter(i => i.alerta && i.stock_actual > 0)

  if (loading) return (
    <BaristaLayout title="Inventario">
      <div className="flex justify-center py-16"><p className="text-sm text-gray-400">Cargando...</p></div>
    </BaristaLayout>
  )

  return (
    <BaristaLayout title="Inventario">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            {criticos.length > 0 && <p className="text-xs text-red-600 font-semibold">{criticos.length} sin stock</p>}
            {bajos.length > 0 && <p className="text-xs text-amber-600 font-semibold">{bajos.length} stock bajo</p>}
          </div>
          <button onClick={load} className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors">
            <RefreshCw size={15} />
          </button>
        </div>

        {selected && (
          <div className={`${embedded ? 'absolute' : 'fixed'} inset-0 bg-black/50 z-50 flex items-end justify-center`}>
            <div className="bg-white w-full max-w-md rounded-t-3xl p-6 space-y-4">
              <div className="flex items-center justify-between">
                <p className="text-base font-bold text-gray-800">{selected.producto_nombre}</p>
                <button onClick={() => setSelected(null)} className="text-gray-400 hover:text-gray-600">
                  <X size={20} />
                </button>
              </div>
              <p className="text-sm text-gray-500">Stock actual: <strong>{Math.round(selected.stock_actual)} {selected.unidad_medida}</strong></p>
              {error && (
                <div className="flex items-center gap-2 text-red-600 text-sm bg-red-50 px-3 py-2 rounded-xl">
                  <AlertTriangle size={14} /> {error}
                </div>
              )}
              {/* Ajuste es SOLO admin: las baristas registran hechos (entrada/salida);
                  las correcciones de stock van por el administrador o verificación. */}
              <div className="flex gap-2">
                {(['entrada', 'salida'] as const).map(t => (
                  <button key={t} onClick={() => { setTipo(t); setError('') }}
                    className={`flex-1 py-2.5 rounded-xl text-sm font-semibold border-2 transition-colors ${
                      tipo === t
                        ? t === 'entrada' ? 'bg-green-100 border-green-400 text-green-700'
                          : 'bg-red-100 border-red-400 text-red-700'
                        : 'border-gray-200 text-gray-400'
                    }`}>{t}</button>
                ))}
              </div>
              <input type="number" step="1" min="0" value={cantidad} onChange={e => setCantidad(e.target.value)}
                placeholder={tipo === 'ajuste'
                  ? `Stock final (${selected.unidad_medida}) — reemplaza el actual`
                  : `Cantidad (${selected.unidad_medida})`}
                className="w-full border-2 border-gray-200 rounded-xl px-4 py-3 text-lg font-bold focus:outline-none focus:border-amber-400"
                autoFocus />
              {tipo === 'ajuste' && (
                <p className="text-xs text-blue-600 -mt-1">El ajuste FIJA el stock a este valor (no suma ni resta).</p>
              )}
              <input value={motivo} onChange={e => setMotivo(e.target.value)} placeholder="Motivo (opcional)"
                className="w-full border-2 border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-amber-400" />
              <button onClick={registrar} disabled={!cantidad || saving}
                className="w-full bg-amber-600 hover:bg-amber-700 disabled:opacity-40 text-white font-bold py-3.5 rounded-xl text-sm transition-colors">
                {saving ? 'Guardando...' : 'Confirmar'}
              </button>
            </div>
          </div>
        )}

        <div className="relative">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            value={busqueda}
            onChange={e => setBusqueda(e.target.value)}
            placeholder="Buscar producto…"
            className="w-full pl-9 pr-3 py-2.5 border-2 border-gray-200 rounded-xl text-sm focus:outline-none focus:border-amber-400"
          />
        </div>

        <div className="space-y-2">
          {items
            .filter(i => i.producto_nombre.toLowerCase().includes(busqueda.toLowerCase()))
            .map(item => {
            const c = stockColor(item)
            return (
              <div key={item.id}
                className={`flex items-center gap-3 px-4 py-3.5 rounded-2xl border-2 ${c.bg} ${c.border} transition-all`}>
                <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${c.dot}`} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-gray-800 leading-tight">{item.producto_nombre}</p>
                  <p className="text-xs text-gray-400">{item.categoria} · mín {Math.round(item.stock_minimo)} {item.unidad_medida}</p>
                </div>
                <span className={`text-base font-bold mr-1 ${c.text}`}>
                  {Math.round(item.stock_actual)}
                  <span className="text-xs font-normal text-gray-400 ml-0.5">{item.unidad_medida}</span>
                </span>
                <div className="flex gap-1.5 shrink-0">
                  <button onClick={() => { setSelected(item); setTipo('entrada'); setCantidad(''); setMotivo(''); setError('') }}
                    className="w-8 h-8 rounded-xl bg-green-100 hover:bg-green-200 text-green-600 flex items-center justify-center transition-colors">
                    <Plus size={14} />
                  </button>
                  <button onClick={() => { setSelected(item); setTipo('salida'); setCantidad(''); setMotivo(''); setError('') }}
                    className="w-8 h-8 rounded-xl bg-red-100 hover:bg-red-200 text-red-600 flex items-center justify-center transition-colors">
                    <Minus size={14} />
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </BaristaLayout>
  )
}

// Esta pantalla ya no bifurca por rol: la vista admin que vivía acá duplicaba
// /catalogo (maestro de productos) y /control-inventario (stock), no la linkeaba
// nada y se borró. /inventario redirige al admin desde App.tsx.
export default InventarioBarista
