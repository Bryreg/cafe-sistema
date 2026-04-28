import { useEffect, useState } from 'react'
import api from '../api/client'
import { Plus, Pencil, Check, X, AlertTriangle, Package } from 'lucide-react'

interface Tienda { id: number; nombre: string }
interface StockInfo { stock_actual: number; stock_minimo: number; alerta: boolean }
interface Producto {
  id: number; nombre: string; categoria: string
  unidad_medida: string; controla_stock: boolean
  stocks: Record<string, StockInfo>
}

const CATEGORIAS = ['pasteleria', 'bebida', 'insumo'] as const
type Cat = typeof CATEGORIAS[number]

const CAT_LABEL: Record<Cat, string> = { pasteleria: 'Pastelería', bebida: 'Bebidas / Café', insumo: 'Insumos / Desechables' }
const CAT_COLOR: Record<Cat, { bg: string; text: string }> = {
  pasteleria: { bg: 'oklch(96% 0.015 60)',  text: 'oklch(40% 0.12 55)' },
  bebida:     { bg: 'oklch(95% 0.015 155)', text: 'oklch(30% 0.10 155)' },
  insumo:     { bg: 'oklch(95% 0.015 245)', text: 'oklch(30% 0.12 245)' },
}

const UNIDADES = ['und', 'g', 'kg', 'litro', 'ml', 'porción', 'paq']

function badge(cat: string) {
  const c = CAT_COLOR[cat as Cat] || { bg: 'oklch(93% 0.005 60)', text: 'oklch(40% 0.005 60)' }
  return (
    <span className="text-xs px-2 py-0.5 rounded-md font-semibold"
      style={{ background: c.bg, color: c.text }}>
      {CAT_LABEL[cat as Cat] || cat}
    </span>
  )
}

export default function Catalogo() {
  const [tiendas, setTiendas] = useState<Tienda[]>([])
  const [productos, setProductos] = useState<Producto[]>([])
  const [catFiltro, setCatFiltro] = useState<Cat | 'todas'>('todas')
  const [busqueda, setBusqueda] = useState('')
  const [editandoId, setEditandoId] = useState<number | null>(null)
  const [editForm, setEditForm] = useState({ nombre: '', categoria: '', unidad_medida: '', controla_stock: true })
  const [nuevoForm, setNuevoForm] = useState({ nombre: '', categoria: 'insumo', unidad_medida: 'und', controla_stock: true })
  const [mostrarNuevo, setMostrarNuevo] = useState(false)
  const [minimoEditing, setMinimoEditing] = useState<{ productoId: number; tiendaId: number; valor: string } | null>(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const load = async () => {
    const res = await api.get('/inventario/admin/resumen')
    setTiendas(res.data.tiendas)
    setProductos(res.data.productos)
  }

  useEffect(() => { load() }, [])

  const productosFiltrados = productos.filter(p => {
    const matchCat = catFiltro === 'todas' || p.categoria === catFiltro
    const matchBusq = p.nombre.toLowerCase().includes(busqueda.toLowerCase())
    return matchCat && matchBusq
  })

  const guardarEdicion = async () => {
    if (!editandoId) return
    setSaving(true)
    try {
      await api.patch(`/inventario/productos/${editandoId}`, editForm)
      setEditandoId(null)
      load()
    } catch (e: any) { setError(e.response?.data?.detail || 'Error') }
    finally { setSaving(false) }
  }

  const crearProducto = async () => {
    setSaving(true)
    try {
      await api.post('/inventario/productos', nuevoForm)
      setMostrarNuevo(false)
      setNuevoForm({ nombre: '', categoria: 'insumo', unidad_medida: 'und', controla_stock: true })
      load()
    } catch (e: any) { setError(e.response?.data?.detail || 'Error') }
    finally { setSaving(false) }
  }

  const guardarMinimo = async () => {
    if (!minimoEditing) return
    try {
      await api.patch(`/inventario/tienda/${minimoEditing.tiendaId}/producto/${minimoEditing.productoId}/minimo`, {
        stock_minimo: Number(minimoEditing.valor)
      })
      setMinimoEditing(null)
      load()
    } catch (e: any) { setError(e.response?.data?.detail || 'Error') }
  }

  const alertasTotal = productos.reduce((n, p) =>
    n + Object.values(p.stocks).filter(s => s.alerta && p.controla_stock).length, 0)

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Catálogo de productos</h1>
          <p className="text-sm text-gray-400">{productos.length} productos · {tiendas.length} sedes</p>
        </div>
        {alertasTotal > 0 && (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl text-sm font-semibold"
            style={{ background: 'oklch(96% 0.015 20)', color: 'oklch(38% 0.16 25)' }}>
            <AlertTriangle size={14} />
            {alertasTotal} alerta{alertasTotal > 1 ? 's' : ''} de stock
          </div>
        )}
        <button onClick={() => setMostrarNuevo(true)}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-bold text-white"
          style={{ background: 'oklch(48% 0.12 155)' }}>
          <Plus size={15} /> Nuevo producto
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl">
          <AlertTriangle size={14} /> {error}
          <button onClick={() => setError('')} className="ml-auto"><X size={13} /></button>
        </div>
      )}

      {/* Filtros */}
      <div className="flex gap-2 flex-wrap">
        {(['todas', ...CATEGORIAS] as const).map(c => (
          <button key={c}
            onClick={() => setCatFiltro(c)}
            className="px-3 py-1.5 rounded-xl text-xs font-semibold border-2 transition-all"
            style={catFiltro === c ? {
              background: c === 'todas' ? 'oklch(35% 0.05 155)' : CAT_COLOR[c as Cat].bg,
              borderColor: c === 'todas' ? 'oklch(35% 0.05 155)' : CAT_COLOR[c as Cat].text,
              color: c === 'todas' ? 'white' : CAT_COLOR[c as Cat].text,
            } : {
              background: 'white',
              borderColor: 'oklch(88% 0.006 75)',
              color: 'oklch(40% 0.01 60)',
            }}>
            {c === 'todas' ? 'Todas' : CAT_LABEL[c as Cat]}
          </button>
        ))}
        <input
          value={busqueda}
          onChange={e => setBusqueda(e.target.value)}
          placeholder="Buscar..."
          className="ml-auto px-3 py-1.5 rounded-xl border-2 text-xs outline-none"
          style={{ borderColor: 'oklch(88% 0.006 75)' }}
        />
      </div>

      {/* Formulario nuevo producto */}
      {mostrarNuevo && (
        <div className="bg-white rounded-2xl border-2 p-5 space-y-4"
          style={{ borderColor: 'oklch(48% 0.12 155)' }}>
          <p className="text-sm font-bold text-gray-800">Nuevo producto</p>
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <label className="text-xs font-semibold text-gray-500 block mb-1">Nombre</label>
              <input value={nuevoForm.nombre} onChange={e => setNuevoForm(f => ({ ...f, nombre: e.target.value }))}
                placeholder="Ej: Leche de Avena" className="w-full border-2 border-gray-200 rounded-xl px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="text-xs font-semibold text-gray-500 block mb-1">Categoría</label>
              <select value={nuevoForm.categoria} onChange={e => setNuevoForm(f => ({ ...f, categoria: e.target.value }))}
                className="w-full border-2 border-gray-200 rounded-xl px-3 py-2 text-sm">
                {CATEGORIAS.map(c => <option key={c} value={c}>{CAT_LABEL[c]}</option>)}
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
              <input type="checkbox" id="ctrl" checked={nuevoForm.controla_stock}
                onChange={e => setNuevoForm(f => ({ ...f, controla_stock: e.target.checked }))} />
              <label htmlFor="ctrl" className="text-sm text-gray-600">Controla stock</label>
            </div>
          </div>
          <div className="flex gap-2">
            <button onClick={crearProducto} disabled={!nuevoForm.nombre || saving}
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
      {(catFiltro === 'todas' ? CATEGORIAS : [catFiltro]).map(cat => {
        const lista = productosFiltrados.filter(p => p.categoria === cat)
        if (lista.length === 0) return null
        return (
          <div key={cat} className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
            <div className="px-4 py-2.5 border-b border-gray-100 flex items-center gap-2">
              <Package size={14} style={{ color: CAT_COLOR[cat].text }} />
              <p className="text-xs font-bold uppercase tracking-wide" style={{ color: CAT_COLOR[cat].text }}>
                {CAT_LABEL[cat]} — {lista.length}
              </p>
            </div>

            {/* Cabecera sedes */}
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
                    <th className="w-16"></th>
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
                              <button onClick={guardarEdicion} disabled={saving}
                                className="p-1.5 rounded-lg text-white"
                                style={{ background: 'oklch(48% 0.12 155)' }}>
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
                            if (!p.controla_stock) {
                              return <td key={t.id} className="px-3 py-2 text-center text-xs text-gray-300">—</td>
                            }
                            return (
                              <td key={t.id} className="px-3 py-2 text-center">
                                <div className="flex flex-col items-center gap-0.5">
                                  <span className={`text-sm font-bold font-mono ${s?.alerta ? 'text-red-500' : 'text-gray-800'}`}>
                                    {s?.stock_actual ?? 0}
                                  </span>
                                  {isEditingMin ? (
                                    <div className="flex items-center gap-1">
                                      <input
                                        type="number"
                                        value={minimoEditing.valor}
                                        onChange={e => setMinimoEditing(m => m ? { ...m, valor: e.target.value } : null)}
                                        className="w-14 border border-gray-300 rounded px-1 text-xs text-center"
                                        autoFocus
                                        onKeyDown={e => { if (e.key === 'Enter') guardarMinimo() }}
                                      />
                                      <button onClick={guardarMinimo} className="text-green-600"><Check size={11} /></button>
                                      <button onClick={() => setMinimoEditing(null)} className="text-gray-400"><X size={11} /></button>
                                    </div>
                                  ) : (
                                    <button
                                      onClick={() => setMinimoEditing({ productoId: p.id, tiendaId: t.id, valor: String(s?.stock_minimo ?? 0) })}
                                      className="text-xs text-gray-400 hover:text-gray-600 transition-colors"
                                      title="Editar mínimo">
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
    </div>
  )
}
