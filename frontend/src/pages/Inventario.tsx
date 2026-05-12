import { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { Plus, Minus, X, RefreshCw, AlertTriangle, Pencil, Package, Check } from 'lucide-react'
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
  controla_stock: boolean; stocks: Record<string, StockTienda>
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

// ─── Constantes catálogo ──────────────────────────────────────────────────────
const CAT_COLS = ['pasteleria', 'bebida', 'insumo'] as const
type CatCol = typeof CAT_COLS[number]
const CAT_LABEL: Record<CatCol, string> = { pasteleria: 'Pastelería', bebida: 'Bebidas / Café', insumo: 'Insumos / Desechables' }
const CAT_COLOR: Record<CatCol, { bg: string; text: string }> = {
  pasteleria: { bg: 'oklch(96% 0.015 60)',  text: 'oklch(40% 0.12 55)' },
  bebida:     { bg: 'oklch(95% 0.015 155)', text: 'oklch(30% 0.10 155)' },
  insumo:     { bg: 'oklch(95% 0.015 245)', text: 'oklch(30% 0.12 245)' },
}
const UNIDADES = ['und', 'g', 'kg', 'litro', 'ml', 'porción', 'paq']

// ─── Vista admin ──────────────────────────────────────────────────────────────

function InventarioAdmin() {
  const [tiendas, setTiendas] = useState<Tienda[]>([])
  const [productos, setProductos] = useState<ProductoAdmin[]>([])
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<'stock' | 'productos'>('stock')

  // ── Stock state ───────────────────────────────────────────────────────────────
  const [selected, setSelected] = useState<{ producto: ProductoAdmin; tienda: Tienda } | null>(null)
  const [tipo, setTipo] = useState<'entrada' | 'salida' | 'ajuste'>('entrada')
  const [cantidad, setCantidad] = useState('')
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [filtro, setFiltro] = useState<'todos' | 'alertas'>('todos')

  // ── Productos (catálogo) state ────────────────────────────────────────────────
  const [catFiltro, setCatFiltro] = useState<CatCol | 'todas'>('todas')
  const [busqueda, setBusqueda] = useState('')
  const [editandoId, setEditandoId] = useState<number | null>(null)
  const [editForm, setEditForm] = useState({ nombre: '', categoria: '', unidad_medida: '', controla_stock: true })
  const [nuevoForm, setNuevoForm] = useState({ nombre: '', categoria: 'insumo', unidad_medida: 'und', controla_stock: true })
  const [mostrarNuevo, setMostrarNuevo] = useState(false)
  const [minimoEditing, setMinimoEditing] = useState<{ productoId: number; tiendaId: number; valor: string } | null>(null)
  const [catError, setCatError] = useState('')
  const [catSaving, setCatSaving] = useState(false)

  const load = async () => {
    try {
      const { data } = await api.get('/inventario/admin/resumen')
      setTiendas(data.tiendas)
      setProductos(data.productos)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  // ── Stock actions ─────────────────────────────────────────────────────────────
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

  // ── Catálogo actions ──────────────────────────────────────────────────────────
  const guardarEdicion = async () => {
    if (!editandoId) return
    setCatSaving(true)
    try {
      await api.patch(`/inventario/productos/${editandoId}`, editForm)
      setEditandoId(null); load()
    } catch (e: any) { setCatError(e.response?.data?.detail || 'Error') }
    finally { setCatSaving(false) }
  }

  const crearProducto = async () => {
    setCatSaving(true)
    try {
      await api.post('/inventario/productos', nuevoForm)
      setMostrarNuevo(false)
      setNuevoForm({ nombre: '', categoria: 'insumo', unidad_medida: 'und', controla_stock: true })
      load()
    } catch (e: any) { setCatError(e.response?.data?.detail || 'Error') }
    finally { setCatSaving(false) }
  }

  const guardarMinimo = async () => {
    if (!minimoEditing) return
    try {
      await api.patch(`/inventario/tienda/${minimoEditing.tiendaId}/producto/${minimoEditing.productoId}/minimo`, {
        stock_minimo: Number(minimoEditing.valor)
      })
      setMinimoEditing(null); load()
    } catch (e: any) { setCatError(e.response?.data?.detail || 'Error') }
  }

  if (loading) return <div className="flex justify-center py-16"><p className="text-sm text-gray-400">Cargando...</p></div>

  // ── Stock computed ────────────────────────────────────────────────────────────
  const productosFiltrados = filtro === 'alertas'
    ? productos.filter(p => Object.values(p.stocks).some(s => s.alerta || s.stock_actual === 0))
    : productos
  const porCategoria = Object.entries(CATEGORIAS).map(([key, label]) => ({
    key, label,
    items: productosFiltrados.filter(p => p.categoria === key),
  })).filter(g => g.items.length > 0)

  // ── Catálogo computed ─────────────────────────────────────────────────────────
  const prodCatFiltrados = productos.filter(p => {
    const matchCat = catFiltro === 'todas' || p.categoria === catFiltro
    const matchBusq = p.nombre.toLowerCase().includes(busqueda.toLowerCase())
    return matchCat && matchBusq
  })
  const alertasTotal = productos.reduce((n, p) =>
    n + Object.values(p.stocks).filter(s => s.alerta && p.controla_stock).length, 0)

  return (
    <div className="space-y-4">

      {/* ── Tabs ── */}
      <div className="flex gap-1 bg-gray-100 rounded-xl p-1">
        {([['stock', 'Stock'], ['productos', 'Productos']] as const).map(([key, label]) => (
          <button key={key} onClick={() => setTab(key)}
            className={`flex-1 py-2 rounded-lg text-xs font-bold transition-all ${
              tab === key ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-500 hover:text-gray-700'
            }`}>
            {label}
          </button>
        ))}
      </div>

      {/* ══════════════ TAB STOCK ══════════════ */}
      {tab === 'stock' && <>
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

        {tiendas.length > 0 && (
          <div className="grid gap-1" style={{ gridTemplateColumns: `1fr repeat(${tiendas.length}, 80px)` }}>
            <div />
            {tiendas.map(t => (
              <div key={t.id} className="text-center text-xs font-bold text-gray-500 uppercase tracking-wide">{t.nombre}</div>
            ))}
          </div>
        )}

        {selected && (
          <div className="fixed inset-0 bg-black/50 z-50 flex items-end justify-center">
            <div className="bg-white w-full max-w-md rounded-t-3xl p-6 space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-base font-bold text-gray-800">{selected.producto.nombre}</p>
                  <p className="text-xs text-gray-400">Sede: <span className="font-semibold text-gray-600">{selected.tienda.nombre}</span></p>
                </div>
                <button onClick={() => setSelected(null)} className="text-gray-400 hover:text-gray-600"><X size={20} /></button>
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

        {porCategoria.map(grupo => (
          <div key={grupo.key} className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
            <div className="px-4 py-2.5 border-b border-gray-100 bg-gray-50">
              <p className="text-xs font-bold text-gray-500 uppercase tracking-wide">{grupo.label}</p>
            </div>
            <div className="divide-y divide-gray-50">
              {grupo.items.map(p => (
                <div key={p.id} className="grid items-center gap-2 px-4 py-3"
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
      </>}

      {/* ══════════════ TAB PRODUCTOS ══════════════ */}
      {tab === 'productos' && <>
        <div className="flex items-center justify-between flex-wrap gap-3">
          <p className="text-xs text-gray-400">{productos.length} productos · {tiendas.length} sedes</p>
          <div className="flex items-center gap-2">
            {alertasTotal > 0 && (
              <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold"
                style={{ background: 'oklch(96% 0.015 20)', color: 'oklch(38% 0.16 25)' }}>
                <AlertTriangle size={12} /> {alertasTotal} alerta{alertasTotal > 1 ? 's' : ''}
              </span>
            )}
            <button onClick={() => setMostrarNuevo(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold text-white"
              style={{ background: 'oklch(48% 0.12 155)' }}>
              <Plus size={13} /> Nuevo
            </button>
          </div>
        </div>

        {catError && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl">
            <AlertTriangle size={14} /> {catError}
            <button onClick={() => setCatError('')} className="ml-auto"><X size={13} /></button>
          </div>
        )}

        {/* Filtros */}
        <div className="flex gap-2 flex-wrap">
          {(['todas', ...CAT_COLS] as const).map(c => (
            <button key={c} onClick={() => setCatFiltro(c)}
              className="px-3 py-1.5 rounded-xl text-xs font-semibold border-2 transition-all"
              style={catFiltro === c ? {
                background: c === 'todas' ? 'oklch(35% 0.05 155)' : CAT_COLOR[c as CatCol].bg,
                borderColor: c === 'todas' ? 'oklch(35% 0.05 155)' : CAT_COLOR[c as CatCol].text,
                color: c === 'todas' ? 'white' : CAT_COLOR[c as CatCol].text,
              } : { background: 'white', borderColor: 'oklch(88% 0.006 75)', color: 'oklch(40% 0.01 60)' }}>
              {c === 'todas' ? 'Todas' : CAT_LABEL[c as CatCol]}
            </button>
          ))}
          <input value={busqueda} onChange={e => setBusqueda(e.target.value)}
            placeholder="Buscar..." className="ml-auto px-3 py-1.5 rounded-xl border-2 text-xs outline-none"
            style={{ borderColor: 'oklch(88% 0.006 75)' }} />
        </div>

        {/* Formulario nuevo */}
        {mostrarNuevo && (
          <div className="bg-white rounded-2xl border-2 p-5 space-y-4" style={{ borderColor: 'oklch(48% 0.12 155)' }}>
            <p className="text-sm font-bold text-gray-800">Nuevo producto</p>
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2">
                <label className="text-xs font-semibold text-gray-500 block mb-1">Nombre</label>
                <input value={nuevoForm.nombre} onChange={e => setNuevoForm(f => ({ ...f, nombre: e.target.value }))}
                  placeholder="Ej: Leche de Avena"
                  className="w-full border-2 border-gray-200 rounded-xl px-3 py-2 text-sm" autoFocus />
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-500 block mb-1">Categoría</label>
                <select value={nuevoForm.categoria} onChange={e => setNuevoForm(f => ({ ...f, categoria: e.target.value }))}
                  className="w-full border-2 border-gray-200 rounded-xl px-3 py-2 text-sm">
                  {CAT_COLS.map(c => <option key={c} value={c}>{CAT_LABEL[c]}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-500 block mb-1">Unidad</label>
                <select value={nuevoForm.unidad_medida} onChange={e => setNuevoForm(f => ({ ...f, unidad_medida: e.target.value }))}
                  className="w-full border-2 border-gray-200 rounded-xl px-3 py-2 text-sm">
                  {UNIDADES.map(u => <option key={u} value={u}>{u}</option>)}
                </select>
              </div>
              <div className="col-span-2 flex items-center gap-2">
                <input type="checkbox" id="ctrl-stock" checked={nuevoForm.controla_stock}
                  onChange={e => setNuevoForm(f => ({ ...f, controla_stock: e.target.checked }))} />
                <label htmlFor="ctrl-stock" className="text-sm text-gray-600">Controla stock</label>
              </div>
            </div>
            <div className="flex gap-2">
              <button onClick={crearProducto} disabled={!nuevoForm.nombre || catSaving}
                className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-40"
                style={{ background: 'oklch(48% 0.12 155)' }}>
                <Check size={14} /> Guardar
              </button>
              <button onClick={() => setMostrarNuevo(false)}
                className="px-4 py-2 rounded-xl text-sm font-semibold border-2 border-gray-200 text-gray-600">
                Cancelar
              </button>
            </div>
          </div>
        )}

        {/* Tabla por categoría */}
        {(catFiltro === 'todas' ? CAT_COLS : [catFiltro]).map(cat => {
          const lista = prodCatFiltrados.filter(p => p.categoria === cat)
          if (lista.length === 0) return null
          return (
            <div key={cat} className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
              <div className="px-4 py-2.5 border-b border-gray-100 flex items-center gap-2">
                <Package size={14} style={{ color: CAT_COLOR[cat].text }} />
                <p className="text-xs font-bold uppercase tracking-wide" style={{ color: CAT_COLOR[cat].text }}>
                  {CAT_LABEL[cat]} — {lista.length}
                </p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100">
                      <th className="text-left px-4 py-2 text-xs font-semibold text-gray-400 uppercase tracking-wide w-64">Producto</th>
                      <th className="text-left px-4 py-2 text-xs font-semibold text-gray-400 uppercase tracking-wide w-20">Unidad</th>
                      {tiendas.map(t => (
                        <th key={t.id} className="text-center px-3 py-2 text-xs font-semibold text-gray-400 uppercase tracking-wide whitespace-nowrap">
                          {t.nombre}
                        </th>
                      ))}
                      <th className="w-16" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {lista.map(p => (
                      <tr key={p.id} className="hover:bg-gray-50 transition-colors">
                        {editandoId === p.id ? (
                          <>
                            <td className="px-4 py-2">
                              <input value={editForm.nombre} onChange={e => setEditForm(f => ({ ...f, nombre: e.target.value }))}
                                className="w-full border-2 border-gray-200 rounded-lg px-2 py-1 text-sm" autoFocus />
                            </td>
                            <td className="px-4 py-2">
                              <select value={editForm.unidad_medida} onChange={e => setEditForm(f => ({ ...f, unidad_medida: e.target.value }))}
                                className="border-2 border-gray-200 rounded-lg px-2 py-1 text-xs">
                                {UNIDADES.map(u => <option key={u} value={u}>{u}</option>)}
                              </select>
                            </td>
                            {tiendas.map(t => <td key={t.id} />)}
                            <td className="px-3 py-2">
                              <div className="flex gap-1">
                                <button onClick={guardarEdicion} disabled={catSaving}
                                  className="p-1.5 rounded-lg text-white" style={{ background: 'oklch(48% 0.12 155)' }}>
                                  <Check size={12} />
                                </button>
                                <button onClick={() => setEditandoId(null)}
                                  className="p-1.5 rounded-lg border-2 border-gray-200 text-gray-400">
                                  <X size={12} />
                                </button>
                              </div>
                            </td>
                          </>
                        ) : (
                          <>
                            <td className="px-4 py-2.5 font-medium text-gray-800">{p.nombre}</td>
                            <td className="px-4 py-2.5 text-xs text-gray-400 font-mono">{p.unidad_medida}</td>
                            {tiendas.map(t => {
                              const s = p.stocks[String(t.id)]
                              const isEditingMin = minimoEditing?.productoId === p.id && minimoEditing?.tiendaId === t.id
                              if (!p.controla_stock) return <td key={t.id} className="px-3 py-2 text-center text-xs text-gray-300">—</td>
                              return (
                                <td key={t.id} className="px-3 py-2 text-center">
                                  <div className="flex flex-col items-center gap-0.5">
                                    <span className={`text-sm font-bold font-mono ${s?.alerta ? 'text-red-500' : 'text-gray-800'}`}>
                                      {s?.stock_actual ?? 0}
                                    </span>
                                    {isEditingMin ? (
                                      <div className="flex items-center gap-1">
                                        <input type="number" value={minimoEditing.valor}
                                          onChange={e => setMinimoEditing(m => m ? { ...m, valor: e.target.value } : null)}
                                          className="w-14 border border-gray-300 rounded px-1 text-xs text-center" autoFocus
                                          onKeyDown={e => { if (e.key === 'Enter') guardarMinimo() }} />
                                        <button onClick={guardarMinimo} className="text-green-600"><Check size={11} /></button>
                                        <button onClick={() => setMinimoEditing(null)} className="text-gray-400"><X size={11} /></button>
                                      </div>
                                    ) : (
                                      <button
                                        onClick={() => setMinimoEditing({ productoId: p.id, tiendaId: t.id, valor: String(s?.stock_minimo ?? 0) })}
                                        className="text-xs text-gray-400 hover:text-gray-600 transition-colors" title="Editar mínimo">
                                        mín {s?.stock_minimo ?? 0}
                                      </button>
                                    )}
                                  </div>
                                </td>
                              )
                            })}
                            <td className="px-3 py-2">
                              <button
                                onClick={() => { setEditandoId(p.id); setEditForm({ nombre: p.nombre, categoria: p.categoria, unidad_medida: p.unidad_medida, controla_stock: p.controla_stock }) }}
                                className="p-1.5 rounded-lg border-2 border-gray-200 text-gray-400 hover:border-gray-300 hover:text-gray-600 transition-colors">
                                <Pencil size={12} />
                              </button>
                            </td>
                          </>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )
        })}
      </>}
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
