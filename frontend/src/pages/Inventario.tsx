import { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { Plus, Minus, X, RefreshCw, AlertTriangle } from 'lucide-react'
import BaristaLayout from '../components/BaristaLayout'

// ─── Tipos ────────────────────────────────────────────────────────────────────

interface InvItem {
  id: number; producto_id: number; producto_nombre: string; categoria: string
  unidad_medida: string; stock_actual: number; stock_minimo: number; alerta: boolean
}

interface Tienda { id: number; nombre: string }
interface StockTienda { stock_actual: number; stock_minimo: number; alerta: boolean }
interface ProductoAdmin {
  id: number; nombre: string; categoria: string; unidad_medida: string
  stocks: Record<string, StockTienda>
}


// ─── Helpers ──────────────────────────────────────────────────────────────────

function stockColor(item: InvItem) {
  if (item.stock_actual === 0) return { bg: 'bg-red-100', border: 'border-red-300', text: 'text-red-700', dot: 'bg-red-500' }
  if (item.alerta) return { bg: 'bg-amber-50', border: 'border-amber-200', text: 'text-amber-700', dot: 'bg-amber-400' }
  return { bg: 'bg-white', border: 'border-gray-200', text: 'text-gray-700', dot: 'bg-green-400' }
}

function stockDot(s: StockTienda) {
  if (s.stock_actual === 0) return 'bg-red-500'
  if (s.alerta) return 'bg-amber-400'
  return 'bg-green-400'
}

function stockTextColor(s: StockTienda) {
  if (s.stock_actual === 0) return 'text-red-600 font-bold'
  if (s.alerta) return 'text-amber-600 font-semibold'
  return 'text-gray-700'
}

const CATEGORIAS: Record<string, string> = {
  pasteleria: 'Pastelería',
  bebida: 'Bebidas',
  insumo: 'Insumos',
}

// ─── Vista admin ──────────────────────────────────────────────────────────────

function InventarioAdmin() {
  const [tiendas, setTiendas] = useState<Tienda[]>([])
  const [productos, setProductos] = useState<ProductoAdmin[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<{ producto: ProductoAdmin; tienda: Tienda } | null>(null)
  const [tipo, setTipo] = useState<'entrada' | 'salida' | 'ajuste'>('entrada')
  const [cantidad, setCantidad] = useState('')
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [filtro, setFiltro] = useState<'todos' | 'alertas'>('todos')

  const load = async () => {
    try {
      const { data } = await api.get('/inventario/admin/resumen')
      setTiendas(data.tiendas)
      setProductos(data.productos)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const registrar = async () => {
    if (!selected) return
    setError(''); setSaving(true)
    try {
      await api.post('/inventario/movimiento', {
        producto_id: selected.producto.id,
        tienda_id: selected.tienda.id,
        tipo, cantidad: Number(cantidad), motivo: motivo || null,
      })
      setCantidad(''); setMotivo(''); setSelected(null)
      load()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error')
    } finally { setSaving(false) }
  }

  if (loading) return <div className="flex justify-center py-16"><p className="text-sm text-gray-400">Cargando...</p></div>

  const productosFiltrados = filtro === 'alertas'
    ? productos.filter(p => Object.values(p.stocks).some(s => s.alerta || s.stock_actual === 0))
    : productos

  const porCategoria = Object.entries(CATEGORIAS).map(([key, label]) => ({
    key, label,
    items: productosFiltrados.filter(p => p.categoria === key),
  })).filter(g => g.items.length > 0)

  return (
    <div className="space-y-4">
      {/* Filtro + refresh */}
      <div className="flex items-center justify-between">
        <div className="flex gap-2">
          {(['todos', 'alertas'] as const).map(f => (
            <button key={f} onClick={() => setFiltro(f)}
              className={`text-xs px-3 py-1.5 rounded-lg font-semibold transition-colors ${
                filtro === f ? 'bg-amber-600 text-white' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
              }`}>
              {f === 'todos' ? 'Todos' : 'Con alertas'}
            </button>
          ))}
        </div>
        <button onClick={load} className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors">
          <RefreshCw size={15} />
        </button>
      </div>

      {/* Cabecera sedes */}
      {tiendas.length > 0 && (
        <div className="grid gap-1" style={{ gridTemplateColumns: `1fr repeat(${tiendas.length}, 80px)` }}>
          <div />
          {tiendas.map(t => (
            <div key={t.id} className="text-center text-xs font-bold text-gray-500 uppercase tracking-wide">{t.nombre}</div>
          ))}
        </div>
      )}

      {/* Modal movimiento */}
      {selected && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-end justify-center">
          <div className="bg-white w-full max-w-md rounded-t-3xl p-6 space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-base font-bold text-gray-800">{selected.producto.nombre}</p>
                <p className="text-xs text-gray-400">Sede: <span className="font-semibold text-gray-600">{selected.tienda.nombre}</span></p>
              </div>
              <button onClick={() => setSelected(null)} className="text-gray-400 hover:text-gray-600">
                <X size={20} />
              </button>
            </div>
            <p className="text-sm text-gray-500">
              Stock actual: <strong>{selected.producto.stocks[String(selected.tienda.id)]?.stock_actual ?? 0} {selected.producto.unidad_medida}</strong>
            </p>
            {error && (
              <div className="flex items-center gap-2 text-red-600 text-sm bg-red-50 px-3 py-2 rounded-xl">
                <AlertTriangle size={14} /> {error}
              </div>
            )}
            <div className="flex gap-2">
              {(['entrada', 'salida', 'ajuste'] as const).map(t => (
                <button key={t} onClick={() => setTipo(t)}
                  className={`flex-1 py-2.5 rounded-xl text-sm font-semibold border-2 transition-colors ${
                    tipo === t
                      ? t === 'entrada' ? 'bg-green-100 border-green-400 text-green-700'
                        : t === 'salida' ? 'bg-red-100 border-red-400 text-red-700'
                        : 'bg-blue-100 border-blue-400 text-blue-700'
                      : 'border-gray-200 text-gray-400'
                  }`}>{t}</button>
              ))}
            </div>
            <input type="number" value={cantidad} onChange={e => setCantidad(e.target.value)}
              placeholder={`Cantidad (${selected.producto.unidad_medida})`}
              className="w-full border-2 border-gray-200 rounded-xl px-4 py-3 text-lg font-bold focus:outline-none focus:border-amber-400"
              autoFocus />
            <input value={motivo} onChange={e => setMotivo(e.target.value)} placeholder="Motivo (opcional)"
              className="w-full border-2 border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-amber-400" />
            <button onClick={registrar} disabled={!cantidad || saving}
              className="w-full bg-amber-600 hover:bg-amber-700 disabled:opacity-40 text-white font-bold py-3.5 rounded-xl text-sm transition-colors">
              {saving ? 'Guardando...' : 'Confirmar'}
            </button>
          </div>
        </div>
      )}

      {/* Lista por categoría */}
      {porCategoria.map(grupo => (
        <div key={grupo.key} className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
          <div className="px-4 py-2.5 border-b border-gray-100 bg-gray-50">
            <p className="text-xs font-bold text-gray-500 uppercase tracking-wide">{grupo.label}</p>
          </div>
          <div className="divide-y divide-gray-50">
            {grupo.items.map(p => (
              <div key={p.id}
                className="grid items-center gap-2 px-4 py-3"
                style={{ gridTemplateColumns: `1fr repeat(${tiendas.length}, 80px)` }}>
                <p className="text-sm font-medium text-gray-800 truncate">{p.nombre}</p>
                {tiendas.map(t => {
                  const s = p.stocks[String(t.id)] ?? { stock_actual: 0, stock_minimo: 0, alerta: false }
                  return (
                    <button key={t.id}
                      onClick={() => { setSelected({ producto: p, tienda: t }); setTipo('entrada'); setCantidad(''); setMotivo(''); setError('') }}
                      className="flex flex-col items-center gap-0.5 py-1.5 rounded-xl hover:bg-gray-100 transition-colors">
                      <div className={`w-2 h-2 rounded-full ${stockDot(s)}`} />
                      <span className={`text-sm ${stockTextColor(s)}`}>{s.stock_actual}</span>
                      <span className="text-xs text-gray-400">{p.unidad_medida}</span>
                    </button>
                  )
                })}
              </div>
            ))}
          </div>
        </div>
      ))}

      {productosFiltrados.length === 0 && (
        <p className="text-center text-sm text-gray-400 py-8">Sin productos con alertas.</p>
      )}
    </div>
  )
}

// ─── Vista barista ────────────────────────────────────────────────────────────

function InventarioBarista() {
  const { user } = useAuth()
  const [items, setItems] = useState<InvItem[]>([])
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

  useEffect(() => { load() }, [user])

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
      setError(e.response?.data?.detail || 'Error')
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
          <div className="fixed inset-0 bg-black/50 z-50 flex items-end justify-center">
            <div className="bg-white w-full max-w-md rounded-t-3xl p-6 space-y-4">
              <div className="flex items-center justify-between">
                <p className="text-base font-bold text-gray-800">{selected.producto_nombre}</p>
                <button onClick={() => setSelected(null)} className="text-gray-400 hover:text-gray-600">
                  <X size={20} />
                </button>
              </div>
              <p className="text-sm text-gray-500">Stock actual: <strong>{selected.stock_actual} {selected.unidad_medida}</strong></p>
              {error && (
                <div className="flex items-center gap-2 text-red-600 text-sm bg-red-50 px-3 py-2 rounded-xl">
                  <AlertTriangle size={14} /> {error}
                </div>
              )}
              <div className="flex gap-2">
                {(['entrada', 'salida', 'ajuste'] as const).map(t => (
                  <button key={t} onClick={() => setTipo(t)}
                    className={`flex-1 py-2.5 rounded-xl text-sm font-semibold border-2 transition-colors ${
                      tipo === t
                        ? t === 'entrada' ? 'bg-green-100 border-green-400 text-green-700'
                          : t === 'salida' ? 'bg-red-100 border-red-400 text-red-700'
                          : 'bg-blue-100 border-blue-400 text-blue-700'
                        : 'border-gray-200 text-gray-400'
                    }`}>{t}</button>
                ))}
              </div>
              <input type="number" value={cantidad} onChange={e => setCantidad(e.target.value)}
                placeholder={`Cantidad (${selected.unidad_medida})`}
                className="w-full border-2 border-gray-200 rounded-xl px-4 py-3 text-lg font-bold focus:outline-none focus:border-amber-400"
                autoFocus />
              <input value={motivo} onChange={e => setMotivo(e.target.value)} placeholder="Motivo (opcional)"
                className="w-full border-2 border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-amber-400" />
              <button onClick={registrar} disabled={!cantidad || saving}
                className="w-full bg-amber-600 hover:bg-amber-700 disabled:opacity-40 text-white font-bold py-3.5 rounded-xl text-sm transition-colors">
                {saving ? 'Guardando...' : 'Confirmar'}
              </button>
            </div>
          </div>
        )}

        <div className="space-y-2">
          {items.map(item => {
            const c = stockColor(item)
            return (
              <div key={item.id}
                className={`flex items-center gap-3 px-4 py-3.5 rounded-2xl border-2 ${c.bg} ${c.border} transition-all`}>
                <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${c.dot}`} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-gray-800 leading-tight">{item.producto_nombre}</p>
                  <p className="text-xs text-gray-400">{item.categoria} · mín {item.stock_minimo} {item.unidad_medida}</p>
                </div>
                <span className={`text-base font-bold mr-1 ${c.text}`}>
                  {item.stock_actual}
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

// ─── Router ───────────────────────────────────────────────────────────────────

export default function Inventario() {
  const { user } = useAuth()
  return user?.rol === 'admin' ? <InventarioAdmin /> : <InventarioBarista />
}
