import { useEffect, useState } from 'react'
import api from '../api/client'
import { conMiles, soloDigitos } from '../utils/plata'
import { Plus, Pencil, Check, X, AlertTriangle, Package, Tag, Trash2, Copy, ChefHat } from 'lucide-react'

interface Tienda { id: number; nombre: string }
interface StockInfo { stock_actual: number; stock_minimo: number; alerta: boolean }
interface Producto {
  id: number; nombre: string; categoria: string
  unidad_medida: string; controla_stock: boolean
  incluir_en_conteo: boolean
  stocks: Record<string, StockInfo>
  precio_venta?: number
  fraccionable?: boolean
  envase?: 'bolsa' | 'botella' | null
}

// Archivado = fuera de POS, conteo y stock: duplicados fusionados o productos retirados.
// Se ocultan del catálogo por defecto (la DB los conserva por el historial de conteos).
const esArchivado = (p: Producto) =>
  !p.controla_stock && p.incluir_en_conteo === false && !(p.precio_venta && p.precio_venta > 0)

const CATEGORIAS = ['pasteleria', 'bebida', 'porciones', 'insumo'] as const
type Cat = typeof CATEGORIAS[number]

const CAT_LABEL: Record<Cat, string> = { pasteleria: 'Pastelería', bebida: 'Bebidas / Café', porciones: 'Porciones', insumo: 'Insumos / Desechables' }
const CAT_COLOR: Record<Cat, { bg: string; text: string }> = {
  pasteleria: { bg: 'oklch(96% 0.015 60)',  text: 'oklch(40% 0.12 55)' },
  bebida:     { bg: 'oklch(95% 0.015 155)', text: 'oklch(30% 0.10 155)' },
  porciones:  { bg: 'oklch(95% 0.02 300)',  text: 'oklch(35% 0.13 300)' },
  insumo:     { bg: 'oklch(95% 0.015 245)', text: 'oklch(30% 0.12 245)' },
}

const UNIDADES = ['und', 'g', 'kg', 'litro', 'ml', 'porción', 'paq']

// ─── Editor de receta de consumo ─────────────────────────────────────────────
// Insumos que el POS descuenta del inventario por cada unidad vendida del producto
// (ej. 1 Waffle Pandebono = 4 bolas de masa). Guarda con PUT reemplazando la lista.

function RecetaModal({ producto, productos, onClose }: {
  producto: { id: number; nombre: string }
  productos: Producto[]
  onClose: () => void
}) {
  const [items, setItems] = useState<{ insumo_id: number; cantidad: string }[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get(`/inventario/productos/${producto.id}/insumos`)
      .then(r => setItems((r.data ?? []).map((x: any) => ({ insumo_id: x.insumo_id, cantidad: String(x.cantidad) }))))
      .catch(() => setError('No se pudo cargar la receta'))
      .finally(() => setLoading(false))
  }, [producto.id])

  const candidatos = productos.filter(p => p.id !== producto.id)

  const guardar = async () => {
    setSaving(true); setError('')
    try {
      const payload = items
        .filter(i => i.insumo_id > 0 && Number(i.cantidad) > 0)
        .map(i => ({ insumo_id: i.insumo_id, cantidad: Number(i.cantidad) }))
      await api.put(`/inventario/productos/${producto.id}/insumos`, { items: payload })
      onClose()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'No se pudo guardar la receta')
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl w-full max-w-md p-5" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-1">
          <h3 className="text-sm font-bold text-gray-800 flex items-center gap-1.5">
            <ChefHat size={15} style={{ color: 'oklch(48% 0.12 155)' }} /> Receta de consumo
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={16} /></button>
        </div>
        <p className="text-xs text-gray-500 mb-3">
          Insumos que se descuentan del inventario por cada <strong>{producto.nombre}</strong> vendido en el POS.
        </p>
        {loading ? (
          <p className="text-xs text-gray-400 py-4 text-center">Cargando...</p>
        ) : (
          <>
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {items.map((it, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <select
                    value={it.insumo_id}
                    onChange={e => setItems(arr => arr.map((x, i) => i === idx ? { ...x, insumo_id: Number(e.target.value) } : x))}
                    className="flex-1 min-w-0 border border-gray-300 rounded-lg px-2 py-1.5 text-xs">
                    <option value={0}>Elegir insumo…</option>
                    {candidatos.map(c => (
                      <option key={c.id} value={c.id}>{c.nombre} ({c.unidad_medida})</option>
                    ))}
                  </select>
                  <input
                    type="number" min="0" step="0.5" inputMode="decimal"
                    value={it.cantidad}
                    onChange={e => setItems(arr => arr.map((x, i) => i === idx ? { ...x, cantidad: e.target.value } : x))}
                    className="w-20 border border-gray-300 rounded-lg px-2 py-1.5 text-xs text-right"
                    placeholder="Cant."
                  />
                  <button onClick={() => setItems(arr => arr.filter((_, i) => i !== idx))}
                    className="text-red-400 hover:text-red-600 shrink-0"><Trash2 size={13} /></button>
                </div>
              ))}
              {items.length === 0 && (
                <p className="text-xs text-gray-400 text-center py-3">
                  Sin insumos — vender este producto no descuenta ingredientes.
                </p>
              )}
            </div>
            <button
              onClick={() => setItems(arr => [...arr, { insumo_id: 0, cantidad: '1' }])}
              className="mt-2 text-xs font-semibold flex items-center gap-1"
              style={{ color: 'oklch(45% 0.12 155)' }}>
              <Plus size={12} /> Agregar insumo
            </button>
            {error && <p className="text-xs text-red-600 mt-2">{error}</p>}
            <button onClick={guardar} disabled={saving}
              className="w-full mt-4 py-2.5 rounded-xl text-white text-sm font-bold disabled:opacity-50"
              style={{ background: 'oklch(48% 0.15 155)' }}>
              {saving ? 'Guardando…' : 'Guardar receta'}
            </button>
          </>
        )}
      </div>
    </div>
  )
}

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
  const [editForm, setEditForm] = useState({ nombre: '', categoria: '', unidad_medida: '', controla_stock: true, envase: '' as '' | 'bolsa' | 'botella' })
  const [verArchivados, setVerArchivados] = useState(false)
  const [nuevoForm, setNuevoForm] = useState({ nombre: '', categoria: 'insumo', unidad_medida: 'und', controla_stock: true })
  const [mostrarNuevo, setMostrarNuevo] = useState(false)
  const [minimoEditing, setMinimoEditing] = useState<{ productoId: number; tiendaId: number; valor: string } | null>(null)
  const [precioEditing, setPrecioEditing] = useState<{ productoId: number; valor: string } | null>(null)
  const [showDuplicados, setShowDuplicados] = useState(false)
  const [recetaEditing, setRecetaEditing] = useState<{ id: number; nombre: string } | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  // Agrupa productos que son EL MISMO escrito distinto. La clave normaliza fuerte:
  // quita acentos/mayúsculas/puntuación, separa número de unidad ("9oz"->"9 oz"),
  // normaliza ceros ("04"->"4") y plurales ("Vasos"->"Vaso"), descarta palabras vacías
  // ("de","con","o") / de unidad (oz/gr/ml/gramos) / empaque ("botella"), y ordena los
  // tokens. Caza "Vaso Cartón 9oz" vs "VASO CARTON 9 OZ", "Torta de Chocolate" vs "Torta
  // Chocolate", "Almojábanas" vs "Almojabanas". Los tamaños distintos (12oz vs 16oz) NO
  // se agrupan porque el número cambia.
  const gruposDuplicados = (() => {
    const STOP = new Set(['de', 'la', 'el', 'los', 'las', 'con', 'y', 'x', 'und', 'unidad', 'unidades', 'para', 'o', 'a', 'botella'])
    const UNITS = new Set(['oz', 'onz', 'onza', 'onzas', 'gr', 'g', 'gramos', 'ml', 'cc', 'lt', 'litro', 'litros', 'kg'])
    const claveNorm = (s: string) =>
      s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
        .replace(/(\d)\s*([a-z])/g, '$1 $2')
        .replace(/([a-z])\s*(\d)/g, '$1 $2')
        .replace(/[^a-z0-9 ]/g, ' ').split(/\s+/)
        .filter(t => t && !STOP.has(t) && !UNITS.has(t))
        .map(t => (t.endsWith('s') && t.length > 4 ? t.slice(0, -1) : t))
        .map(t => (/^\d+$/.test(t) ? String(parseInt(t, 10)) : t))
        .filter(t => t && !STOP.has(t) && !UNITS.has(t))
        .sort().join(' ')
    const map = new Map<string, Producto[]>()
    for (const p of productos) {
      const key = claveNorm(p.nombre)
      if (!key) continue
      map.set(key, [...(map.get(key) ?? []), p])
    }
    return [...map.values()].filter(g => g.length > 1)
  })()

  const load = async () => {
    const res = await api.get('/inventario/admin/resumen')
    setTiendas(res.data.tiendas)
    setProductos(res.data.productos)
  }

  useEffect(() => { load() }, [])

  const nArchivados = productos.filter(esArchivado).length
  const productosFiltrados = productos.filter(p => {
    const matchCat = catFiltro === 'todas' || p.categoria === catFiltro
    const matchBusq = p.nombre.toLowerCase().includes(busqueda.toLowerCase())
    const matchArch = verArchivados || !esArchivado(p)
    return matchCat && matchBusq && matchArch
  })

  const guardarEdicion = async () => {
    if (!editandoId) return
    setSaving(true)
    try {
      await api.patch(`/inventario/productos/${editandoId}`, { ...editForm, fraccionable: editForm.envase !== '' })
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

  const eliminarProducto = async (id: number) => {
    try {
      await api.delete(`/inventario/productos/${id}`)
      setConfirmDelete(null)
      load()
    } catch (e: any) {
      setConfirmDelete(null)
      setError(e.response?.data?.detail || 'No se puede eliminar: tiene historial de movimientos')
    }
  }

  const guardarPrecio = async () => {
    if (!precioEditing) return
    const precio = Number(precioEditing.valor)
    if (isNaN(precio) || precio < 0) { setError('Precio inválido'); return }
    try {
      await api.patch(`/pos/productos/${precioEditing.productoId}/precio`, { precio_venta: precio })
      setPrecioEditing(null)
      load()
    } catch (e: any) { setError(e.response?.data?.detail || 'Error al guardar precio') }
  }

  const toggleConteo = async (p: Producto) => {
    try {
      await api.patch(`/inventario/productos/${p.id}`, { incluir_en_conteo: !p.incluir_en_conteo })
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
            onClick={() => { setCatFiltro(c); setShowDuplicados(false) }}
            className="px-3 py-1.5 rounded-xl text-xs font-semibold border-2 transition-all"
            style={!showDuplicados && catFiltro === c ? {
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
        <button
          onClick={() => setShowDuplicados(d => !d)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold border-2 transition-all"
          style={showDuplicados ? {
            background: 'oklch(96% 0.06 35)',
            borderColor: 'oklch(55% 0.16 35)',
            color: 'oklch(38% 0.16 35)',
          } : {
            background: 'white',
            borderColor: 'oklch(88% 0.006 75)',
            color: gruposDuplicados.length > 0 ? 'oklch(42% 0.14 35)' : 'oklch(40% 0.01 60)',
          }}>
          <Copy size={11} />
          Duplicados
          {gruposDuplicados.length > 0 && (
            <span className="px-1.5 py-0.5 rounded-full text-xs font-bold"
              style={{ background: showDuplicados ? 'oklch(55% 0.16 35)' : 'oklch(55% 0.16 35)', color: 'white', fontSize: 9 }}>
              {gruposDuplicados.length}
            </span>
          )}
        </button>
        <input
          value={busqueda}
          onChange={e => setBusqueda(e.target.value)}
          placeholder="Buscar..."
          className="ml-auto px-3 py-1.5 rounded-xl border-2 text-xs outline-none"
          style={{ borderColor: 'oklch(88% 0.006 75)' }}
        />
        {nArchivados > 0 && (
          <button onClick={() => setVerArchivados(v => !v)}
            className="px-3 py-1.5 rounded-xl border-2 text-xs font-semibold transition-colors"
            style={verArchivados
              ? { borderColor: 'oklch(60% 0.05 60)', background: 'oklch(94% 0.01 60)', color: 'oklch(40% 0.02 60)' }
              : { borderColor: 'oklch(88% 0.006 75)', color: 'oklch(55% 0.01 60)' }}>
            {verArchivados ? 'Ocultar archivados' : `Archivados (${nArchivados})`}
          </button>
        )}
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

      {/* Vista duplicados */}
      {showDuplicados && (
        <div className="space-y-4">
          {gruposDuplicados.length === 0 ? (
            <div className="bg-white rounded-2xl border border-gray-200 px-6 py-10 text-center">
              <Check size={32} className="mx-auto mb-3" style={{ color: 'oklch(50% 0.12 155)' }} />
              <p className="text-sm font-semibold text-gray-700">Sin duplicados detectados</p>
              <p className="text-xs text-gray-400 mt-1">Todos los nombres de producto son únicos</p>
            </div>
          ) : (
            gruposDuplicados.map((grupo, gi) => (
              <div key={gi} className="bg-white rounded-2xl border-2 overflow-hidden"
                style={{ borderColor: 'oklch(82% 0.08 35)' }}>
                <div className="px-4 py-2.5 flex items-center gap-2"
                  style={{ background: 'oklch(97% 0.03 35)' }}>
                  <Copy size={13} style={{ color: 'oklch(50% 0.14 35)' }} />
                  <p className="text-xs font-bold uppercase tracking-wide" style={{ color: 'oklch(38% 0.14 35)' }}>
                    {grupo[0].nombre.trim()} — {grupo.length} registros
                  </p>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-100">
                        <th className="text-left px-4 py-2 text-xs font-semibold text-gray-400 uppercase tracking-wide">ID</th>
                        <th className="text-left px-4 py-2 text-xs font-semibold text-gray-400 uppercase tracking-wide">Nombre exacto</th>
                        <th className="text-left px-4 py-2 text-xs font-semibold text-gray-400 uppercase tracking-wide">Categoría</th>
                        <th className="text-left px-4 py-2 text-xs font-semibold text-gray-400 uppercase tracking-wide">Unidad</th>
                        <th className="text-center px-3 py-2 text-xs font-semibold text-gray-400 uppercase tracking-wide">Precio POS</th>
                        {tiendas.map(t => (
                          <th key={t.id} className="text-center px-3 py-2 text-xs font-semibold text-gray-400 uppercase tracking-wide whitespace-nowrap">
                            Stock {t.nombre}
                          </th>
                        ))}
                        <th className="w-20"></th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                      {grupo.map(p => (
                        <tr key={p.id} className="hover:bg-orange-50 transition-colors">
                          <td className="px-4 py-2.5 text-xs text-gray-400 font-mono">#{p.id}</td>
                          <td className="px-4 py-2.5 font-medium text-gray-800">{p.nombre}</td>
                          <td className="px-4 py-2.5">{badge(p.categoria)}</td>
                          <td className="px-4 py-2.5 text-xs text-gray-400 font-mono">{p.unidad_medida}</td>
                          <td className="px-3 py-2.5 text-center text-xs font-semibold"
                            style={{ color: p.precio_venta ? 'oklch(38% 0.12 155)' : 'oklch(65% 0.01 60)' }}>
                            {p.precio_venta ? `$${p.precio_venta.toLocaleString('es-CO')}` : '—'}
                          </td>
                          {tiendas.map(t => {
                            const s = p.stocks[String(t.id)]
                            return (
                              <td key={t.id} className="px-3 py-2.5 text-center">
                                <span className={`text-sm font-bold font-mono ${s?.alerta ? 'text-red-500' : 'text-gray-700'}`}>
                                  {p.controla_stock ? Math.round(s?.stock_actual ?? 0) : '—'}
                                </span>
                              </td>
                            )
                          })}
                          <td className="px-3 py-2.5">
                            {confirmDelete === p.id ? (
                              <div className="flex items-center gap-1">
                                <button onClick={() => eliminarProducto(p.id)}
                                  className="px-2 py-1 rounded-lg text-xs font-bold text-white"
                                  style={{ background: 'oklch(45% 0.18 25)' }}>
                                  Sí
                                </button>
                                <button onClick={() => setConfirmDelete(null)}
                                  className="px-2 py-1 rounded-lg text-xs border-2 border-gray-200 text-gray-500">
                                  No
                                </button>
                              </div>
                            ) : (
                              <button onClick={() => setConfirmDelete(p.id)}
                                className="p-1.5 rounded-lg border-2 border-gray-200 text-gray-400 hover:border-red-300 hover:text-red-500 transition-colors"
                                title="Eliminar producto">
                                <Trash2 size={12} />
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* Tabla por categoría */}
      {!showDuplicados && (catFiltro === 'todas' ? CATEGORIAS : [catFiltro]).map(cat => {
        const lista = productosFiltrados.filter(p => p.categoria === cat)
        if (!lista.length) return null
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
                    <th className="text-center px-3 py-2 text-xs font-semibold uppercase tracking-wide whitespace-nowrap" style={{ color: 'oklch(38% 0.12 155)' }}>
                      Precio POS
                    </th>
                    <th className="text-center px-3 py-2 text-xs font-semibold text-gray-400 uppercase tracking-wide whitespace-nowrap">Conteo</th>
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
                            <div className="flex flex-col gap-1">
                              <select value={editForm.unidad_medida} onChange={e => setEditForm(f => ({ ...f, unidad_medida: e.target.value }))}
                                className="border-2 border-gray-200 rounded-lg px-2 py-1 text-xs">
                                {UNIDADES.map(u => <option key={u} value={u}>{u}</option>)}
                              </select>
                              <select value={editForm.envase}
                                onChange={e => setEditForm(f => ({ ...f, envase: e.target.value as '' | 'bolsa' | 'botella' }))}
                                title="Conteo fraccionado: se cuenta por unidades selladas + nivel de la abierta"
                                className="border-2 border-gray-200 rounded-lg px-2 py-1 text-xs">
                                <option value="">Conteo normal</option>
                                <option value="bolsa">Por bolsa (con dibujo)</option>
                                <option value="botella">Por botella (con dibujo)</option>
                              </select>
                            </div>
                          </td>
                          {tiendas.map(t => <td key={t.id} />)}
                          <td /><td />
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
                                    {Math.round(s?.stock_actual ?? 0)}
                                  </span>
                                  {isEditingMin ? (
                                    <div className="flex items-center gap-1">
                                      <input
                                        type="number"
                                        step="1"
                                        min="0"
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
                                      mín {Math.round(s?.stock_minimo ?? 0)}
                                    </button>
                                  )}
                                </div>
                              </td>
                            )
                          })}
                          {/* Precio POS inline */}
                          <td className="px-3 py-2 text-center">
                            {precioEditing?.productoId === p.id ? (
                              <div className="flex items-center gap-1 justify-center">
                                <span className="text-xs text-gray-400">$</span>
                                <input
                                  type="text"
                                  inputMode="numeric"
                                  value={conMiles(precioEditing.valor)}
                                  onChange={e => setPrecioEditing(pe => pe ? { ...pe, valor: soloDigitos(e.target.value) } : null)}
                                  className="w-20 border border-gray-300 rounded px-1.5 py-1 text-xs text-right font-semibold focus:outline-none focus:ring-2"
                                  style={{ '--tw-ring-color': 'oklch(48% 0.12 155)' } as React.CSSProperties}
                                  autoFocus
                                  onKeyDown={e => { if (e.key === 'Enter') guardarPrecio(); if (e.key === 'Escape') setPrecioEditing(null) }}
                                />
                                <button onClick={guardarPrecio} className="text-green-600 hover:text-green-700"><Check size={11} /></button>
                                <button onClick={() => setPrecioEditing(null)} className="text-gray-400 hover:text-gray-600"><X size={11} /></button>
                              </div>
                            ) : (
                              <button
                                onClick={() => setPrecioEditing({ productoId: p.id, valor: String(Math.round(p.precio_venta ?? 0)) })}
                                className="flex items-center gap-1 mx-auto text-xs font-semibold transition-colors px-2 py-1 rounded-lg hover:bg-green-50"
                                style={{ color: p.precio_venta ? 'oklch(38% 0.12 155)' : 'oklch(65% 0.01 60)' }}
                                title="Editar precio POS"
                              >
                                <Tag size={10} />
                                {p.precio_venta ? `$${p.precio_venta.toLocaleString('es-CO')}` : 'Sin precio'}
                              </button>
                            )}
                          </td>
                          <td className="px-3 py-2 text-center">
                            <button
                              onClick={() => toggleConteo(p)}
                              title={p.incluir_en_conteo ? 'Excluir del conteo' : 'Incluir en el conteo'}
                              className="relative inline-flex h-5 w-9 flex-shrink-0 rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none"
                              style={{ background: p.incluir_en_conteo !== false ? 'oklch(50% 0.14 155)' : 'oklch(75% 0.005 60)' }}>
                              <span
                                className="inline-block h-4 w-4 transform rounded-full bg-white shadow transition duration-200"
                                style={{ transform: p.incluir_en_conteo !== false ? 'translateX(16px)' : 'translateX(0px)' }}
                              />
                            </button>
                          </td>
                          <td className="px-3 py-2">
                            <div className="flex items-center gap-1">
                              <button
                                onClick={() => { setEditandoId(p.id); setEditForm({ nombre: p.nombre, categoria: p.categoria, unidad_medida: p.unidad_medida, controla_stock: p.controla_stock, envase: p.fraccionable ? (p.envase === 'botella' ? 'botella' : 'bolsa') : '' }) }}
                                className="p-1.5 rounded-lg border-2 border-gray-200 text-gray-400 hover:border-gray-300 hover:text-gray-600 transition-colors">
                                <Pencil size={12} />
                              </button>
                              <button
                                onClick={() => setRecetaEditing({ id: p.id, nombre: p.nombre })}
                                title="Receta de consumo (insumos que descuenta cada venta)"
                                className="p-1.5 rounded-lg border-2 border-gray-200 text-gray-400 hover:border-gray-300 hover:text-gray-600 transition-colors">
                                <ChefHat size={12} />
                              </button>
                            </div>
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

      {recetaEditing && (
        <RecetaModal
          producto={recetaEditing}
          productos={productos}
          onClose={() => setRecetaEditing(null)}
        />
      )}
    </div>
  )
}
