import { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import {
  ShoppingCart, AlertTriangle, Clock, CheckCircle2,
  Copy, ChevronDown, ChevronUp, Phone,
} from 'lucide-react'

// ─── Tipos ────────────────────────────────────────────────────────────────────

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

// ─── Helpers ──────────────────────────────────────────────────────────────────

const ESTADO_CFG = {
  agotado: { label: 'AGOTADO',  bg: 'bg-red-100',    text: 'text-red-700',    border: 'border-red-300',    dot: 'bg-red-500'    },
  urgente: { label: 'URGENTE',  bg: 'bg-red-50',     text: 'text-red-600',    border: 'border-red-200',    dot: 'bg-red-400'    },
  pronto:  { label: 'PEDIR',    bg: 'bg-amber-50',   text: 'text-amber-700',  border: 'border-amber-200',  dot: 'bg-amber-400'  },
  bajo:    { label: 'BAJO',     bg: 'bg-yellow-50',  text: 'text-yellow-700', border: 'border-yellow-200', dot: 'bg-yellow-400' },
  ok:      { label: 'OK',       bg: 'bg-green-50',   text: 'text-green-700',  border: 'border-green-200',  dot: 'bg-green-400'  },
}

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

// ─── Fila de producto ─────────────────────────────────────────────────────────

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
            type="number"
            min={0}
            step={1}
            value={cantidad}
            onChange={e => onCantidad(p.producto_id, Math.max(0, Number(e.target.value)))}
            className="w-16 text-center border border-gray-300 rounded-lg py-1 text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-amber-400"
          />
          <span className="text-xs text-gray-400">{p.unidad}</span>
        </div>
      </td>
    </tr>
  )
}

// ─── Grupo proveedor fijo ─────────────────────────────────────────────────────

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
      {/* Header */}
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

      {/* Tabla */}
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

// ─── Panel de insumos generales ───────────────────────────────────────────────

const CAT_LABEL: Record<string, string> = {
  pasteleria: 'Pastelería',
  bebida: 'Bebidas e insumos',
  insumo: 'Desechables y limpieza',
}

function GeneralesPanel({
  items, cantidades, onCantidad,
}: {
  items: ProductoSugerido[]
  cantidades: Record<number, number>
  onCantidad: (id: number, v: number) => void
}) {
  const [verOk, setVerOk] = useState(false)

  const noOk = items.filter(i => i.estado !== 'ok')
  const ok   = items.filter(i => i.estado === 'ok')
  const visible = verOk ? items : noOk

  if (!items.length) return null

  // Agrupar por categoría
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

// ─── Página principal ─────────────────────────────────────────────────────────

export default function PedidosAdmin() {
  const { user } = useAuth()
  const [sedes, setSedes] = useState<Sede[]>([])
  const [tiendaId, setTiendaId] = useState<number | null>(user?.tienda_id ?? null)
  const [data, setData] = useState<Sugerencia | null>(null)
  const [loading, setLoading] = useState(false)
  const [cantidades, setCantidades] = useState<Record<number, number>>({})

  // Cargar sedes
  useEffect(() => {
    api.get('/auth/tiendas').then(r => {
      setSedes(r.data)
      if (tiendaId === null && r.data.length > 0) setTiendaId(r.data[0].id)
    }).catch(() => {})
  }, [])

  // Cargar sugerencia cuando cambia la sede
  useEffect(() => {
    if (tiendaId === null) return
    setLoading(true)
    api.get('/pedidos/sugerencia', { params: { tienda_id: tiendaId } })
      .then(r => {
        setData(r.data)
        // Inicializar cantidades con las sugeridas
        const init: Record<number, number> = {}
        for (const g of r.data.grupos_fijos) {
          for (const p of g.productos) init[p.producto_id] = p.cantidad_sugerida
        }
        for (const p of r.data.insumos_generales) init[p.producto_id] = p.cantidad_sugerida
        setCantidades(init)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [tiendaId])

  const handleCantidad = (id: number, v: number) =>
    setCantidades(prev => ({ ...prev, [id]: v }))

  return (
    <div className="space-y-4 pb-10">
      {/* Título */}
      <div>
        <h1 className="text-xl font-bold text-gray-800 flex items-center gap-2">
          <ShoppingCart size={20} className="text-amber-600" />
          Panel de Pedidos
        </h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Sugerencia basada en consumo de los últimos 14 días
        </p>
      </div>

      {/* Selector de sede */}
      {sedes.length > 1 && (
        <div className="flex gap-2 flex-wrap">
          {sedes.map(s => (
            <button
              key={s.id}
              onClick={() => setTiendaId(s.id)}
              className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
                tiendaId === s.id
                  ? 'bg-amber-500 text-white shadow-sm'
                  : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'
              }`}
            >
              {s.nombre}
            </button>
          ))}
        </div>
      )}

      {loading && (
        <p className="text-sm text-gray-400 animate-pulse py-8 text-center">
          Calculando sugerencias…
        </p>
      )}

      {data && !loading && (
        <>
          {/* KPIs de resumen */}
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

          {/* Sin urgencias */}
          {data.total_urgentes === 0 && data.total_pronto === 0 && data.total_bajo === 0 && (
            <div className="flex items-center gap-2 text-sm text-green-700 bg-green-50 border border-green-200 rounded-xl px-4 py-3">
              <CheckCircle2 size={16} />
              Todo el inventario tiene stock suficiente para los próximos días
            </div>
          )}

          {/* Advertencia si hay urgentes */}
          {data.total_urgentes > 0 && (
            <div className="flex items-center gap-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded-xl px-4 py-3">
              <AlertTriangle size={16} />
              {data.total_urgentes} producto{data.total_urgentes > 1 ? 's' : ''} se agotará{data.total_urgentes > 1 ? 'n' : ''} antes de que llegue el próximo pedido
            </div>
          )}

          {/* Grupos de proveedores fijos */}
          {data.grupos_fijos.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
                Proveedores fijos
              </p>
              {data.grupos_fijos.map(g => (
                <GrupoFijo
                  key={g.proveedor}
                  grupo={g}
                  cantidades={cantidades}
                  onCantidad={handleCantidad}
                />
              ))}
            </div>
          )}

          {/* Insumos generales */}
          <GeneralesPanel
            items={data.insumos_generales}
            cantidades={cantidades}
            onCantidad={handleCantidad}
          />
        </>
      )}
    </div>
  )
}
