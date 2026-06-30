import { useEffect, useState, useCallback } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import {
  ShoppingCart, AlertTriangle, Clock, CheckCircle2, CheckCircle,
  Copy, ChevronDown, ChevronUp, Phone, ClipboardList, Settings2, Check, Search,
} from 'lucide-react'

// ─── Types ────────────────────────────────────────────────────────────────────

interface Sede { id: number; nombre: string }

interface ProductoSugerido {
  producto_id: number
  nombre: string
  categoria: string
  unidad: string
  proveedor: string | null
  lead_time_dias: number
  stock_actual: number
  stock_minimo: number
  consumo_diario: number
  dias_restantes: number | null
  estado: 'agotado' | 'urgente' | 'pronto' | 'bajo' | 'ok'
  cantidad_sugerida: number
  barista_alerto: boolean
}

interface GrupoProveedor {
  proveedor: string
  lead_time_dias: number
  alerta_mediodia: boolean
  productos: ProductoSugerido[]
  estado_resumen: string
}

interface Sugerencia {
  grupos_fijos: GrupoProveedor[]
  insumos_generales: ProductoSugerido[]
  total_urgentes: number
  total_pronto: number
  total_bajo: number
  total_ok: number
}

interface ConteoItem {
  id: number
  producto_id: number
  producto_nombre: string
  categoria: string
  unidad_medida: string
  cantidad_sistema: number
  cantidad_real: number
  diferencia: number
}

interface Conteo {
  id: number
  tienda_id: number
  tienda_nombre: string | null
  fecha_conteo: string
  ajustado: boolean
  nota: string | null
  usuario_nombre: string
  items: ConteoItem[]
}

// ─── Config ───────────────────────────────────────────────────────────────────

const ESTADO_CFG = {
  agotado: { label: 'AGOTADO',  bg: 'bg-red-100',    text: 'text-red-700',    border: 'border-red-300',    dot: 'bg-red-500'    },
  urgente: { label: 'URGENTE',  bg: 'bg-red-50',     text: 'text-red-600',    border: 'border-red-200',    dot: 'bg-red-400'    },
  pronto:  { label: 'PEDIR',    bg: 'bg-amber-50',   text: 'text-amber-700',  border: 'border-amber-200',  dot: 'bg-amber-400'  },
  bajo:    { label: 'BAJO',     bg: 'bg-yellow-50',  text: 'text-yellow-700', border: 'border-yellow-200', dot: 'bg-yellow-400' },
  ok:      { label: 'OK',       bg: 'bg-green-50',   text: 'text-green-700',  border: 'border-green-200',  dot: 'bg-green-400'  },
}

const CAT_LABEL: Record<string, string> = {
  pasteleria: 'Pastelería',
  bebida: 'Bebidas e insumos',
  insumo: 'Desechables y limpieza',
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function BadgeEstado({ estado }: { estado: string }) {
  const cfg = ESTADO_CFG[estado as keyof typeof ESTADO_CFG] ?? ESTADO_CFG.ok
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold ${cfg.bg} ${cfg.text}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
      {cfg.label}
    </span>
  )
}

function diasLabel(d: number | null): string {
  if (d === null) return '—'
  if (d < 1) return `${Math.round(d * 24)}h`
  return `${d.toFixed(1)}d`
}

function copiarLista(proveedor: string, productos: ProductoSugerido[], cantidades: Record<number, number>) {
  const fecha = new Date().toLocaleDateString('es-CO', { day: 'numeric', month: 'long' })
  const lineas = productos
    .filter(p => cantidades[p.producto_id] > 0)
    .map(p => `- ${p.nombre}: ${cantidades[p.producto_id]} ${p.unidad}`)
  if (!lineas.length) { alert('No hay productos con cantidad > 0'); return }
  const texto = `*Pedido ${proveedor} — ${fecha}*\n${lineas.join('\n')}`
  navigator.clipboard.writeText(texto)
    .then(() => alert('Lista copiada al portapapeles ✓'))
    .catch(() => alert(texto))
}

// ─── FilaProducto ─────────────────────────────────────────────────────────────

function FilaProducto({
  p, cantidad, onCantidad,
}: {
  p: ProductoSugerido
  cantidad: number
  onCantidad: (id: number, v: number) => void
}) {
  const cfg = ESTADO_CFG[p.estado as keyof typeof ESTADO_CFG] ?? ESTADO_CFG.ok
  return (
    <tr className={`border-b border-gray-100 last:border-0 ${p.estado === 'ok' ? 'opacity-60' : ''}`}>
      <td className="py-2 pr-3">
        <div className="flex items-center gap-1.5">
          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${cfg.dot}`} />
          <span className="text-sm text-gray-800 font-medium">{p.nombre}</span>
          {p.barista_alerto && (
            <span className="text-xs bg-purple-100 text-purple-700 px-1.5 rounded-full font-medium">
              barista
            </span>
          )}
        </div>
      </td>
      <td className="py-2 px-2 text-center text-sm text-gray-600 whitespace-nowrap">
        {p.stock_actual} {p.unidad}
      </td>
      <td className="py-2 px-2 text-center">
        <span className={`text-sm font-semibold ${
          p.dias_restantes !== null && p.dias_restantes <= p.lead_time_dias
            ? 'text-red-600' : 'text-gray-700'
        }`}>
          {diasLabel(p.dias_restantes)}
        </span>
      </td>
      <td className="py-2 pl-2">
        <div className="flex items-center gap-1">
          <input
            type="number" min={0} step={1} value={cantidad}
            onChange={e => onCantidad(p.producto_id, Math.max(0, Number(e.target.value)))}
            className="w-16 text-center border border-gray-300 rounded-lg py-1 text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-amber-400"
          />
          <span className="text-xs text-gray-400">{p.unidad}</span>
        </div>
      </td>
    </tr>
  )
}

// ─── GrupoFijo ────────────────────────────────────────────────────────────────

function GrupoFijo({
  grupo, cantidades, onCantidad,
}: {
  grupo: GrupoProveedor
  cantidades: Record<number, number>
  onCantidad: (id: number, v: number) => void
}) {
  const [abierto, setAbierto] = useState(grupo.estado_resumen !== 'ok')
  const cfg = ESTADO_CFG[grupo.estado_resumen as keyof typeof ESTADO_CFG] ?? ESTADO_CFG.ok

  return (
    <div className={`rounded-2xl border-2 ${cfg.border} overflow-hidden mb-3`}>
      <button
        onClick={() => setAbierto(v => !v)}
        className={`w-full flex items-center justify-between px-4 py-3 ${cfg.bg}`}
      >
        <div className="flex items-center gap-2">
          <Phone size={14} className={cfg.text} />
          <span className={`font-bold text-sm ${cfg.text}`}>{grupo.proveedor}</span>
          <BadgeEstado estado={grupo.estado_resumen} />
          {grupo.alerta_mediodia && (
            <span className="flex items-center gap-1 text-xs text-amber-600 font-medium bg-amber-100 px-2 py-0.5 rounded-full">
              <Clock size={11} /> Antes del mediodía
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500">{grupo.productos.length} productos</span>
          {abierto ? <ChevronUp size={16} className="text-gray-400" /> : <ChevronDown size={16} className="text-gray-400" />}
        </div>
      </button>

      {abierto && (
        <div className="px-4 pb-3 pt-2 bg-white">
          <table className="w-full">
            <thead>
              <tr className="text-xs text-gray-400 uppercase border-b border-gray-100">
                <th className="pb-1.5 text-left font-medium">Producto</th>
                <th className="pb-1.5 text-center font-medium">Stock</th>
                <th className="pb-1.5 text-center font-medium">Días</th>
                <th className="pb-1.5 text-left font-medium pl-2">Pedir</th>
              </tr>
            </thead>
            <tbody>
              {grupo.productos.map(p => (
                <FilaProducto
                  key={p.producto_id}
                  p={p}
                  cantidad={cantidades[p.producto_id] ?? p.cantidad_sugerida}
                  onCantidad={onCantidad}
                />
              ))}
            </tbody>
          </table>
          <button
            onClick={() => copiarLista(grupo.proveedor, grupo.productos, cantidades)}
            className="mt-3 flex items-center gap-1.5 text-xs font-medium text-gray-500 hover:text-gray-700 border border-gray-200 rounded-lg px-3 py-1.5 hover:bg-gray-50 transition-colors"
          >
            <Copy size={12} /> Copiar lista para WhatsApp
          </button>
        </div>
      )}
    </div>
  )
}

// ─── GeneralesPanel ───────────────────────────────────────────────────────────

function GeneralesPanel({
  items, cantidades, onCantidad,
}: {
  items: ProductoSugerido[]
  cantidades: Record<number, number>
  onCantidad: (id: number, v: number) => void
}) {
  const [verOk, setVerOk] = useState(false)
  const noOk    = items.filter(i => i.estado !== 'ok')
  const ok      = items.filter(i => i.estado === 'ok')
  const visible = verOk ? items : noOk

  if (!items.length) return null

  const porCat: Record<string, ProductoSugerido[]> = {}
  for (const item of visible) {
    const cat = item.categoria
    if (!porCat[cat]) porCat[cat] = []
    porCat[cat].push(item)
  }

  return (
    <div className="mt-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-bold text-gray-700">Insumos generales</h3>
        {ok.length > 0 && (
          <button
            onClick={() => setVerOk(v => !v)}
            className="text-xs text-gray-400 hover:text-gray-600 underline"
          >
            {verOk ? 'Ocultar OK' : `Ver ${ok.length} productos OK`}
          </button>
        )}
      </div>

      {noOk.length === 0 && !verOk ? (
        <div className="flex items-center gap-2 text-sm text-green-600 bg-green-50 border border-green-200 rounded-xl px-4 py-3">
          <CheckCircle2 size={16} />
          Todos los insumos tienen stock suficiente
        </div>
      ) : (
        Object.entries(porCat).map(([cat, prods]) => (
          <div key={cat} className="mb-4">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
              {CAT_LABEL[cat] ?? cat}
            </p>
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <table className="w-full">
                <thead>
                  <tr className="text-xs text-gray-400 uppercase border-b border-gray-100">
                    <th className="px-3 pb-1.5 pt-2 text-left font-medium">Producto</th>
                    <th className="px-2 pb-1.5 pt-2 text-center font-medium">Stock</th>
                    <th className="px-2 pb-1.5 pt-2 text-center font-medium">Días</th>
                    <th className="px-2 pb-1.5 pt-2 text-left font-medium">Pedir</th>
                  </tr>
                </thead>
                <tbody>
                  {prods.map(p => (
                    <FilaProducto
                      key={p.producto_id}
                      p={p}
                      cantidad={cantidades[p.producto_id] ?? p.cantidad_sugerida}
                      onCantidad={onCantidad}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))
      )}
    </div>
  )
}

// ─── TabPedidos ───────────────────────────────────────────────────────────────

function TabPedidos({ tiendaId }: { tiendaId: number | null }) {
  const [data, setData]           = useState<Sugerencia | null>(null)
  const [loading, setLoading]     = useState(false)
  const [cantidades, setCantidades] = useState<Record<number, number>>({})

  useEffect(() => {
    if (tiendaId === null) return
    setCantidades({})
    setData(null)
    setLoading(true)
    api.get('/pedidos/sugerencia', { params: { tienda_id: tiendaId } })
      .then(r => {
        setData(r.data)
        const init: Record<number, number> = {}
        for (const g of r.data.grupos_fijos)
          for (const p of g.productos) init[p.producto_id] = p.cantidad_sugerida
        for (const p of r.data.insumos_generales) init[p.producto_id] = p.cantidad_sugerida
        setCantidades(init)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [tiendaId])

  const handleCantidad = (id: number, v: number) =>
    setCantidades(prev => ({ ...prev, [id]: v }))

  if (loading) return (
    <p className="text-sm text-gray-400 animate-pulse py-8 text-center">Calculando sugerencias…</p>
  )

  if (!data) return null

  return (
    <>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <div className="bg-red-50 border border-red-200 rounded-xl p-3 text-center">
          <p className="text-2xl font-bold text-red-600">{data.total_urgentes}</p>
          <p className="text-xs text-red-500 font-medium uppercase tracking-wide mt-0.5">Urgente</p>
        </div>
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 text-center">
          <p className="text-2xl font-bold text-amber-600">{data.total_pronto}</p>
          <p className="text-xs text-amber-500 font-medium uppercase tracking-wide mt-0.5">Pedir hoy</p>
        </div>
        <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-3 text-center">
          <p className="text-2xl font-bold text-yellow-600">{data.total_bajo}</p>
          <p className="text-xs text-yellow-500 font-medium uppercase tracking-wide mt-0.5">Stock bajo</p>
        </div>
        <div className="bg-green-50 border border-green-200 rounded-xl p-3 text-center">
          <p className="text-2xl font-bold text-green-600">{data.total_ok}</p>
          <p className="text-xs text-green-500 font-medium uppercase tracking-wide mt-0.5">OK</p>
        </div>
      </div>

      {data.total_urgentes === 0 && data.total_pronto === 0 && data.total_bajo === 0 && (
        <div className="flex items-center gap-2 text-sm text-green-700 bg-green-50 border border-green-200 rounded-xl px-4 py-3">
          <CheckCircle2 size={16} />
          Todo el inventario tiene stock suficiente para los próximos días
        </div>
      )}

      {data.total_urgentes > 0 && (
        <div className="flex items-center gap-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded-xl px-4 py-3">
          <AlertTriangle size={16} />
          {data.total_urgentes} producto{data.total_urgentes > 1 ? 's' : ''} se agotará{data.total_urgentes > 1 ? 'n' : ''} antes de que llegue el próximo pedido
        </div>
      )}

      {data.grupos_fijos.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
            Proveedores fijos
          </p>
          {data.grupos_fijos.map(g => (
            <GrupoFijo key={g.proveedor} grupo={g} cantidades={cantidades} onCantidad={handleCantidad} />
          ))}
        </div>
      )}

      <GeneralesPanel items={data.insumos_generales} cantidades={cantidades} onCantidad={handleCantidad} />
    </>
  )
}

// ─── TabConteos ───────────────────────────────────────────────────────────────

function TabConteos() {
  const [conteos, setConteos]     = useState<Conteo[]>([])
  const [expandido, setExpandido] = useState<number | null>(null)
  const [ajustando, setAjustando] = useState<number | null>(null)
  const [error, setError]         = useState('')

  const cargar = useCallback(async () => {
    try {
      const { data } = await api.get<Conteo[]>('/compras/conteo/pendientes')
      setConteos(data)
      setError('')
    } catch (e: any) {
      setError(e.response?.data?.detail || 'No se pudieron cargar los conteos pendientes')
    }
  }, [])

  useEffect(() => { cargar() }, [cargar])

  const ajustar = async (conteoId: number) => {
    setAjustando(conteoId); setError('')
    try {
      await api.post(`/compras/conteo/${conteoId}/ajustar`)
      await cargar()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al ajustar')
    } finally { setAjustando(null) }
  }

  return (
    <div className="space-y-3">
      {error && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-600 rounded-xl px-4 py-3 text-sm">
          <AlertTriangle size={14} /> {error}
        </div>
      )}

      {conteos.length === 0 && (
        <div className="bg-white border border-gray-200 rounded-2xl px-4 py-8 text-center">
          <CheckCircle size={28} className="text-green-400 mx-auto mb-2" />
          <p className="text-sm text-gray-500">No hay conteos pendientes de ajuste</p>
        </div>
      )}

      {conteos.map(c => (
        <div key={c.id} className="bg-white border border-gray-200 rounded-2xl overflow-hidden">
          <button
            onClick={() => setExpandido(expandido === c.id ? null : c.id)}
            className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors"
          >
            <div className="text-left">
              <p className="text-sm font-semibold text-gray-800">
                Conteo #{c.id} — {c.tienda_nombre ?? `Tienda ${c.tienda_id}`}
              </p>
              <p className="text-xs text-gray-400">
                {new Date(c.fecha_conteo).toLocaleDateString('es-CO', {
                  day: '2-digit', month: 'short', year: 'numeric',
                })} · Por: {c.usuario_nombre}
              </p>
              {c.nota && <p className="text-xs text-amber-700 mt-0.5 font-medium">Nota: {c.nota}</p>}
            </div>
            {expandido === c.id
              ? <ChevronUp size={16} className="text-gray-400" />
              : <ChevronDown size={16} className="text-gray-400" />}
          </button>

          {expandido === c.id && (
            <div className="border-t border-gray-100">
              <div className="px-4 py-2 bg-gray-50 grid grid-cols-4 text-xs font-bold text-gray-400 uppercase tracking-wide">
                <span className="col-span-2">Producto</span>
                <span className="text-center">Sistema</span>
                <span className="text-center">Real</span>
              </div>
              <div className="divide-y divide-gray-50">
                {c.items.map(item => {
                  const dif = item.diferencia
                  const difColor = dif < 0 ? 'text-red-600' : dif > 0 ? 'text-blue-600' : 'text-gray-400'
                  return (
                    <div key={item.id} className="px-4 py-2.5 grid grid-cols-4 items-center">
                      <div className="col-span-2">
                        <p className="text-sm font-medium text-gray-800">{item.producto_nombre}</p>
                        <p className="text-xs text-gray-400">{item.unidad_medida}</p>
                      </div>
                      <p className="text-sm text-center text-gray-500">{Math.round(item.cantidad_sistema)}</p>
                      <div className="text-center">
                        <p className="text-sm font-bold text-gray-800">{Math.round(item.cantidad_real)}</p>
                        {dif !== 0 && (
                          <p className={`text-xs font-semibold ${difColor}`}>
                            {dif > 0 ? `+${Math.round(dif)}` : Math.round(dif)}
                          </p>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
              <div className="px-4 py-3 border-t border-gray-100">
                <button
                  onClick={() => ajustar(c.id)}
                  disabled={ajustando === c.id}
                  className="w-full bg-green-600 hover:bg-green-700 disabled:opacity-40 text-white font-bold py-3 rounded-xl text-sm transition-colors"
                >
                  {ajustando === c.id ? 'Ajustando stock...' : 'Aprobar y Ajustar Stock'}
                </button>
                <p className="text-xs text-gray-400 text-center mt-1.5">
                  Actualiza el inventario a las cantidades reales contadas
                </p>
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

// ─── TabProveedores ───────────────────────────────────────────────────────────

interface ProdFlat { id: number; nombre: string; categoria: string; proveedor: string }

function TabProveedores({ tiendaId }: { tiendaId: number | null }) {
  const [productos, setProductos]   = useState<ProdFlat[]>([])
  const [editores, setEditores]     = useState<Record<number, string>>({})
  const [saving, setSaving]         = useState<Record<number, boolean>>({})
  const [saved, setSaved]           = useState<Record<number, boolean>>({})
  const [loading, setLoading]       = useState(false)

  const cargar = useCallback(() => {
    if (!tiendaId) return
    setLoading(true)
    api.get('/pedidos/sugerencia', { params: { tienda_id: tiendaId } })
      .then(r => {
        const all: ProdFlat[] = [
          ...r.data.grupos_fijos.flatMap((g: GrupoProveedor) =>
            g.productos.map((p: ProductoSugerido) => ({
              id: p.producto_id, nombre: p.nombre, categoria: p.categoria, proveedor: g.proveedor,
            }))
          ),
          ...r.data.insumos_generales.map((p: ProductoSugerido) => ({
            id: p.producto_id, nombre: p.nombre, categoria: p.categoria, proveedor: '',
          })),
        ]
        all.sort((a, b) => a.proveedor.localeCompare(b.proveedor) || a.nombre.localeCompare(b.nombre))
        setProductos(all)
        const init: Record<number, string> = {}
        for (const p of all) init[p.id] = p.proveedor
        setEditores(init)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [tiendaId])

  useEffect(() => { cargar() }, [cargar])

  const proveedoresExistentes = [...new Set(productos.map(p => p.proveedor).filter(Boolean))].sort()

  const guardar = async (id: number) => {
    setSaving(prev => ({ ...prev, [id]: true }))
    try {
      await api.patch(`/inventario/productos/${id}`, { proveedor: editores[id]?.trim() ?? '' })
      setSaved(prev => ({ ...prev, [id]: true }))
      setTimeout(() => { setSaved(prev => ({ ...prev, [id]: false })); cargar() }, 900)
    } catch { alert('Error al guardar') }
    finally { setSaving(prev => ({ ...prev, [id]: false })) }
  }

  // Agrupar por proveedor actual (en editores)
  const grupos: Record<string, ProdFlat[]> = {}
  for (const p of productos) {
    const key = p.proveedor || '__sin__'
    if (!grupos[key]) grupos[key] = []
    grupos[key].push(p)
  }
  const gruposOrdenados: [string, ProdFlat[]][] = [
    ...Object.entries(grupos).filter(([k]) => k !== '__sin__').sort(([a], [b]) => a.localeCompare(b)),
    ...(grupos['__sin__'] ? [['__sin__', grupos['__sin__']] as [string, ProdFlat[]]] : []),
  ]

  const [busqueda, setBusqueda] = useState('')
  const listId = 'proveedores-list'

  const gruposFiltrados: [string, ProdFlat[]][] = busqueda.trim()
    ? gruposOrdenados
        .map(([key, items]) => [
          key,
          items.filter(p => p.nombre.toLowerCase().includes(busqueda.toLowerCase())),
        ] as [string, ProdFlat[]])
        .filter(([, items]) => items.length > 0)
    : gruposOrdenados

  if (loading) return <p className="text-sm text-gray-400 text-center py-8 animate-pulse">Cargando…</p>

  return (
    <div className="space-y-4">
      <datalist id={listId}>
        {proveedoresExistentes.map(p => <option key={p} value={p} />)}
      </datalist>

      <div className="relative">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
        <input
          type="text"
          placeholder="Buscar producto…"
          value={busqueda}
          onChange={e => setBusqueda(e.target.value)}
          className="w-full pl-8 pr-3 py-2 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-amber-300"
        />
      </div>

      <p className="text-xs text-gray-400">
        Asigná un proveedor a cada producto para que aparezca agrupado en la sugerencia de pedido.
        Dejá el campo vacío para moverlo a "Insumos generales".
      </p>

      {gruposFiltrados.map(([key, items]) => (
        <div key={key} className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <div className="px-4 py-2.5 bg-gray-50 border-b border-gray-100 flex items-center gap-2">
            <Phone size={13} className="text-gray-400" />
            <p className="text-xs font-bold text-gray-600 uppercase tracking-wide">
              {key === '__sin__' ? 'Sin proveedor — insumos generales' : key}
            </p>
            <span className="ml-auto text-xs text-gray-400">{items.length} productos</span>
          </div>
          <div className="divide-y divide-gray-50">
            {items.map(p => {
              const val = editores[p.id] ?? p.proveedor
              const dirty = val.trim() !== p.proveedor
              return (
                <div key={p.id} className="flex items-center gap-3 px-4 py-2.5">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-800">{p.nombre}</p>
                    <p className="text-xs text-gray-400">{p.categoria}</p>
                  </div>
                  <input
                    type="text"
                    list={listId}
                    value={val}
                    onChange={e => setEditores(prev => ({ ...prev, [p.id]: e.target.value }))}
                    placeholder="Nombre del proveedor…"
                    className="w-44 border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-amber-300 text-gray-700 placeholder:text-gray-300"
                  />
                  <button
                    onClick={() => guardar(p.id)}
                    disabled={!dirty || saving[p.id] || saved[p.id]}
                    className={`shrink-0 w-8 h-8 flex items-center justify-center rounded-lg transition-all ${
                      saved[p.id]  ? 'bg-green-100 text-green-600' :
                      dirty        ? 'bg-amber-500 text-white hover:bg-amber-600' :
                      'bg-gray-100 text-gray-300'
                    }`}
                    title="Guardar"
                  >
                    {saved[p.id] ? <Check size={14} /> : saving[p.id] ? '…' : <Check size={14} />}
                  </button>
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function PedidosAdmin() {
  const { user } = useAuth()
  const [sedes, setSedes]         = useState<Sede[]>([])
  const [tiendaId, setTiendaId]   = useState<number | null>(user?.tienda_id ?? null)
  const [tab, setTab]             = useState<'pedidos' | 'conteos' | 'proveedores'>('pedidos')
  const [nConteos, setNConteos]   = useState(0)

  useEffect(() => {
    api.get('/auth/tiendas').then(r => {
      setSedes(r.data)
      if (tiendaId === null && r.data.length > 0) setTiendaId(r.data[0].id)
    }).catch(() => {})
    api.get<Conteo[]>('/compras/conteo/pendientes')
      .then(r => setNConteos(r.data.length))
      .catch(() => {})
  }, [])

  return (
    <div className="space-y-4 pb-10">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <ShoppingCart size={18} className="text-amber-600" />
          <h1 className="text-lg font-bold text-gray-800">Pedidos</h1>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {sedes.length > 1 && (
            <div className="flex gap-1">
              {sedes.map(s => (
                <button key={s.id} onClick={() => setTiendaId(s.id)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                    tiendaId === s.id
                      ? 'bg-amber-500 text-white'
                      : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'
                  }`}>
                  {s.nombre}
                </button>
              ))}
            </div>
          )}

          <div className="flex bg-gray-100 rounded-xl p-0.5">
            <button
              onClick={() => setTab('pedidos')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                tab === 'pedidos' ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              <ShoppingCart size={13} /> Sugerencia
            </button>
            <button
              onClick={() => setTab('conteos')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                tab === 'conteos' ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              <ClipboardList size={13} /> Conteos
              {nConteos > 0 && (
                <span className="bg-red-500 text-white text-[10px] font-bold rounded-full w-4 h-4 flex items-center justify-center">
                  {nConteos}
                </span>
              )}
            </button>
            <button
              onClick={() => setTab('proveedores')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                tab === 'proveedores' ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              <Settings2 size={13} /> Proveedores
            </button>
          </div>
        </div>
      </div>

      {tab === 'pedidos'     && <TabPedidos     tiendaId={tiendaId} />}
      {tab === 'conteos'     && <TabConteos />}
      {tab === 'proveedores' && <TabProveedores tiendaId={tiendaId} />}
    </div>
  )
}
