import { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { CheckCircle2, XCircle, ShoppingCart, Coins, Pencil } from 'lucide-react'

const BILLETES = [
  { valor: 2000,   label: '$2.000',   tipo: 'billete' },
  { valor: 5000,   label: '$5.000',   tipo: 'billete' },
  { valor: 10000,  label: '$10.000',  tipo: 'billete' },
  { valor: 20000,  label: '$20.000',  tipo: 'billete' },
  { valor: 50000,  label: '$50.000',  tipo: 'billete' },
  { valor: 100000, label: '$100.000', tipo: 'billete' },
]
const MONEDAS = [
  { valor: 50,   label: '$50',    tipo: 'moneda' },
  { valor: 100,  label: '$100',   tipo: 'moneda' },
  { valor: 200,  label: '$200',   tipo: 'moneda' },
  { valor: 500,  label: '$500',   tipo: 'moneda' },
  { valor: 1000, label: '$1.000', tipo: 'moneda' },
]
const TODAS = [...BILLETES, ...MONEDAS]

interface DetalleItem { label: string; tipo: string; valor: number; monto: number; cantidad: number }
interface PedidoItem { producto_id: number; cantidad_solicitada: number; nombre: string; unidad_medida: string }
interface Pedido { id: number; fecha_solicitud: string; estado: string; nota: string | null; items: PedidoItem[]; tienda_nombre?: string }
interface Sencilla { id: number; fecha_solicitud: string; estado: string; monto_solicitado: number; motivo: string; detalle: string | null; tienda_nombre?: string }

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`

// ─── Editor de denominaciones (mismo que vista barista) ───────────────────────
function EditorSencilla({ sencilla, onAprobar, onCancelar }: {
  sencilla: Sencilla
  onAprobar: (detalle: string, monto: number) => void
  onCancelar: () => void
}) {
  const init = (): Record<string, string> => {
    if (!sencilla.detalle) return {}
    try {
      const items: DetalleItem[] = JSON.parse(sencilla.detalle)
      const m: Record<string, string> = {}
      items.forEach(it => { m[`${it.tipo[0]}-${it.valor}`] = String(it.monto) })
      return m
    } catch { return {} }
  }

  const [montos, setMontos] = useState<Record<string, string>>(init)

  const key = (tipo: string, valor: number) => `${tipo[0]}-${valor}`
  const getMonto = (tipo: string, valor: number) => montos[key(tipo, valor)] ?? ''
  const setMonto = (tipo: string, valor: number, v: string) =>
    setMontos(prev => ({ ...prev, [key(tipo, valor)]: v }))

  const total = TODAS.reduce((s, d) => {
    const m = Number(montos[key(d.tipo, d.valor)]) || 0
    return s + (m % d.valor === 0 ? m : 0)
  }, 0)

  const hayErrores = TODAS.some(d => {
    const m = Number(montos[key(d.tipo, d.valor)]) || 0
    return m > 0 && m % d.valor !== 0
  })

  const confirmar = () => {
    const items: DetalleItem[] = TODAS.filter(d => {
      const m = Number(montos[key(d.tipo, d.valor)]) || 0
      return m > 0 && m % d.valor === 0
    }).map(d => {
      const m = Number(montos[key(d.tipo, d.valor)])
      return { label: d.label, tipo: d.tipo, valor: d.valor, monto: m, cantidad: m / d.valor }
    })
    onAprobar(JSON.stringify(items), total)
  }

  return (
    <div className="mt-3 border-2 border-amber-200 rounded-xl overflow-hidden">
      <div className="px-3 py-2 bg-amber-50 border-b border-amber-200">
        <p className="text-xs font-bold text-amber-700 uppercase tracking-wide">Ajustar denominaciones</p>
      </div>

      <div className="divide-y divide-gray-100 bg-white">
        {TODAS.map(d => {
          const m = Number(montos[key(d.tipo, d.valor)]) || 0
          const esMultiplo = m > 0 && m % d.valor === 0
          const esError    = m > 0 && m % d.valor !== 0
          const cantidad   = esMultiplo ? m / d.valor : null
          const esBillete  = d.tipo === 'billete'

          return (
            <div key={`${d.tipo}-${d.valor}`}
              className={`flex items-center gap-2 px-3 py-2 ${m > 0 ? (esBillete ? 'bg-green-50' : 'bg-amber-50') : ''}`}>
              <span className={`w-14 text-center py-0.5 rounded text-xs font-bold shrink-0 ${
                esBillete ? 'bg-green-100 text-green-800' : 'bg-amber-100 text-amber-800'
              }`}>{d.label}</span>

              <div className="flex-1 relative">
                <span className="absolute left-2 top-1/2 -translate-y-1/2 text-xs text-gray-400">$</span>
                <input
                  type="number"
                  value={getMonto(d.tipo, d.valor)}
                  onChange={e => setMonto(d.tipo, d.valor, e.target.value)}
                  placeholder="0"
                  step={d.valor}
                  inputMode="numeric"
                  className={`w-full pl-5 pr-2 py-1.5 text-sm font-bold border rounded-lg focus:outline-none transition-colors ${
                    esError ? 'border-red-300 text-red-700' : 'border-gray-200 focus:border-amber-400'
                  }`}
                />
              </div>

              <div className="w-20 text-right text-xs shrink-0">
                {esMultiplo
                  ? <span className="font-semibold text-gray-700">{cantidad} {d.tipo}{cantidad !== 1 ? 's' : ''}</span>
                  : esError
                  ? <span className="text-red-500">no válido</span>
                  : <span className="text-gray-300">—</span>}
              </div>
            </div>
          )
        })}
      </div>

      <div className="px-3 py-2 bg-gray-50 border-t border-gray-200 flex items-center justify-between">
        <span className="text-xs font-semibold text-gray-500">Total ajustado</span>
        <span className={`text-base font-bold ${total > 0 ? 'text-amber-700' : 'text-gray-300'}`}>
          {total > 0 ? fmt(total) : '$0'}
        </span>
      </div>

      <div className="flex gap-2 px-3 py-3 bg-gray-50 border-t border-gray-100">
        <button onClick={onCancelar}
          className="text-xs border border-gray-300 text-gray-600 hover:bg-gray-100 px-3 py-2 rounded-lg font-medium">
          Cancelar
        </button>
        <button onClick={confirmar} disabled={total === 0 || hayErrores}
          className="flex-1 flex items-center justify-center gap-1 text-xs bg-green-600 hover:bg-green-700 disabled:opacity-40 text-white px-3 py-2 rounded-lg font-semibold">
          <CheckCircle2 size={13} /> Aprobar {total > 0 && fmt(total)}
        </button>
      </div>
    </div>
  )
}

// ─── Página ───────────────────────────────────────────────────────────────────
export default function Bandeja() {
  const { user } = useAuth()
  const [pedidos, setPedidos] = useState<Pedido[]>([])
  const [sencillas, setSencillas] = useState<Sencilla[]>([])
  const [loading, setLoading] = useState(true)
  const [editando, setEditando] = useState<number | null>(null)

  const tienda_id = user?.tienda_id

  const load = async () => {
    const isAdmin = user?.rol === 'admin'
    if (!isAdmin && !tienda_id) return
    const [p, s] = await Promise.all([
      isAdmin
        ? api.get('/solicitudes/pedido/todas')
        : api.get(`/solicitudes/pedido/tienda/${tienda_id}`),
      isAdmin
        ? api.get('/solicitudes/sencilla/todas')
        : api.get(`/solicitudes/sencilla/tienda/${tienda_id}`),
    ])
    setPedidos(p.data)
    setSencillas(s.data)
    setLoading(false)
  }

  useEffect(() => { load() }, [tienda_id])

  const accionPedido = async (id: number, accion: 'aprobar' | 'rechazar') => {
    await api.patch(`/solicitudes/pedido/${id}/${accion}`)
    load()
  }

  const aprobarSencilla = async (id: number, detalle: string, monto: number) => {
    await api.patch(`/solicitudes/sencilla/${id}/aprobar`, { detalle, monto_solicitado: monto })
    setEditando(null)
    load()
  }

  const rechazarSencilla = async (id: number) => {
    await api.patch(`/solicitudes/sencilla/${id}/rechazar`)
    setEditando(null)
    load()
  }

  const estadoBadge = (estado: string) => (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
      estado === 'pendiente' ? 'bg-amber-100 text-amber-700' :
      estado === 'aprobada'  ? 'bg-green-100 text-green-700' :
                               'bg-red-100 text-red-700'
    }`}>{estado}</span>
  )

  if (loading) return <p className="text-sm text-gray-400 py-8 text-center">Cargando...</p>

  const pendientesPedidos   = pedidos.filter(p => p.estado === 'pendiente')
  const pendientesSencillas = sencillas.filter(s => s.estado === 'pendiente')

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-base font-bold text-gray-800">Bandeja</h1>
        {(pendientesPedidos.length + pendientesSencillas.length) > 0 && (
          <span className="text-xs bg-red-500 text-white px-2 py-0.5 rounded-full font-bold">
            {pendientesPedidos.length + pendientesSencillas.length} pendientes
          </span>
        )}
      </div>

      {/* Pedidos de insumos */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-2">
          <ShoppingCart size={14} className="text-blue-500" />
          <p className="text-sm font-semibold text-gray-700">Pedidos de insumos</p>
          {pendientesPedidos.length > 0 && (
            <span className="text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded-full">{pendientesPedidos.length}</span>
          )}
        </div>
        {pedidos.length === 0
          ? <p className="text-sm text-gray-400 px-4 py-3">Sin solicitudes</p>
          : (
            <div className="divide-y divide-gray-50">
              {pedidos.map(p => (
                <div key={p.id} className="px-4 py-3">
                  <div className="flex items-start justify-between mb-1">
                    <div>
                      <div className="flex items-center gap-2 mb-0.5">
                        <p className="text-xs text-gray-400">{new Date(p.fecha_solicitud).toLocaleString('es-CO')}</p>
                        {p.tienda_nombre && (
                          <span className="text-xs bg-blue-50 text-blue-600 border border-blue-200 px-1.5 py-0.5 rounded-full font-semibold">{p.tienda_nombre}</span>
                        )}
                      </div>
                      <div className="mt-1 space-y-0.5">
                        {p.items.map(item => (
                          <div key={item.producto_id} className="flex items-center justify-between text-xs">
                            <span className="text-gray-700 font-medium">{item.nombre}</span>
                            <span className="text-gray-500 ml-2">{item.cantidad_solicitada} {item.unidad_medida}</span>
                          </div>
                        ))}
                      </div>
                      {p.nota && <p className="text-xs italic text-gray-500 mt-1">{p.nota}</p>}
                    </div>
                    {estadoBadge(p.estado)}
                  </div>
                  {p.estado === 'pendiente' && (
                    <div className="flex gap-2 mt-2">
                      <button onClick={() => accionPedido(p.id, 'aprobar')}
                        className="flex items-center gap-1 text-xs bg-green-100 text-green-700 hover:bg-green-200 px-3 py-1.5 rounded-lg font-medium">
                        <CheckCircle2 size={12} /> Aprobar
                      </button>
                      <button onClick={() => accionPedido(p.id, 'rechazar')}
                        className="flex items-center gap-1 text-xs bg-red-100 text-red-700 hover:bg-red-200 px-3 py-1.5 rounded-lg font-medium">
                        <XCircle size={12} /> Rechazar
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )
        }
      </div>

      {/* Solicitudes de sencilla */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-2">
          <Coins size={14} className="text-amber-500" />
          <p className="text-sm font-semibold text-gray-700">Solicitudes de sencilla</p>
          {pendientesSencillas.length > 0 && (
            <span className="text-xs bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded-full">{pendientesSencillas.length}</span>
          )}
        </div>
        {sencillas.length === 0
          ? <p className="text-sm text-gray-400 px-4 py-3">Sin solicitudes</p>
          : (
            <div className="divide-y divide-gray-50">
              {sencillas.map(s => {
                let items: DetalleItem[] = []
                try { if (s.detalle) items = JSON.parse(s.detalle) } catch {}

                return (
                  <div key={s.id} className="px-4 py-3">
                    {/* Cabecera */}
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="flex items-center gap-2 mb-0.5">
                          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Total a cambiar</p>
                          {s.tienda_nombre && (
                            <span className="text-xs bg-blue-50 text-blue-600 border border-blue-200 px-1.5 py-0.5 rounded-full font-semibold">{s.tienda_nombre}</span>
                          )}
                        </div>
                        <p className="text-xl font-bold text-amber-700">{fmt(s.monto_solicitado)}</p>
                      </div>
                      {estadoBadge(s.estado)}
                    </div>

                    {/* Motivo */}
                    {s.motivo && (
                      <p className="text-xs text-gray-500 mt-1 italic">"{s.motivo}"</p>
                    )}

                    {/* Desglose legible */}
                    <div className="mt-2 space-y-1">
                      {items.length > 0
                        ? items.map((it, i) => (
                            <p key={i} className="text-sm text-gray-700">
                              <span className="font-semibold">{fmt(it.monto)}</span>
                              <span className="text-gray-500"> en {it.tipo}s de </span>
                              <span className={`font-bold ${it.tipo === 'billete' ? 'text-green-700' : 'text-amber-700'}`}>{it.label}</span>
                              <span className="text-gray-400 text-xs"> ({it.cantidad} {it.tipo}{it.cantidad !== 1 ? 's' : ''})</span>
                            </p>
                          ))
                        : <p className="text-xs text-gray-400 italic">Sin desglose registrado</p>
                      }
                    </div>

                    {/* Fecha */}
                    <p className="text-xs text-gray-400 mt-1.5">{new Date(s.fecha_solicitud).toLocaleString('es-CO')}</p>

                    {/* Botones acción (solo pendiente, sin editor abierto) */}
                    {s.estado === 'pendiente' && editando !== s.id && (
                      <div className="flex gap-2 mt-3">
                        <button onClick={() => rechazarSencilla(s.id)}
                          className="flex items-center gap-1 text-xs bg-red-100 text-red-700 hover:bg-red-200 px-3 py-2 rounded-lg font-medium">
                          <XCircle size={12} /> Rechazar
                        </button>
                        <button onClick={() => setEditando(s.id)}
                          className="flex items-center gap-1 text-xs bg-amber-100 text-amber-700 hover:bg-amber-200 px-3 py-2 rounded-lg font-medium">
                          <Pencil size={12} /> Cambiar
                        </button>
                        <button
                          onClick={() => aprobarSencilla(s.id, s.detalle ?? '[]', s.monto_solicitado)}
                          className="flex-1 flex items-center justify-center gap-1 text-xs bg-green-600 hover:bg-green-700 text-white px-3 py-2 rounded-lg font-semibold">
                          <CheckCircle2 size={12} /> Aprobar
                        </button>
                      </div>
                    )}

                    {/* Editor inline al presionar Cambiar */}
                    {s.estado === 'pendiente' && editando === s.id && (
                      <EditorSencilla
                        sencilla={s}
                        onAprobar={(detalle, monto) => aprobarSencilla(s.id, detalle, monto)}
                        onCancelar={() => setEditando(null)}
                      />
                    )}
                  </div>
                )
              })}
            </div>
          )
        }
      </div>
    </div>
  )
}
