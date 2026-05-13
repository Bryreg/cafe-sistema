import { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import BaristaLayout from '../components/BaristaLayout'
import { AlertTriangle, CheckCircle, RefreshCw } from 'lucide-react'

interface InvItem {
  producto_id: number
  producto_nombre: string
  categoria: string
  unidad_medida: string
  stock_actual: number
}

interface ItemConteo {
  producto_id: number
  nombre: string
  categoria: string
  unidad_medida: string
  cantidad_sistema: number
  cantidad_real: string
}

const CAT_LABEL: Record<string, string> = {
  pasteleria: 'Pastelería',
  bebida: 'Bebidas',
  insumo: 'Insumos',
}

export default function ConteoCompras() {
  const { user } = useAuth()
  const [items, setItems] = useState<ItemConteo[]>([])
  const [nota, setNota] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [exito, setExito] = useState(false)

  const cargar = async () => {
    if (!user?.tienda_id) return
    setLoading(true)
    try {
      const { data } = await api.get<InvItem[]>(`/inventario/tienda/${user.tienda_id}`)
      setItems(data.map(i => ({
        producto_id: i.producto_id,
        nombre: i.producto_nombre,
        categoria: i.categoria,
        unidad_medida: i.unidad_medida,
        cantidad_sistema: i.stock_actual,
        cantidad_real: '',
      })))
    } finally { setLoading(false) }
  }

  useEffect(() => { cargar() }, [user])

  const actualizar = (producto_id: number, valor: string) => {
    setItems(prev => prev.map(i => i.producto_id === producto_id ? { ...i, cantidad_real: valor } : i))
  }

  const guardar = async () => {
    if (!user?.tienda_id) return
    const itemsCompletados = items.filter(i => i.cantidad_real !== '')
    if (itemsCompletados.length === 0) {
      setError('Debes contar al menos un producto'); return
    }
    setError(''); setSaving(true)
    try {
      await api.post('/compras/conteo', {
        tienda_id: user.tienda_id,
        fecha_conteo: new Date().toISOString(),
        nota: nota.trim() || null,
        items: itemsCompletados.map(i => ({
          producto_id: i.producto_id,
          cantidad_real: Math.round(Number(i.cantidad_real)),
        })),
      })
      setExito(true)
      setNota('')
      setItems(prev => prev.map(i => ({ ...i, cantidad_real: '' })))
      setTimeout(() => setExito(false), 4000)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al guardar')
    } finally { setSaving(false) }
  }

  const porCategoria = Object.entries(CAT_LABEL).map(([key, label]) => ({
    key, label, items: items.filter(i => i.categoria === key),
  })).filter(g => g.items.length > 0)

  if (loading) return (
    <BaristaLayout title="Conteo para Compras">
      <div className="flex justify-center py-16">
        <p className="text-sm text-gray-400 animate-pulse">Cargando inventario...</p>
      </div>
    </BaristaLayout>
  )

  return (
    <BaristaLayout title="Conteo para Compras">
      <div className="space-y-4 pb-8">

        {/* Instrucción */}
        <div className="bg-amber-50 border border-amber-200 rounded-2xl px-4 py-3">
          <p className="text-sm font-semibold text-amber-800">¿Cómo funciona?</p>
          <p className="text-xs text-amber-700 mt-1">
            Cuenta físicamente los productos en tienda e ingresa la cantidad real.
            El admin revisará las diferencias y ajustará el stock antes de hacer el pedido.
            Solo necesitas contar los que vas a revisar.
          </p>
        </div>

        {exito && (
          <div className="flex items-center gap-2 bg-green-50 border border-green-200 text-green-700 rounded-2xl px-4 py-3 text-sm font-semibold">
            <CheckCircle size={16} /> Conteo enviado. El admin ajustará el stock.
          </div>
        )}
        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-600 rounded-2xl px-4 py-3 text-sm">
            <AlertTriangle size={15} /> {error}
          </div>
        )}

        {/* Tabla por categoría */}
        {porCategoria.map(grupo => (
          <div key={grupo.key} className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
            <div className="px-4 py-2.5 bg-gray-50 border-b border-gray-100 flex items-center justify-between">
              <p className="text-xs font-bold text-gray-500 uppercase tracking-wide">{grupo.label}</p>
              <p className="text-xs text-gray-400">Sistema → Real</p>
            </div>
            <div className="divide-y divide-gray-50">
              {grupo.items.map(item => {
                const real = item.cantidad_real !== '' ? Number(item.cantidad_real) : null
                const diferencia = real !== null ? real - item.cantidad_sistema : null
                const difColor = diferencia === null ? '' :
                  diferencia < 0 ? 'text-red-600' :
                  diferencia > 0 ? 'text-blue-600' : 'text-green-600'

                return (
                  <div key={item.producto_id} className="px-4 py-3 flex items-center gap-3">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-800 truncate">{item.nombre}</p>
                      <p className="text-xs text-gray-400">{item.unidad_medida}</p>
                    </div>
                    {/* Cantidad sistema (referencia) */}
                    <div className="text-center w-12 shrink-0">
                      <p className="text-sm font-bold text-gray-400">{Math.round(item.cantidad_sistema)}</p>
                      <p className="text-xs text-gray-300">sist.</p>
                    </div>
                    {/* Input cantidad real */}
                    <input
                      type="number"
                      step="1"
                      min="0"
                      value={item.cantidad_real}
                      onChange={e => actualizar(item.producto_id, e.target.value)}
                      placeholder="—"
                      className="w-20 border-2 border-gray-200 rounded-xl px-2 py-2 text-sm font-bold text-center focus:outline-none focus:border-amber-400"
                    />
                    {/* Diferencia */}
                    {diferencia !== null && (
                      <div className={`w-10 text-center shrink-0 text-sm font-bold ${difColor}`}>
                        {diferencia > 0 ? `+${Math.round(diferencia)}` : Math.round(diferencia)}
                      </div>
                    )}
                    {diferencia === null && <div className="w-10 shrink-0" />}
                  </div>
                )
              })}
            </div>
          </div>
        ))}

        {/* Nota opcional */}
        <div className="bg-white rounded-2xl border border-gray-200 p-4">
          <label className="text-xs font-bold text-gray-500 uppercase tracking-wide block mb-2">
            Nota (opcional)
          </label>
          <textarea value={nota} onChange={e => setNota(e.target.value)}
            placeholder="Ej: Faltan insumos de pastelería, pedido urgente..."
            rows={2}
            className="w-full border-2 border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-amber-400 resize-none" />
        </div>

        <div className="flex gap-3">
          <button onClick={cargar}
            className="flex items-center gap-1.5 px-4 py-3 border-2 border-gray-200 rounded-xl text-sm font-semibold text-gray-500 hover:bg-gray-50 transition-colors">
            <RefreshCw size={14} /> Recargar
          </button>
          <button onClick={guardar} disabled={saving}
            className="flex-1 bg-amber-600 hover:bg-amber-700 disabled:opacity-40 text-white font-bold py-3 rounded-xl text-sm transition-colors">
            {saving ? 'Enviando...' : 'Enviar Conteo al Admin'}
          </button>
        </div>
      </div>
    </BaristaLayout>
  )
}
