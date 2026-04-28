import { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { Plus, Minus, Send, AlertTriangle, Zap } from 'lucide-react'
import BaristaLayout from '../components/BaristaLayout'

interface Producto { id: number; nombre: string; unidad_medida: string }
interface Item { producto_id: number; nombre: string; unidad_medida: string; cantidad: number }
interface Alerta {
  producto_id: number; producto: string; unidad: string
  stock_actual: number; stock_minimo: number; cantidad_sugerida: number
}

export default function SolicitudPedido() {
  const { user } = useAuth()
  const [productos, setProductos] = useState<Producto[]>([])
  const [alertas, setAlertas] = useState<Alerta[]>([])
  const [items, setItems] = useState<Item[]>([])
  const [nota, setNota] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    api.get('/inventario/productos').then(r => setProductos(r.data))
    if (user?.tienda_id) {
      api.get(`/inventario/alertas/${user.tienda_id}`)
        .then(r => setAlertas(r.data))
        .catch(() => {})
    }
  }, [user?.tienda_id])

  const agregar = (producto_id: number, nombre: string, unidad_medida: string, cantidad = 1) => {
    setItems(prev => {
      const existe = prev.find(i => i.producto_id === producto_id)
      if (existe) return prev
      return [...prev, { producto_id, nombre, unidad_medida, cantidad }]
    })
  }

  const ajustar = (id: number, delta: number) => {
    setItems(prev => prev.map(i =>
      i.producto_id === id ? { ...i, cantidad: Math.max(1, i.cantidad + delta) } : i
    ))
  }

  const quitar = (id: number) => setItems(prev => prev.filter(i => i.producto_id !== id))

  const agregarTodosCriticos = () => {
    alertas.forEach(a => agregar(a.producto_id, a.producto, a.unidad, a.cantidad_sugerida))
  }

  const enviar = async () => {
    setError(''); setSuccess('')
    try {
      await api.post('/solicitudes/pedido', {
        tienda_id: user?.tienda_id,
        nota: nota || null,
        items: items.map(i => ({ producto_id: i.producto_id, cantidad_solicitada: i.cantidad })),
      })
      setItems([]); setNota('')
      setSuccess('Solicitud enviada al administrador')
    } catch (e: any) { setError(e.response?.data?.detail || 'Error') }
  }

  return (
    <BaristaLayout title="Solicitar pedido">
    <div className="space-y-4">
      <h1 className="text-base font-bold text-gray-800">Solicitar pedido</h1>

      {error && <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl">{error}</div>}
      {success && <div className="bg-green-50 border border-green-200 text-green-700 text-sm px-4 py-3 rounded-xl">{success}</div>}

      {/* Productos críticos con sugerencia */}
      {alertas.length > 0 && (
        <div className="bg-red-50 border border-red-200 rounded-xl overflow-hidden">
          <div className="px-4 py-2.5 border-b border-red-200 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <AlertTriangle size={13} className="text-red-600" />
              <p className="text-xs font-semibold text-red-700 uppercase tracking-wide">
                {alertas.length} producto{alertas.length > 1 ? 's' : ''} con stock bajo
              </p>
            </div>
            <button onClick={agregarTodosCriticos}
              className="flex items-center gap-1 text-xs bg-red-600 hover:bg-red-700 text-white px-2.5 py-1 rounded-lg font-semibold">
              <Zap size={11} /> Agregar todos
            </button>
          </div>
          <div className="divide-y divide-red-100">
            {alertas.map(a => {
              const yaAgregado = !!items.find(i => i.producto_id === a.producto_id)
              return (
                <div key={a.producto_id} className="px-4 py-3 flex items-center justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-gray-800">{a.producto}</p>
                    <p className="text-xs text-red-600">
                      Stock: <span className="font-bold">{a.stock_actual}</span> {a.unidad}
                      <span className="text-gray-400"> · mín {a.stock_minimo}</span>
                    </p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-xs text-amber-700 bg-amber-100 px-2 py-0.5 rounded-full font-semibold">
                      sugerido: {a.cantidad_sugerida}
                    </span>
                    <button
                      onClick={() => agregar(a.producto_id, a.producto, a.unidad, a.cantidad_sugerida)}
                      disabled={yaAgregado}
                      className={`text-xs px-2.5 py-1 rounded-lg font-semibold transition-colors ${
                        yaAgregado
                          ? 'bg-green-100 text-green-700 cursor-default'
                          : 'bg-red-600 hover:bg-red-700 text-white'
                      }`}
                    >
                      {yaAgregado ? '✓' : '+ pedir'}
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Productos seleccionados */}
      {items.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="px-4 py-2.5 border-b border-gray-100">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
              Productos solicitados ({items.length})
            </p>
          </div>
          <div className="divide-y divide-gray-50">
            {items.map(item => (
              <div key={item.producto_id} className="flex items-center gap-3 px-4 py-3">
                <p className="flex-1 text-sm font-medium text-gray-800">{item.nombre}</p>
                <div className="flex items-center gap-2">
                  <button onClick={() => ajustar(item.producto_id, -1)} className="p-1 rounded-lg bg-gray-100 hover:bg-gray-200">
                    <Minus size={12} />
                  </button>
                  <span className="text-sm font-bold w-8 text-center">{item.cantidad}</span>
                  <button onClick={() => ajustar(item.producto_id, 1)} className="p-1 rounded-lg bg-gray-100 hover:bg-gray-200">
                    <Plus size={12} />
                  </button>
                  <span className="text-xs text-gray-400 w-12">{item.unidad_medida}</span>
                  <button onClick={() => quitar(item.producto_id)} className="text-xs text-red-400 hover:text-red-600 ml-1">✕</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Nota y enviar */}
      {items.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
          <textarea value={nota} onChange={e => setNota(e.target.value)} rows={2}
            placeholder="Nota al administrador (opcional)"
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400 resize-none" />
          <button onClick={enviar}
            className="w-full bg-amber-600 hover:bg-amber-700 text-white font-semibold py-2.5 rounded-lg text-sm flex items-center justify-center gap-2">
            <Send size={14} /> Enviar solicitud
          </button>
        </div>
      )}

      {/* Lista de todos los productos */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-4 py-2.5 border-b border-gray-100">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Todos los productos</p>
        </div>
        <div className="divide-y divide-gray-50">
          {productos.map(p => {
            const ya = items.find(i => i.producto_id === p.id)
            const critico = alertas.find(a => a.producto_id === p.id)
            return (
              <button key={p.id} onClick={() => agregar(p.id, p.nombre, p.unidad_medida)}
                className={`w-full flex items-center justify-between px-4 py-3 text-left hover:bg-gray-50 ${ya ? 'opacity-40' : ''}`}>
                <div className="flex items-center gap-2">
                  {critico && <span className="w-1.5 h-1.5 rounded-full bg-red-500 shrink-0" />}
                  <p className="text-sm font-medium text-gray-800">{p.nombre}</p>
                </div>
                <span className="text-xs text-gray-400">{ya ? '✓' : '+ agregar'}</span>
              </button>
            )
          })}
        </div>
      </div>
    </div>
    </BaristaLayout>
  )
}
