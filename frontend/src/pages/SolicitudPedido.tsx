import { useEffect, useMemo, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { Send, AlertTriangle, Zap, Search, ClipboardList, Check } from 'lucide-react'
import BaristaLayout from '../components/BaristaLayout'

interface Producto {
  id: number; nombre: string; unidad_medida: string
  incluir_en_conteo?: boolean; grupo_conteo?: string | null
}
interface Item { producto_id: number; nombre: string; unidad_medida: string; cantidad: string }

const UNIDADES = ['unidad', 'gr', 'kg', 'lt', 'ml', 'paquete', 'caja', 'bolsa', 'botella']
interface Alerta {
  producto_id: number; producto: string; unidad: string
  stock_actual: number; stock_minimo: number; cantidad_sugerida: number
}

export default function SolicitudPedido() {
  const { user } = useAuth()
  const [productos, setProductos] = useState<Producto[]>([])
  const [alertas, setAlertas] = useState<Alerta[]>([])
  const [items, setItems] = useState<Item[]>([])
  const [busqueda, setBusqueda] = useState('')
  const [nota, setNota] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [sending, setSending] = useState(false)
  // Modo dual: pedir reposición o contar existencia (sobre todo lo que NO entra
  // al conteo diario: vasos, tapas, helado). La existencia se registra como conteo
  // que compara vs sistema sin tocar stock — el admin decide si aplicarlo.
  const [modo, setModo] = useState<'pedido' | 'existencia'>('pedido')
  const [existencias, setExistencias] = useState<Record<number, string>>({})
  const [soloFueraConteo, setSoloFueraConteo] = useState(true)

  useEffect(() => {
    api.get('/inventario/productos').then(r => setProductos(r.data))
    if (user?.tienda_id) {
      api.get(`/inventario/alertas/${user.tienda_id}`)
        .then(r => setAlertas(r.data))
        .catch(() => {})
    }
  }, [user?.tienda_id])

  const agregar = (producto_id: number, nombre: string, unidad_medida: string, cantidad: number | string = 1) => {
    setItems(prev => {
      const existe = prev.find(i => i.producto_id === producto_id)
      if (existe) return prev
      return [...prev, { producto_id, nombre, unidad_medida, cantidad: String(cantidad) }]
    })
  }

  const setCantidad = (id: number, v: string) =>
    setItems(prev => prev.map(i => i.producto_id === id ? { ...i, cantidad: v } : i))

  const setUnidad = (id: number, u: string) =>
    setItems(prev => prev.map(i => i.producto_id === id ? { ...i, unidad_medida: u } : i))

  const quitar = (id: number) => setItems(prev => prev.filter(i => i.producto_id !== id))

  const agregarTodosCriticos = () => {
    alertas.forEach(a => agregar(a.producto_id, a.producto, a.unidad, Math.round(a.cantidad_sugerida)))
  }

  const invalido = (c: string) => !(Number(c) > 0)
  const hayInvalidos = items.some(i => invalido(i.cantidad))

  const enviar = async () => {
    setError(''); setSuccess('')
    if (items.length === 0) { setError('Agregá al menos un producto'); return }
    if (hayInvalidos) {
      // El error va JUNTO al botón (antes solo arriba, fuera de vista en el kiosko):
      // la barista tocaba enviar y "no pasaba nada" porque no veía el mensaje.
      const malos = items.filter(i => invalido(i.cantidad)).map(i => i.nombre)
      setError(`Poné una cantidad mayor a 0 en: ${malos.join(', ')}`)
      return
    }
    setSending(true)
    try {
      await api.post('/solicitudes/pedido', {
        tienda_id: user?.tienda_id,
        nota: nota || null,
        items: items.map(i => ({
          producto_id: i.producto_id,
          cantidad_solicitada: Number(i.cantidad),
          unidad_solicitada: i.unidad_medida,
        })),
      })
      setItems([]); setNota('')
      setSuccess('Solicitud enviada al administrador')
    } catch (e: any) {
      setError(e.response?.data?.detail || 'No se pudo enviar. Revisá tu conexión y reintentá.')
    } finally { setSending(false) }
  }

  // Productos para el modo existencia: por defecto los que NO entran al conteo diario.
  const productosExistencia = useMemo(() => productos
    .filter(p => !soloFueraConteo || p.incluir_en_conteo === false)
    .filter(p => p.nombre.toLowerCase().includes(busqueda.toLowerCase())),
    [productos, soloFueraConteo, busqueda])
  const nContados = Object.values(existencias).filter(v => v !== '' && Number(v) >= 0).length

  const enviarExistencia = async () => {
    setError(''); setSuccess('')
    const items = Object.entries(existencias)
      .filter(([, v]) => v !== '' && Number(v) >= 0)
      .map(([pid, v]) => ({ producto_id: Number(pid), cantidad_real: Number(v) }))
    if (items.length === 0) { setError('Contá al menos un producto'); return }
    setSending(true)
    try {
      await api.post('/conteos/existencia', {
        tienda_id: user?.tienda_id, tipo: 'existencia', items,
      })
      setExistencias({})
      setSuccess(`Existencia registrada: ${items.length} producto${items.length !== 1 ? 's' : ''}. El administrador la puede ver en el monitor.`)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'No se pudo registrar. Revisá tu conexión y reintentá.')
    } finally { setSending(false) }
  }

  return (
    <BaristaLayout title="Pedido y existencia">
    <div className="space-y-4">
      <h1 className="text-base font-bold text-gray-800">
        {modo === 'pedido' ? 'Solicitar pedido' : 'Contar existencia'}
      </h1>

      {/* Toggle de modo */}
      <div className="flex gap-2 bg-gray-100 p-1 rounded-xl">
        <button onClick={() => { setModo('pedido'); setError(''); setSuccess('') }}
          className={`flex-1 py-2 rounded-lg text-sm font-semibold flex items-center justify-center gap-1.5 transition-colors ${
            modo === 'pedido' ? 'bg-white shadow-sm text-amber-700' : 'text-gray-500'}`}>
          <Send size={13} /> Pedir
        </button>
        <button onClick={() => { setModo('existencia'); setError(''); setSuccess('') }}
          className={`flex-1 py-2 rounded-lg text-sm font-semibold flex items-center justify-center gap-1.5 transition-colors ${
            modo === 'existencia' ? 'bg-white shadow-sm text-forest' : 'text-gray-500'}`}>
          <ClipboardList size={13} /> Contar existencia
        </button>
      </div>

      {error && <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl">{error}</div>}
      {success && <div className="bg-green-50 border border-green-200 text-green-700 text-sm px-4 py-3 rounded-xl">{success}</div>}

      {/* ══════════ MODO EXISTENCIA ══════════ */}
      {modo === 'existencia' && (
        <>
          <p className="text-xs text-gray-500">
            Contá lo que hay físicamente — sobre todo lo que no entra al conteo diario (vasos, tapas, helado).
            No modifica el inventario: queda registrado para que el administrador lo revise.
          </p>
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <div className="px-3 py-2.5 border-b border-gray-100 space-y-2">
              <div className="relative">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <input value={busqueda} onChange={e => setBusqueda(e.target.value)} placeholder="Buscar producto…"
                  className="w-full pl-9 pr-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-forest" />
              </div>
              <label className="flex items-center gap-2 text-xs text-gray-500">
                <input type="checkbox" checked={soloFueraConteo} onChange={e => setSoloFueraConteo(e.target.checked)} />
                Solo lo que no entra al conteo diario
              </label>
            </div>
            <div className="divide-y divide-gray-50 max-h-[55vh] overflow-y-auto">
              {productosExistencia.map(p => {
                const v = existencias[p.id] ?? ''
                const contado = v !== '' && Number(v) >= 0
                return (
                  <div key={p.id} className="flex items-center gap-2 px-4 py-3">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-800 truncate">{p.nombre}</p>
                      {p.incluir_en_conteo === false && (
                        <span className="text-[10px] text-forest bg-forest-50 px-1.5 py-0.5 rounded-full">fuera del conteo diario</span>
                      )}
                    </div>
                    <input type="number" inputMode="decimal" min={0} value={v}
                      onChange={e => setExistencias(prev => ({ ...prev, [p.id]: e.target.value }))}
                      placeholder="—"
                      className={`w-20 text-right rounded-lg border-2 px-2 py-1.5 text-sm font-bold font-mono focus:outline-none ${
                        contado ? 'border-forest bg-forest-50 text-forest' : 'border-gray-200 focus:border-forest'}`} />
                    <span className="text-xs text-gray-400 w-8">{p.unidad_medida}</span>
                  </div>
                )
              })}
              {productosExistencia.length === 0 && (
                <p className="px-4 py-8 text-sm text-gray-400 text-center">Sin productos con ese filtro</p>
              )}
            </div>
          </div>

          {nContados > 0 && (
            <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3 sticky bottom-2">
              <p className="text-xs text-gray-500">{nContados} producto{nContados !== 1 ? 's' : ''} contado{nContados !== 1 ? 's' : ''}</p>
              <button onClick={enviarExistencia} disabled={sending}
                className="w-full bg-forest hover:bg-forest-700 disabled:opacity-50 text-white font-semibold py-2.5 rounded-lg text-sm flex items-center justify-center gap-2">
                <Check size={15} /> {sending ? 'Registrando…' : 'Registrar existencia'}
              </button>
            </div>
          )}
        </>
      )}

      {/* ══════════ MODO PEDIDO ══════════ */}
      {modo === 'pedido' && <>
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
                      Stock: <span className="font-bold">{Math.round(a.stock_actual)}</span> {a.unidad}
                      <span className="text-gray-400"> · mín {Math.round(a.stock_minimo)}</span>
                    </p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-xs text-amber-700 bg-amber-100 px-2 py-0.5 rounded-full font-semibold">
                      sugerido: {Math.round(a.cantidad_sugerida)}
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
              <div key={item.producto_id} className="flex items-center gap-2 px-4 py-3">
                <p className="flex-1 min-w-0 text-sm font-medium text-gray-800 truncate">{item.nombre}</p>
                <input
                  type="number" inputMode="decimal" min={0}
                  value={item.cantidad}
                  onChange={e => setCantidad(item.producto_id, e.target.value)}
                  placeholder="0"
                  className={`w-16 text-right rounded-lg border-2 px-2 py-1.5 text-sm font-bold font-mono focus:outline-none ${
                    invalido(item.cantidad)
                      ? 'border-red-300 bg-red-50 text-red-600 focus:border-red-400'
                      : 'border-gray-200 focus:border-amber-400'
                  }`}
                />
                <select
                  value={item.unidad_medida}
                  onChange={e => setUnidad(item.producto_id, e.target.value)}
                  className="rounded-lg border-2 border-gray-200 px-1.5 py-1.5 text-xs bg-white focus:outline-none focus:border-amber-400">
                  {/* la unidad del producto siempre disponible aunque no esté en la lista */}
                  {[...new Set([item.unidad_medida, ...UNIDADES])].map(u => (
                    <option key={u} value={u}>{u}</option>
                  ))}
                </select>
                <button onClick={() => quitar(item.producto_id)} className="text-xs text-red-400 hover:text-red-600" aria-label="Quitar">✕</button>
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
          {/* Feedback JUNTO al botón — así la barista siempre ve por qué no se envió */}
          {error && <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-3 py-2 rounded-lg">{error}</div>}
          <button onClick={enviar} disabled={sending}
            className="w-full bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white font-semibold py-2.5 rounded-lg text-sm flex items-center justify-center gap-2">
            <Send size={14} /> {sending ? 'Enviando…' : 'Enviar solicitud'}
          </button>
        </div>
      )}

      {/* Lista de todos los productos */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-3 py-2.5 border-b border-gray-100">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              value={busqueda}
              onChange={e => setBusqueda(e.target.value)}
              placeholder="Buscar producto…"
              className="w-full pl-9 pr-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
            />
          </div>
        </div>
        <div className="divide-y divide-gray-50 max-h-[50vh] overflow-y-auto">
          {productos
            .filter(p => p.nombre.toLowerCase().includes(busqueda.toLowerCase()))
            .map(p => {
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
      </>}
    </div>
    </BaristaLayout>
  )
}
