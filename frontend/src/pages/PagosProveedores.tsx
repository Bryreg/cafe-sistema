import { useEffect, useMemo, useState } from 'react'
import api from '../api/client'
import { conMiles, soloDigitos } from '../utils/plata'
import {
  Truck, Wallet, Receipt, Download, Camera, X, Search,
  CheckCircle, AlertCircle, Clock, Building2, Trash2, Pencil, CalendarClock,
} from 'lucide-react'

// ─── Tipos ────────────────────────────────────────────────────────────────────
interface FacturaItem { id: number; producto_nombre: string; cantidad: number; precio_unitario: number; unidad_medida: string }
interface Factura {
  id: number; tienda_id: number; tienda_nombre: string | null
  proveedor: string; numero_factura: string | null
  fecha_recibido: string | null; valor_total: number
  tipo_pago: string; valor_pagado: number; saldo: number
  estado_pago: 'pagado' | 'parcial' | 'pendiente'
  forma_pago_real: string | null
  imagen_url: string | null; imagen_soporte_url: string | null
  barista_nombre: string; items: FacturaItem[]
  // Vencimiento: lo que hace que la factura entre en la agenda de Costos.
  fecha_vencimiento: string | null
  plazo_dias: number | null
  fecha_programada: string | null
  vencida: boolean            // derivado: hay saldo y el vencimiento ya pasó
}
interface Grupo { proveedor?: string; tienda?: string; facturado: number; pagado: number; pendiente: number; n?: number }
interface Dashboard {
  totales: { facturado: number; pagado: number; pendiente: number; n_facturas: number }
  por_proveedor: Grupo[]; por_sede: Grupo[]; facturas: Factura[]
}
interface Tienda { id: number; nombre: string }

const fmt = (v: number) => '$' + Math.round(v || 0).toLocaleString('es-CO')
// Los timestamps llegan como medianoche COLOMBIA en UTC: cortar a YYYY-MM-DD y leer
// ese día tal cual evita que el navegador lo corra al día anterior.
const fechaCorta = (s: string) => new Date(s.slice(0, 10) + 'T00:00:00').toLocaleDateString('es-CO')
const ESTADO: Record<string, { label: string; cls: string; Icon: typeof CheckCircle }> = {
  pagado:    { label: 'Pagado',    cls: 'bg-green-100 text-green-700', Icon: CheckCircle },
  parcial:   { label: 'Parcial',   cls: 'bg-amber-100 text-amber-700', Icon: Clock },
  pendiente: { label: 'Pendiente', cls: 'bg-red-100 text-red-700',     Icon: AlertCircle },
}

/** `embebido` = renderizado como pestaña DENTRO de Costos (su casa desde la fase 5).
 *  Solo apaga el título propio: dos <h1> en la misma página rompen la jerarquía y
 *  repiten el nombre del módulo. Todo lo demás —filtros, KPIs, acciones— es idéntico:
 *  la vista se reusa, no se duplica. */
export default function PagosProveedores({ embebido = false }: { embebido?: boolean }) {
  const [tiendas, setTiendas] = useState<Tienda[]>([])
  const [tiendaId, setTiendaId] = useState<number | null>(null)  // null = todas
  const [desde, setDesde] = useState('')
  const [hasta, setHasta] = useState('')
  const [data, setData] = useState<Dashboard | null>(null)
  const [loading, setLoading] = useState(false)
  // filtros client-side
  const [fProveedor, setFProveedor] = useState('')
  const [fEstado, setFEstado] = useState('')
  const [busqueda, setBusqueda] = useState('')
  const [detalleAbierto, setDetalleAbierto] = useState<number | null>(null)
  // registrar pago
  const [pagoFactura, setPagoFactura] = useState<Factura | null>(null)
  const [monto, setMonto] = useState('')
  const [formaPago, setFormaPago] = useState('transferencia')
  const [soporte, setSoporte] = useState<File | null>(null)
  const [guardando, setGuardando] = useState(false)
  const [pagoError, setPagoError] = useState('')
  // editar factura completa
  const [editFactura, setEditFactura] = useState<Factura | null>(null)
  const [editTotal, setEditTotal] = useState('')
  const [editPagado, setEditPagado] = useState('')
  const [editProveedor, setEditProveedor] = useState('')
  const [editNumero, setEditNumero] = useState('')
  const [editFecha, setEditFecha] = useState('')
  const [editTipoPago, setEditTipoPago] = useState('')
  const [editVence, setEditVence] = useState('')
  const [editPlazo, setEditPlazo] = useState('')
  const [editProgramada, setEditProgramada] = useState('')
  const [editItems, setEditItems] = useState<{ id: number; nombre: string; unidad: string; cantidad: string; precio: string }[]>([])
  const [editError, setEditError] = useState('')

  useEffect(() => {
    api.get<Tienda[]>('/auth/tiendas').then(r => setTiendas(r.data)).catch(() => {})
  }, [])

  const cargar = () => {
    setLoading(true)
    const params: Record<string, string | number> = {}
    if (tiendaId) params.tienda_id = tiendaId
    if (desde) params.desde = desde
    if (hasta) params.hasta = hasta
    api.get<Dashboard>('/facturas/dashboard', { params })
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }
  useEffect(cargar, [tiendaId, desde, hasta])

  const proveedores = useMemo(() => [...new Set((data?.facturas ?? []).map(f => f.proveedor))].sort(), [data])

  const facturas = useMemo(() => (data?.facturas ?? []).filter(f =>
    (!fProveedor || f.proveedor === fProveedor) &&
    (!fEstado || f.estado_pago === fEstado) &&
    (!busqueda || f.proveedor.toLowerCase().includes(busqueda.toLowerCase())
      || (f.numero_factura || '').toLowerCase().includes(busqueda.toLowerCase())
      || f.items.some(i => i.producto_nombre.toLowerCase().includes(busqueda.toLowerCase())))
  ), [data, fProveedor, fEstado, busqueda])

  const maxProv = Math.max(1, ...(data?.por_proveedor ?? []).map(p => p.facturado))

  const abrirEditar = (f: Factura) => {
    setEditFactura(f)
    setEditTotal(String(Math.round(f.valor_total)))
    setEditPagado(String(Math.round(f.valor_pagado)))
    setEditProveedor(f.proveedor)
    setEditNumero(f.numero_factura ?? '')
    setEditFecha(f.fecha_recibido ? f.fecha_recibido.slice(0, 10) : '')
    setEditTipoPago(f.tipo_pago)
    setEditVence(f.fecha_vencimiento ? f.fecha_vencimiento.slice(0, 10) : '')
    setEditPlazo(f.plazo_dias != null ? String(f.plazo_dias) : '')
    setEditProgramada(f.fecha_programada ? f.fecha_programada.slice(0, 10) : '')
    setEditItems(f.items.map(i => ({
      id: i.id, nombre: i.producto_nombre, unidad: i.unidad_medida,
      cantidad: String(i.cantidad), precio: String(Math.round(i.precio_unitario || 0)),
    })))
    setEditError('')
  }

  const quitarItemEdit = (id: number) => setEditItems(prev => prev.filter(i => i.id !== id))

  const guardarEdicion = async () => {
    if (!editFactura) return
    const total = Number(editTotal)
    if (!(total > 0)) { setEditError('El total debe ser mayor a 0'); return }
    setGuardando(true); setEditError('')
    try {
      await api.patch(`/facturas/${editFactura.id}`, {
        valor_total: total,
        valor_pagado: Number(editPagado) || 0,
        proveedor: editProveedor.trim() || undefined,
        numero_factura: editNumero.trim(),
        fecha_recibido: editFecha || undefined,
        tipo_pago: editTipoPago || undefined,
        // Van SIEMPRE, y en null cuando se vacían: así se puede BORRAR una fecha
        // programada puesta por error (es la que manda en la agenda).
        fecha_vencimiento: editVence || null,
        plazo_dias: editPlazo === '' ? null : Number(editPlazo),
        fecha_programada: editProgramada || null,
        items: editItems.map(i => ({
          id: i.id,
          cantidad: Number(i.cantidad) || 0,
          precio_unitario: Number(i.precio) || 0,
        })),
      })
      setEditFactura(null)
      cargar()
    } catch (e: any) {
      setEditError(e.response?.data?.detail || 'No se pudo editar. Reintentá.')
    } finally { setGuardando(false) }
  }

  const registrarPago = async () => {
    if (!pagoFactura || !monto || Number(monto) <= 0) return
    setGuardando(true); setPagoError('')
    try {
      const fd = new FormData()
      fd.append('monto', monto)
      fd.append('forma_pago', formaPago)
      if (soporte) fd.append('imagen', soporte)
      await api.patch(`/facturas/${pagoFactura.id}/pago`, fd)
      setPagoFactura(null); setMonto(''); setSoporte(null)
      cargar()
    } catch (e: any) {
      // Antes el error se tragaba: el modal quedaba abierto sin feedback (manejo de dinero).
      setPagoError(e.response?.data?.detail || 'No se pudo registrar el pago. Reintentá.')
    } finally { setGuardando(false) }
  }

  return (
    <div className="space-y-4">
      {/* Header + filtros */}
      <div className="flex flex-wrap items-center gap-3">
        {!embebido && (
          <div className="flex items-center gap-2">
            <Truck size={20} className="text-forest" />
            <h1 className="text-lg font-bold text-gray-800">Pagos a Proveedores</h1>
          </div>
        )}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <input type="date" value={desde} onChange={e => setDesde(e.target.value)}
            className="border border-gray-200 rounded-lg px-2 py-1.5 text-sm bg-white" />
          <span className="text-gray-400 text-sm">→</span>
          <input type="date" value={hasta} onChange={e => setHasta(e.target.value)}
            className="border border-gray-200 rounded-lg px-2 py-1.5 text-sm bg-white" />
        </div>
      </div>

      {/* Sede */}
      <div className="flex items-center gap-2 flex-wrap">
        <button onClick={() => setTiendaId(null)}
          className={`px-3 py-1.5 rounded-xl text-sm font-semibold transition-colors ${
            tiendaId === null ? 'bg-forest text-white' : 'bg-white border border-gray-200 text-gray-500 hover:bg-gray-50'
          }`}>Todas las sedes</button>
        {tiendas.map(t => (
          <button key={t.id} onClick={() => setTiendaId(t.id)}
            className={`px-3 py-1.5 rounded-xl text-sm font-semibold transition-colors ${
              tiendaId === t.id ? 'bg-forest text-white' : 'bg-white border border-gray-200 text-gray-500 hover:bg-gray-50'
            }`}>{t.nombre}</button>
        ))}
      </div>

      {loading && <p className="text-sm text-gray-400 text-center py-8 animate-pulse">Cargando pagos...</p>}

      {!loading && data && (
        <>
          {/* KPIs */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1">Total facturado</p>
              <p className="text-xl font-bold text-gray-800 font-mono">{fmt(data.totales.facturado)}</p>
              <p className="text-xs text-gray-400">{data.totales.n_facturas} facturas</p>
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1">Total pagado</p>
              <p className="text-xl font-bold text-green-700 font-mono">{fmt(data.totales.pagado)}</p>
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1">Pendiente</p>
              <p className="text-xl font-bold text-red-600 font-mono">{fmt(data.totales.pendiente)}</p>
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1">% Pagado</p>
              <p className="text-xl font-bold text-gray-800 font-mono">
                {data.totales.facturado > 0 ? Math.round(data.totales.pagado / data.totales.facturado * 100) : 0}%
              </p>
            </div>
          </div>

          {/* Ranking proveedores + por sede */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-3">Ranking de proveedores</p>
              <div className="space-y-2.5">
                {data.por_proveedor.slice(0, 8).map(p => (
                  <div key={p.proveedor}>
                    <div className="flex items-center justify-between text-xs mb-1">
                      <span className="font-semibold text-gray-700 truncate">{p.proveedor}</span>
                      <span className="font-mono text-gray-500 shrink-0 ml-2">{fmt(p.facturado)}</span>
                    </div>
                    <div className="h-2.5 rounded-full bg-gray-100 overflow-hidden flex">
                      <div className="h-full bg-green-500" style={{ width: `${(p.pagado / maxProv) * 100}%` }} title={`Pagado ${fmt(p.pagado)}`} />
                      <div className="h-full bg-red-300" style={{ width: `${(p.pendiente / maxProv) * 100}%` }} title={`Pendiente ${fmt(p.pendiente)}`} />
                    </div>
                  </div>
                ))}
                {data.por_proveedor.length === 0 && <p className="text-sm text-gray-400">Sin datos</p>}
              </div>
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-3">Por sede</p>
              <div className="space-y-2">
                {data.por_sede.map(s => (
                  <div key={s.tienda} className="flex items-center gap-2 text-sm">
                    <Building2 size={14} className="text-gray-400 shrink-0" />
                    <span className="flex-1 font-medium text-gray-700">{s.tienda}</span>
                    <span className="font-mono text-green-700">{fmt(s.pagado)}</span>
                    <span className="text-gray-300">/</span>
                    <span className="font-mono text-gray-500">{fmt(s.facturado)}</span>
                  </div>
                ))}
                {data.por_sede.length === 0 && <p className="text-sm text-gray-400">Sin datos</p>}
              </div>
            </div>
          </div>

          {/* Filtros lista */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative flex-1 min-w-[200px]">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input value={busqueda} onChange={e => setBusqueda(e.target.value)} placeholder="Buscar proveedor, factura o producto…"
                className="w-full pl-9 pr-3 py-2 border border-gray-200 rounded-lg text-sm" />
            </div>
            <select value={fProveedor} onChange={e => setFProveedor(e.target.value)}
              className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white">
              <option value="">Todos los proveedores</option>
              {proveedores.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
            <select value={fEstado} onChange={e => setFEstado(e.target.value)}
              className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white">
              <option value="">Todo estado</option>
              <option value="pagado">Pagado</option>
              <option value="parcial">Parcial</option>
              <option value="pendiente">Pendiente</option>
            </select>
          </div>

          {/* Lista de facturas */}
          <div className="space-y-2">
            {facturas.map(f => {
              const e = ESTADO[f.estado_pago]
              return (
                <div key={f.id} className="bg-white border border-gray-200 rounded-2xl p-4">
                  <div className="flex items-start gap-3">
                    {/* Foto factura */}
                    {f.imagen_url ? (
                      <a href={f.imagen_url} target="_blank" rel="noreferrer" className="shrink-0" title="Ver factura">
                        <img src={f.imagen_url} alt="factura" className="h-14 w-14 object-cover rounded-lg border border-gray-200 hover:opacity-80" />
                      </a>
                    ) : (
                      <div className="h-14 w-14 shrink-0 rounded-lg border border-dashed border-gray-200 flex items-center justify-center text-[9px] text-gray-400">factura</div>
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-sm font-bold text-gray-800 truncate">{f.proveedor}</p>
                        <span className={`text-[11px] px-2 py-0.5 rounded-full font-bold flex items-center gap-1 shrink-0 ${e.cls}`}>
                          <e.Icon size={11} /> {e.label}
                        </span>
                      </div>
                      <p className="text-xs text-gray-400 mt-0.5">
                        {f.numero_factura ? `Fact. ${f.numero_factura} · ` : ''}
                        {f.tienda_nombre || ''}{f.fecha_recibido ? ` · ${new Date(f.fecha_recibido).toLocaleDateString('es-CO')}` : ''}
                      </p>
                      {/* Cuándo hay que pagarla — lo mismo que ve la agenda de Costos */}
                      {(f.fecha_vencimiento || f.fecha_programada || f.plazo_dias != null) && (
                        <p className={`text-xs mt-0.5 flex items-center gap-1 ${f.vencida ? 'text-red-600 font-semibold' : 'text-gray-400'}`}>
                          <CalendarClock size={12} />
                          {f.fecha_programada
                            ? `La pagás el ${fechaCorta(f.fecha_programada)}`
                            : f.fecha_vencimiento
                              ? `Vence ${fechaCorta(f.fecha_vencimiento)}`
                              : `Plazo ${f.plazo_dias} días`}
                          {f.vencida && ' · VENCIDA'}
                        </p>
                      )}
                      <div className="flex items-center gap-3 mt-1.5 text-sm flex-wrap">
                        <span className="text-gray-500">Total: <span className="font-mono font-bold text-gray-800">{fmt(f.valor_total)}</span></span>
                        <span className="text-gray-500">Pagado: <span className="font-mono font-bold text-green-700">{fmt(f.valor_pagado)}</span></span>
                        {f.saldo > 0 && <span className="text-gray-500">Saldo: <span className="font-mono font-bold text-red-600">{fmt(f.saldo)}</span></span>}
                        {f.forma_pago_real && (
                          <span className="text-[11px] px-2 py-0.5 rounded-full font-bold bg-blue-50 text-blue-700 border border-blue-100">
                            Pagado con {f.forma_pago_real}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                  {/* Productos ingresados (detalle expandible) */}
                  {f.items.length > 0 && (
                    <div className="mt-2">
                      <button onClick={() => setDetalleAbierto(d => (d === f.id ? null : f.id))}
                        className="text-xs font-semibold text-gray-500 hover:text-gray-700">
                        {detalleAbierto === f.id ? '▾' : '▸'} Productos ingresados ({f.items.length})
                      </button>
                      {detalleAbierto === f.id && (
                        <div className="mt-1.5 ml-3 pl-3 border-l-2 border-gray-100 space-y-1">
                          {f.items.map((i, idx) => (
                            <div key={idx} className="flex items-center justify-between gap-2 text-xs">
                              <span className="text-gray-600 truncate">{i.producto_nombre}</span>
                              <span className="font-mono font-semibold text-gray-800 shrink-0">
                                {Math.round(i.cantidad)} {i.unidad_medida}
                                {i.precio_unitario ? ` · ${fmt(i.precio_unitario)} c/u` : ''}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                  {/* Acciones + soportes */}
                  <div className="flex items-center gap-2 mt-3 pt-3 border-t border-gray-50 flex-wrap">
                    {f.imagen_url && (
                      <a href={f.imagen_url} download target="_blank" rel="noreferrer"
                        className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 px-2 py-1 rounded-lg border border-gray-200">
                        <Download size={12} /> Factura
                      </a>
                    )}
                    {f.imagen_soporte_url ? (
                      <a href={f.imagen_soporte_url} download target="_blank" rel="noreferrer"
                        className="flex items-center gap-1 text-xs text-green-700 hover:text-green-800 px-2 py-1 rounded-lg border border-green-200 bg-green-50">
                        <Download size={12} /> Soporte de pago
                      </a>
                    ) : (
                      <span className="text-xs text-gray-300">Sin soporte de pago</span>
                    )}
                    {f.estado_pago !== 'pagado' && (
                      <button onClick={() => { setPagoFactura(f); setMonto(String(Math.round(f.saldo))); setPagoError('') }}
                        className="ml-auto flex items-center gap-1.5 text-xs font-bold text-white bg-forest hover:bg-forest-700 px-3 py-1.5 rounded-lg">
                        <Wallet size={13} /> Registrar pago
                      </button>
                    )}
                    <button onClick={() => abrirEditar(f)}
                      title="Corregir montos (ej. un cero de más)"
                      className={`flex items-center gap-1 text-xs font-semibold text-blue-600 hover:text-blue-700 px-2 py-1 rounded-lg border border-blue-100 hover:border-blue-300 ${f.estado_pago === 'pagado' ? 'ml-auto' : ''}`}>
                      <Pencil size={12} /> Editar
                    </button>
                    <button
                      onClick={async () => {
                        if (!window.confirm(`¿Eliminar la factura de ${f.proveedor} por ${fmt(f.valor_total)}?\n\nSe revierte TODO: la entrada de inventario, los lotes y el egreso de caja si se pagó en efectivo.`)) return
                        try {
                          await api.delete(`/facturas/${f.id}`)
                          cargar()
                        } catch (e: any) {
                          alert(e.response?.data?.detail || 'No se pudo eliminar')
                        }
                      }}
                      title="Eliminar factura (revierte inventario y caja)"
                      className={`flex items-center gap-1 text-xs font-semibold text-red-500 hover:text-red-700 px-2 py-1 rounded-lg border border-red-100 hover:border-red-300 ${f.estado_pago === 'pagado' ? 'ml-auto' : ''}`}>
                      <Trash2 size={12} /> Eliminar
                    </button>
                  </div>
                </div>
              )
            })}
            {facturas.length === 0 && (
              <div className="bg-white border border-gray-200 rounded-2xl px-4 py-10 text-center">
                <Receipt size={26} className="text-gray-300 mx-auto mb-2" />
                <p className="text-sm text-gray-500">No hay facturas con esos filtros</p>
              </div>
            )}
          </div>
        </>
      )}

      {/* Modal editar factura completa */}
      {editFactura && (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-4" onClick={() => setEditFactura(null)}>
          <div className="bg-white rounded-2xl w-full max-w-lg p-5 space-y-4 max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h3 className="text-base font-bold text-gray-800">Editar factura</h3>
              <button onClick={() => setEditFactura(null)} className="text-gray-400 hover:text-gray-600"><X size={18} /></button>
            </div>

            {/* Metadata */}
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2">
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Proveedor</label>
                <input value={editProveedor} onChange={e => setEditProveedor(e.target.value)}
                  className="w-full border-2 border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-forest" />
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">N° factura</label>
                <input value={editNumero} onChange={e => setEditNumero(e.target.value)}
                  className="w-full border-2 border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-forest" />
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Fecha recibido</label>
                <input type="date" value={editFecha} onChange={e => setEditFecha(e.target.value)}
                  className="w-full border-2 border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-forest" />
              </div>
              <div className="col-span-2">
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Tipo de pago</label>
                <select value={editTipoPago} onChange={e => setEditTipoPago(e.target.value)}
                  className="w-full border-2 border-gray-200 rounded-xl px-3 py-2 text-sm bg-white focus:outline-none focus:border-forest">
                  <option value="contado">Contado (efectivo)</option>
                  <option value="transferencia">Transferencia</option>
                  <option value="credito">Crédito</option>
                </select>
              </div>
            </div>

            {/* Vencimiento: lo que mete la factura en la agenda de Costos */}
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5 flex items-center gap-1">
                <CalendarClock size={13} /> Cuándo hay que pagarla
              </p>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="text-[11px] text-gray-500 block mb-1">Vence</label>
                  <input type="date" value={editVence} onChange={e => setEditVence(e.target.value)}
                    className="w-full border-2 border-gray-200 rounded-xl px-2 py-2 text-sm focus:outline-none focus:border-forest" />
                </div>
                <div>
                  <label className="text-[11px] text-gray-500 block mb-1">Plazo (días)</label>
                  <input type="number" inputMode="numeric" min={0} value={editPlazo}
                    onChange={e => setEditPlazo(e.target.value)} placeholder="30"
                    className="w-full border-2 border-gray-200 rounded-xl px-2 py-2 text-sm font-mono focus:outline-none focus:border-forest" />
                </div>
                <div>
                  <label className="text-[11px] text-gray-500 block mb-1">La vas a pagar el</label>
                  <input type="date" value={editProgramada} onChange={e => setEditProgramada(e.target.value)}
                    className="w-full border-2 border-gray-200 rounded-xl px-2 py-2 text-sm focus:outline-none focus:border-forest" />
                </div>
              </div>
              <p className="text-[11px] text-gray-400 mt-1">
                Si no ponés fecha de vencimiento, se calcula con el plazo desde el día que la
                recibiste. La fecha que vos elegís para pagarla manda sobre las dos. Sin ninguna
                de las tres, la factura no entra en la agenda de Costos.
              </p>
            </div>

            {/* Productos */}
            {editItems.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Productos ingresados</p>
                <div className="rounded-xl border border-gray-200 divide-y divide-gray-50">
                  {editItems.map(it => (
                    <div key={it.id} className="flex items-center gap-2 px-3 py-2">
                      <span className="flex-1 min-w-0 text-sm text-gray-700 truncate">{it.nombre}</span>
                      <input type="number" inputMode="decimal" min={0} value={it.cantidad}
                        onChange={e => setEditItems(prev => prev.map(x => x.id === it.id ? { ...x, cantidad: e.target.value } : x))}
                        className="w-16 text-right rounded-lg border-2 border-gray-200 px-2 py-1 text-sm font-bold font-mono focus:outline-none" />
                      <span className="text-[11px] text-gray-400 w-8">{it.unidad}</span>
                      <div className="flex items-center gap-0.5">
                        <span className="text-[11px] text-gray-400">$</span>
                        <input type="text" inputMode="numeric" value={conMiles(it.precio)}
                          onChange={e => setEditItems(prev => prev.map(x => x.id === it.id ? { ...x, precio: soloDigitos(e.target.value) } : x))}
                          placeholder="c/u"
                          className="w-20 text-right rounded-lg border-2 border-gray-200 px-2 py-1 text-xs font-mono focus:outline-none" />
                      </div>
                      <button onClick={() => quitarItemEdit(it.id)} className="text-red-400 hover:text-red-600" title="Quitar producto (revierte su entrada)"><X size={14} /></button>
                    </div>
                  ))}
                </div>
                <p className="text-[11px] text-gray-400 mt-1">Cambiar la cantidad ajusta el inventario por la diferencia; quitar un producto revierte su entrada.</p>
              </div>
            )}

            {/* Montos */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Total factura</label>
                <input type="text" inputMode="numeric" value={conMiles(editTotal)} onChange={e => setEditTotal(soloDigitos(e.target.value))}
                  className="w-full border-2 border-gray-200 rounded-xl px-3 py-2 text-base font-bold font-mono focus:outline-none focus:border-forest" />
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Ya pagado</label>
                <input type="text" inputMode="numeric" value={conMiles(editPagado)} onChange={e => setEditPagado(soloDigitos(e.target.value))}
                  className="w-full border-2 border-gray-200 rounded-xl px-3 py-2 text-base font-bold font-mono focus:outline-none focus:border-forest" />
              </div>
            </div>
            <p className="text-[11px] text-gray-400 -mt-1">Si el pago fue en efectivo, el egreso de caja se ajusta solo por la diferencia.</p>

            {editError && <p className="text-sm text-red-600">{editError}</p>}
            <button onClick={guardarEdicion} disabled={guardando}
              className="w-full bg-forest hover:bg-forest-700 disabled:opacity-50 text-white font-bold py-2.5 rounded-xl">
              {guardando ? 'Guardando…' : 'Guardar cambios'}
            </button>
          </div>
        </div>
      )}

      {/* Modal registrar pago */}
      {pagoFactura && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setPagoFactura(null)}>
          <div className="bg-white rounded-2xl w-full max-w-sm p-5 space-y-4" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h2 className="font-bold text-gray-800">Registrar pago</h2>
              <button onClick={() => setPagoFactura(null)} className="text-gray-400"><X size={18} /></button>
            </div>
            <div className="text-sm text-gray-500">
              <p className="font-semibold text-gray-700">{pagoFactura.proveedor}</p>
              <p>Saldo pendiente: <span className="font-mono font-bold text-red-600">{fmt(pagoFactura.saldo)}</span></p>
            </div>
            <div>
              <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Monto a pagar</label>
              <input type="text" inputMode="numeric" value={conMiles(monto)} onChange={e => setMonto(soloDigitos(e.target.value))}
                className="w-full border-2 border-gray-200 rounded-xl px-4 py-2.5 text-lg font-bold font-mono focus:outline-none focus:border-forest" />
            </div>
            <div>
              <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Forma de pago</label>
              <select value={formaPago} onChange={e => setFormaPago(e.target.value)}
                className="w-full border-2 border-gray-200 rounded-xl px-4 py-2.5 text-sm bg-white">
                <option value="efectivo">Efectivo (sale del cajón)</option>
                <option value="transferencia">Bancos</option>
                <option value="cheque">Cheque</option>
                <option value="otro">Otro</option>
              </select>
            </div>
            <div>
              <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Foto del soporte (opcional)</label>
              <label className="flex items-center gap-2 border-2 border-dashed border-gray-200 rounded-xl px-4 py-3 cursor-pointer text-sm text-gray-500">
                <Camera size={16} /> {soporte ? soporte.name : 'Adjuntar comprobante'}
                <input type="file" accept="image/*" capture="environment" className="hidden"
                  onChange={e => setSoporte(e.target.files?.[0] ?? null)} />
              </label>
            </div>
            {pagoError && (
              <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-xl px-3 py-2">{pagoError}</p>
            )}
            <button onClick={registrarPago} disabled={guardando || !monto || Number(monto) <= 0}
              className="w-full bg-forest hover:bg-forest-700 disabled:opacity-40 text-white font-bold py-3 rounded-xl text-sm">
              {guardando ? 'Guardando...' : 'Confirmar pago'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
