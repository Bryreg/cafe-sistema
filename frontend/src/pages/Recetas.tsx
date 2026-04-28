import { useEffect, useState } from 'react'
import api from '../api/client'
import { Plus, Pencil, Trash2, Check, X, ChefHat, AlertTriangle } from 'lucide-react'

interface Ingrediente { id?: number; producto_id: number; producto_nombre: string; unidad_medida: string; cantidad: number }
interface Receta { id: number; nombre: string; categoria: string; precio_venta: number | null; activa: boolean; ingredientes: Ingrediente[]; food_cost_pct: number | null }
interface Producto { id: number; nombre: string; unidad_medida: string; categoria: string }

const CATS = ['bebida', 'pasteleria', 'comida'] as const
type Cat = typeof CATS[number]
const CAT_LABEL: Record<Cat, string> = { bebida: 'Bebidas', pasteleria: 'Pastelería', comida: 'Comidas' }
const CAT_COLOR: Record<Cat, { bg: string; text: string }> = {
  bebida:     { bg: 'oklch(95% 0.015 155)', text: 'oklch(30% 0.10 155)' },
  pasteleria: { bg: 'oklch(96% 0.015 60)',  text: 'oklch(40% 0.12 55)'  },
  comida:     { bg: 'oklch(95% 0.015 245)', text: 'oklch(30% 0.12 245)' },
}

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`

function foodCostColor(pct: number) {
  if (pct <= 30) return 'oklch(38% 0.14 145)'
  if (pct <= 40) return 'oklch(50% 0.15 75)'
  return 'oklch(45% 0.18 25)'
}

interface FormState { nombre: string; categoria: Cat; precio_venta: string; ingredientes: { producto_id: number; cantidad: string; nombre: string; unidad: string }[] }
const emptyForm = (): FormState => ({ nombre: '', categoria: 'bebida', precio_venta: '', ingredientes: [] })

export default function Recetas() {
  const [recetas, setRecetas] = useState<Receta[]>([])
  const [productos, setProductos] = useState<Producto[]>([])
  const [editandoId, setEditandoId] = useState<number | 'nuevo' | null>(null)
  const [form, setForm] = useState<FormState>(emptyForm())
  const [busqProd, setBusqProd] = useState('')
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const load = async () => {
    const [rec, prod] = await Promise.all([
      api.get('/recetas/todas'),
      api.get('/inventario/productos'),
    ])
    setRecetas(rec.data)
    setProductos(prod.data)
  }

  useEffect(() => { load() }, [])

  const prodFiltrados = productos.filter(p =>
    p.nombre.toLowerCase().includes(busqProd.toLowerCase())
  ).slice(0, 20)

  const abrirNuevo = () => {
    setForm(emptyForm())
    setEditandoId('nuevo')
    setBusqProd('')
    setError('')
  }

  const abrirEditar = (r: Receta) => {
    setForm({
      nombre: r.nombre,
      categoria: r.categoria as Cat,
      precio_venta: r.precio_venta ? String(r.precio_venta) : '',
      ingredientes: r.ingredientes.map(i => ({
        producto_id: i.producto_id,
        cantidad: String(i.cantidad),
        nombre: i.producto_nombre,
        unidad: i.unidad_medida,
      })),
    })
    setEditandoId(r.id)
    setBusqProd('')
    setError('')
  }

  const agregarIngrediente = (p: Producto) => {
    if (form.ingredientes.find(i => i.producto_id === p.id)) return
    setForm(f => ({ ...f, ingredientes: [...f.ingredientes, { producto_id: p.id, cantidad: '1', nombre: p.nombre, unidad: p.unidad_medida }] }))
    setBusqProd('')
  }

  const quitarIngrediente = (idx: number) =>
    setForm(f => ({ ...f, ingredientes: f.ingredientes.filter((_, i) => i !== idx) }))

  const setCantidadIng = (idx: number, val: string) =>
    setForm(f => ({ ...f, ingredientes: f.ingredientes.map((i, n) => n === idx ? { ...i, cantidad: val } : i) }))

  const guardar = async () => {
    if (!form.nombre.trim()) { setError('El nombre es obligatorio'); return }
    setSaving(true); setError('')
    try {
      const body = {
        nombre: form.nombre,
        categoria: form.categoria,
        precio_venta: form.precio_venta ? Number(form.precio_venta) : null,
        ingredientes: form.ingredientes.map(i => ({ producto_id: i.producto_id, cantidad: Number(i.cantidad) })),
      }
      if (editandoId === 'nuevo') {
        await api.post('/recetas/', body)
      } else {
        await api.patch(`/recetas/${editandoId}`, body)
      }
      setEditandoId(null)
      load()
    } catch (e: any) { setError(e.response?.data?.detail || 'Error al guardar') }
    finally { setSaving(false) }
  }

  const archivar = async (id: number) => {
    await api.delete(`/recetas/${id}`)
    load()
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Recetas / Escandallos</h1>
          <p className="text-sm text-gray-400">{recetas.filter(r => r.activa).length} activas</p>
        </div>
        <button onClick={abrirNuevo}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-bold text-white"
          style={{ background: 'oklch(48% 0.12 155)' }}>
          <Plus size={15} /> Nueva receta
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl">
          <AlertTriangle size={14} /> {error}
          <button onClick={() => setError('')} className="ml-auto"><X size={13} /></button>
        </div>
      )}

      {/* Formulario nuevo / editar */}
      {editandoId !== null && (
        <div className="bg-white rounded-2xl border-2 p-5 space-y-4" style={{ borderColor: 'oklch(48% 0.12 155)' }}>
          <p className="text-sm font-bold text-gray-800">{editandoId === 'nuevo' ? 'Nueva receta' : 'Editar receta'}</p>

          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <label className="text-xs font-semibold text-gray-500 block mb-1">Nombre</label>
              <input value={form.nombre} onChange={e => setForm(f => ({ ...f, nombre: e.target.value }))}
                placeholder="Ej: Latte clásico 12oz" autoFocus
                className="w-full border-2 border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none" />
            </div>
            <div>
              <label className="text-xs font-semibold text-gray-500 block mb-1">Categoría</label>
              <select value={form.categoria} onChange={e => setForm(f => ({ ...f, categoria: e.target.value as Cat }))}
                className="w-full border-2 border-gray-200 rounded-xl px-3 py-2 text-sm">
                {CATS.map(c => <option key={c} value={c}>{CAT_LABEL[c]}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs font-semibold text-gray-500 block mb-1">Precio de venta (COP)</label>
              <input type="number" value={form.precio_venta} onChange={e => setForm(f => ({ ...f, precio_venta: e.target.value }))}
                placeholder="0" className="w-full border-2 border-gray-200 rounded-xl px-3 py-2 text-sm font-mono" />
            </div>
          </div>

          {/* Ingredientes ya agregados */}
          {form.ingredientes.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Ingredientes</p>
              {form.ingredientes.map((ing, idx) => (
                <div key={ing.producto_id} className="flex items-center gap-2 bg-gray-50 rounded-xl px-3 py-2">
                  <span className="text-sm font-medium text-gray-700 flex-1 truncate">{ing.nombre}</span>
                  <input type="number" value={ing.cantidad} onChange={e => setCantidadIng(idx, e.target.value)}
                    className="w-20 border border-gray-200 rounded-lg px-2 py-1 text-sm text-center font-mono"
                    min="0" step="0.1" />
                  <span className="text-xs text-gray-400 w-10">{ing.unidad}</span>
                  <button onClick={() => quitarIngrediente(idx)} className="text-gray-300 hover:text-red-500">
                    <X size={14} />
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Buscador de ingredientes */}
          <div>
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Agregar ingrediente</label>
            <input value={busqProd} onChange={e => setBusqProd(e.target.value)}
              placeholder="Buscar producto..." className="w-full border-2 border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none mb-2" />
            {busqProd.length > 0 && (
              <div className="border border-gray-200 rounded-xl overflow-hidden max-h-48 overflow-y-auto">
                {prodFiltrados.map(p => (
                  <button key={p.id} onClick={() => agregarIngrediente(p)}
                    disabled={!!form.ingredientes.find(i => i.producto_id === p.id)}
                    className="w-full text-left px-3 py-2 text-sm hover:bg-gray-50 flex items-center justify-between disabled:opacity-40 border-b border-gray-50 last:border-0">
                    <span className="font-medium text-gray-700">{p.nombre}</span>
                    <span className="text-xs text-gray-400">{p.unidad_medida}</span>
                  </button>
                ))}
                {prodFiltrados.length === 0 && <p className="text-xs text-gray-400 px-3 py-2">Sin resultados</p>}
              </div>
            )}
          </div>

          <div className="flex gap-2 pt-2">
            <button onClick={guardar} disabled={saving}
              className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-40"
              style={{ background: 'oklch(48% 0.12 155)' }}>
              <Check size={14} /> {saving ? 'Guardando...' : 'Guardar'}
            </button>
            <button onClick={() => setEditandoId(null)}
              className="px-4 py-2 rounded-xl text-sm font-semibold border-2 border-gray-200 text-gray-600">
              Cancelar
            </button>
          </div>
        </div>
      )}

      {/* Lista de recetas por categoría */}
      {CATS.map(cat => {
        const lista = recetas.filter(r => r.categoria === cat && r.activa)
        if (lista.length === 0) return null
        const cc = CAT_COLOR[cat]
        return (
          <div key={cat} className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
            <div className="px-4 py-2.5 border-b border-gray-100 flex items-center gap-2">
              <ChefHat size={14} style={{ color: cc.text }} />
              <p className="text-xs font-bold uppercase tracking-wide" style={{ color: cc.text }}>
                {CAT_LABEL[cat]} — {lista.length}
              </p>
            </div>
            <div className="divide-y divide-gray-50">
              {lista.map(r => (
                <div key={r.id}>
                  <button onClick={() => setExpandedId(expandedId === r.id ? null : r.id)}
                    className="w-full text-left px-4 py-3 hover:bg-gray-50 flex items-center justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-gray-800 truncate">{r.nombre}</p>
                      <p className="text-xs text-gray-400">{r.ingredientes.length} ingredientes</p>
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      {r.precio_venta && (
                        <span className="text-sm font-bold text-gray-700 font-mono">{fmt(r.precio_venta)}</span>
                      )}
                      {r.food_cost_pct !== null && (
                        <span className="text-xs font-bold px-2 py-0.5 rounded-lg text-white"
                          style={{ background: foodCostColor(r.food_cost_pct) }}>
                          {r.food_cost_pct}% FC
                        </span>
                      )}
                    </div>
                  </button>

                  {expandedId === r.id && (
                    <div className="bg-gray-50 border-t border-gray-100 px-4 py-3 space-y-3">
                      {r.ingredientes.length > 0 ? (
                        <div className="space-y-1">
                          {r.ingredientes.map(ing => (
                            <div key={ing.producto_id} className="flex items-center justify-between text-sm">
                              <span className="text-gray-700">{ing.producto_nombre}</span>
                              <span className="font-mono text-gray-600">{ing.cantidad} {ing.unidad_medida}</span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-xs text-gray-400">Sin ingredientes definidos.</p>
                      )}
                      <div className="flex gap-2 pt-1">
                        <button onClick={() => abrirEditar(r)}
                          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border-2 border-gray-200 text-gray-600 font-semibold hover:border-gray-300">
                          <Pencil size={11} /> Editar
                        </button>
                        <button onClick={() => archivar(r.id)}
                          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border-2 border-red-100 text-red-500 font-semibold hover:border-red-300">
                          <Trash2 size={11} /> Archivar
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )
      })}

      {recetas.filter(r => r.activa).length === 0 && editandoId === null && (
        <div className="text-center py-12 text-gray-400">
          <ChefHat size={32} className="mx-auto mb-3 opacity-30" />
          <p className="text-sm">Aún no hay recetas. Crea la primera.</p>
        </div>
      )}
    </div>
  )
}
