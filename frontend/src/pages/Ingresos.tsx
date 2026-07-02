import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useEmbedded } from '../contexts/PanelContext'
import api from '../api/client'
import { conMiles, soloDigitos } from '../utils/plata'
import {
  ArrowLeft, ChevronDown, ChevronRight, Search, Plus, X,
  Check, Trash2, Croissant, Box, Upload,
} from 'lucide-react'

// ─── Types ───────────────────────────────────────────────────────────────────

interface Producto {
  id: number
  nombre: string
  categoria: string
  unidad_medida: string
}

interface ProveedorHistorial {
  proveedor: string
  frecuencia: number
  total_gastado: number
  ultima: string | null
}

interface ItemForm {
  producto_id: number
  nombre: string
  unidad_medida: string
  categoria: string
  cantidad: string
  numero_lote: string
  fecha_vencimiento: string
}

// Hora LOCAL: toISOString es UTC y despues de las 19:00 Colombia devuelve manana.
function hoy() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function fmt(n: number) { return '$' + n.toLocaleString('es-CO') }

function daysAgo(iso: string | null): string {
  if (!iso) return 'nunca'
  const d = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000)
  if (d === 0) return 'hoy'
  if (d === 1) return 'ayer'
  return `hace ${d} días`
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function Ingresos() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const embedded = useEmbedded()

  // Form
  const [proveedor, setProveedor]         = useState('')
  const [fechaRecibido, setFechaRecibido] = useState(hoy())
  const [tipoPago, setTipoPago]           = useState<'contado'|'credito'|'transferencia'>('contado')
  const [valorTotal, setValorTotal]       = useState('')
  const [numeroFactura, setNumeroFactura] = useState('')
  const [imagen, setImagen]               = useState<File | null>(null)
  const [preview, setPreview]             = useState<string | null>(null)
  const fileRef                           = useRef<HTMLInputElement>(null)
  const [items, setItems]                 = useState<ItemForm[]>([])

  // Proveedor picker
  const [showPickerProv, setShowPickerProv] = useState(false)
  const [queryProv, setQueryProv]           = useState('')
  const [historialProv, setHistorialProv]   = useState<ProveedorHistorial[]>([])

  // Quick-add
  const [showQuickAdd, setShowQuickAdd]   = useState(false)
  const [addQuery, setAddQuery]           = useState('')
  const [addProducto, setAddProducto]     = useState<Producto | null>(null)
  const [addCantidad, setAddCantidad]     = useState('')
  const [addLote, setAddLote]             = useState('')
  const [addVence, setAddVence]           = useState('')

  // Data
  const [productos, setProductos] = useState<Producto[]>([])

  // Status
  const [saving, setSaving] = useState(false)
  const [error, setError]   = useState('')
  const [exito, setExito]   = useState(false)

  useEffect(() => {
    api.get('/inventario/productos').then(r => setProductos(r.data))
    if (user?.tienda_id) {
      api.get(`/facturas/proveedores/${user.tienda_id}`)
        .then(r => setHistorialProv(r.data))
        .catch(() => {})
    }
  }, [user?.tienda_id])

  // ── Foto factura ─────────────────────────────────────────────────────────
  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (!f) return
    if (preview) URL.revokeObjectURL(preview)
    setImagen(f)
    setPreview(URL.createObjectURL(f))
  }
  const quitarFoto = () => {
    if (preview) URL.revokeObjectURL(preview)
    setImagen(null); setPreview(null)
    if (fileRef.current) fileRef.current.value = ''
  }

  // ── Abrir quick-add ───────────────────────────────────────────────────────
  const openQuickAdd = () => {
    setAddQuery(''); setAddProducto(null); setAddCantidad('')
    setAddLote(''); setAddVence('')
    setShowQuickAdd(true)
  }

  // ── Confirmar adición de ítem ──────────────────────────────────────────────
  const confirmarAdd = () => {
    if (!addProducto || !addCantidad || Number(addCantidad) <= 0) return
    setItems(prev => [...prev, {
      producto_id:       addProducto.id,
      nombre:            addProducto.nombre,
      unidad_medida:     addProducto.unidad_medida,
      categoria:         addProducto.categoria,
      cantidad:          addCantidad,
      numero_lote:       addLote,
      fecha_vencimiento: addVence,
    }])
    setShowQuickAdd(false)
  }

  const quitarItem = (idx: number) => setItems(prev => prev.filter((_, i) => i !== idx))

  const seleccionarProveedor = (p: string) => {
    setProveedor(p); setShowPickerProv(false); setQueryProv('')
  }

  // ── Guardar factura ────────────────────────────────────────────────────────
  const guardar = async () => {
    if (!proveedor.trim()) return setError('Selecciona o escribe el proveedor')
    if (!valorTotal || Number(valorTotal) <= 0) return setError('El valor total debe ser mayor a 0')
    if (items.length === 0) return setError('Agrega al menos un producto')
    for (const it of items) {
      if (!it.cantidad || Number(it.cantidad) <= 0) return setError(`Cantidad inválida en ${it.nombre}`)
    }
    if (!user?.tienda_id) return
    setError(''); setSaving(true)

    const payload = {
      tienda_id:      user.tienda_id,
      proveedor:      proveedor.trim(),
      numero_factura: numeroFactura.trim() || null,
      numero_lote:    null,
      fecha_recibido: new Date(fechaRecibido + 'T00:00:00').toISOString(),
      valor_total:    Number(valorTotal),
      tipo_pago:      tipoPago,
      items: items.map(it => ({
        producto_id:      it.producto_id,
        cantidad:         Number(it.cantidad),
        precio_unitario:  null,
        numero_lote:      it.numero_lote || null,
        fecha_vencimiento: it.fecha_vencimiento
          ? new Date(it.fecha_vencimiento + 'T00:00:00').toISOString()
          : null,
      })),
    }

    const fd = new FormData()
    fd.append('data', JSON.stringify(payload))
    if (imagen) fd.append('imagen', imagen)

    try {
      await api.post('/facturas/', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
      setExito(true)
      setProveedor(''); setFechaRecibido(hoy()); setTipoPago('contado')
      setValorTotal(''); setNumeroFactura('')
      if (preview) URL.revokeObjectURL(preview)
      setImagen(null); setPreview(null)
      if (fileRef.current) fileRef.current.value = ''
      setItems([])
      setTimeout(() => setExito(false), 3000)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al guardar')
    } finally {
      setSaving(false)
    }
  }

  const filteredProv = historialProv.filter(p =>
    !queryProv || p.proveedor.toLowerCase().includes(queryProv.toLowerCase())
  )
  const suggestedProducts = productos.filter(p =>
    !items.some(i => i.producto_id === p.id) &&
    (!addQuery || p.nombre.toLowerCase().includes(addQuery.toLowerCase()))
  )

  const totalUnidades = items.reduce((s, i) => s + (Number(i.cantidad) || 0), 0)
  const canSave       = !!proveedor && !!valorTotal && Number(valorTotal) > 0 && items.length > 0

  return (
    <div className={embedded ? 'flex flex-col w-full' : 'min-h-screen bg-warm-50 flex flex-col'}>

      {/* ── Header con proveedor tappable ── */}
      <header className={`bg-white border-b border-warm-200 px-4 pb-3 sticky top-0 z-10 ${embedded ? 'pt-3' : 'header-safe'}`}>
        <div className="flex items-center gap-3 max-w-lg mx-auto">
          {!embedded && (
            <button
              onClick={() => navigate('/')}
              className="p-2 -ml-1 rounded-xl text-warm-400 hover:text-warm-700 hover:bg-warm-100 transition-colors"
            >
              <ArrowLeft size={18} />
            </button>
          )}
          <div className="flex-1 min-w-0">
            <p className="text-[10px] font-bold uppercase tracking-widest text-amber-600">
              Ingreso · Mercancía
            </p>
            <button
              onClick={() => setShowPickerProv(true)}
              className="flex items-center gap-1.5 mt-0.5 max-w-full"
            >
              <span className={`text-sm font-bold leading-tight truncate ${proveedor ? 'text-warm-800' : 'text-warm-300'}`}>
                {proveedor || 'Seleccionar proveedor'}
              </span>
              <ChevronDown size={13} className="text-warm-400 shrink-0" />
            </button>
          </div>
          <span className="text-xs text-warm-400 font-mono shrink-0">
            {fechaRecibido.slice(5).replace('-', '/')}
          </span>
        </div>
      </header>

      {/* ── Proveedor picker overlay ──
          Embebido: `absolute` confinado al panel (el POS sigue visible al lado).
          Standalone: `fixed` a pantalla completa. */}
      {showPickerProv && (
        <div
          className={`${embedded ? 'absolute' : 'fixed'} inset-0 z-50 flex flex-col`}
          style={{ background: 'rgba(20,15,10,0.5)', backdropFilter: 'blur(2px)' }}
        >
          <div className="bg-white p-4 border-b border-warm-200" style={{ paddingTop: embedded ? '1rem' : 'max(1rem, env(safe-area-inset-top))' }}>
            <div className="flex items-center justify-between mb-3">
              <p className="text-[10px] font-bold uppercase tracking-widest text-warm-400">Proveedor</p>
              <button onClick={() => { setShowPickerProv(false); setQueryProv('') }}
                className="p-1.5 rounded-lg text-warm-400 hover:bg-warm-100">
                <X size={16} />
              </button>
            </div>
            <div className="flex items-center gap-2 border-2 border-amber-500 rounded-xl px-3 py-2.5"
              style={{ boxShadow: '0 0 0 4px rgba(217,119,6,0.12)' }}>
              <Search size={14} className="text-amber-500 shrink-0" />
              <input
                value={queryProv}
                onChange={e => setQueryProv(e.target.value)}
                placeholder="Buscar o escribir proveedor…"
                className="flex-1 text-sm font-medium text-warm-800 bg-transparent outline-none placeholder:text-warm-300"
                autoFocus
              />
              {queryProv && (
                <button onClick={() => setQueryProv('')}><X size={12} className="text-warm-400" /></button>
              )}
            </div>
            {filteredProv.length > 0 && (
              <p className="text-[11px] text-warm-400 mt-2">
                {filteredProv.length} {filteredProv.length === 1 ? 'coincidencia' : 'coincidencias'}
              </p>
            )}
          </div>

          <div className="flex-1 bg-warm-50 overflow-auto">
            {filteredProv.map(p => (
              <button
                key={p.proveedor}
                onClick={() => seleccionarProveedor(p.proveedor)}
                className="w-full flex items-center gap-3 px-4 py-3 bg-white border-b border-warm-100 hover:bg-amber-50 text-left active:bg-amber-100 transition-colors"
              >
                <div className="w-8 h-8 rounded-xl bg-amber-50 text-amber-600 flex items-center justify-center text-sm font-bold font-mono shrink-0">
                  {p.proveedor[0].toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-bold text-warm-800 truncate">
                    <HighlightText text={p.proveedor} match={queryProv} />
                  </p>
                  <p className="text-[10px] text-warm-400 mt-0.5">
                    {p.frecuencia} {p.frecuencia === 1 ? 'factura' : 'facturas'} · última {daysAgo(p.ultima)}
                  </p>
                </div>
                <ChevronRight size={14} className="text-warm-300 shrink-0" />
              </button>
            ))}

            {queryProv && !filteredProv.some(p => p.proveedor.toLowerCase() === queryProv.toLowerCase()) && (
              <button
                onClick={() => seleccionarProveedor(queryProv.trim())}
                className="flex items-center justify-center gap-2 mx-4 my-3 px-4 py-3 border-2 border-dashed border-warm-200 rounded-2xl text-sm font-bold text-amber-600 w-[calc(100%-2rem)] hover:border-amber-400 hover:bg-amber-50 transition-colors"
              >
                <Plus size={14} /> Crear proveedor "{queryProv}"
              </button>
            )}

            {filteredProv.length === 0 && !queryProv && (
              <p className="text-sm text-warm-400 text-center py-10">
                Escribe el nombre del proveedor
              </p>
            )}
          </div>
        </div>
      )}

      {/* ── Contenido scrollable ── */}
      <div className={`flex-1 ${embedded ? '' : 'overflow-auto pb-nav'}`}>
        <div className="max-w-lg mx-auto">

          {/* ── Hero: valor total ── */}
          <div className="bg-white border-b border-warm-100 px-4 py-3 flex items-center gap-4">
            <div className="flex-1">
              <p className="text-[9px] font-bold uppercase tracking-widest text-warm-400">Total factura</p>
              <div className="flex items-baseline gap-1 mt-1">
                <span className="text-lg font-bold text-warm-400">$</span>
                <input
                  type="text"
                  inputMode="numeric"
                  value={conMiles(valorTotal)}
                  onChange={e => setValorTotal(soloDigitos(e.target.value))}
                  placeholder="0"
                  className="text-2xl font-bold text-warm-800 bg-transparent outline-none w-full font-mono tracking-tight placeholder:text-warm-200"
                />
              </div>
              <p className="text-[10px] text-warm-400 mt-0.5">Solo el total · sin precio por producto</p>
            </div>
            {items.length > 0 && (
              <div className="text-right shrink-0">
                <p className="text-xl font-bold text-amber-600 font-mono">{totalUnidades}</p>
                <p className="text-[10px] text-warm-400">
                  {items.length} {items.length === 1 ? 'producto' : 'productos'}
                </p>
              </div>
            )}
          </div>

          {/* ── Header lista de productos ── */}
          <div className="flex items-center justify-between px-4 pt-4 pb-2">
            <p className="text-[10px] font-bold uppercase tracking-widest text-warm-400">
              Productos recibidos{items.length > 0 ? ` · ${items.length}` : ''}
            </p>
            {items.length > 0 && !showQuickAdd && (
              <button onClick={openQuickAdd} className="flex items-center gap-1 text-[11px] font-bold text-amber-600">
                <Plus size={12} /> Otro
              </button>
            )}
          </div>

          {/* ── Lista de ítems ── */}
          {items.length > 0 && (
            <div className="mx-4 bg-white border border-warm-100 rounded-2xl overflow-hidden">
              {items.map((it, idx) => (
                <div key={`${it.producto_id}-${idx}`}
                  className={`px-3 py-2.5 ${idx < items.length - 1 ? 'border-b border-warm-100' : ''}`}>
                  {/* Fila 1: nombre + cantidad + borrar */}
                  <div className="flex items-center gap-2 mb-2">
                    {it.numero_lote || it.fecha_vencimiento
                      ? <Croissant size={13} className="text-amber-500 shrink-0" />
                      : <Box size={13} className="text-warm-400 shrink-0" />
                    }
                    <span className="flex-1 text-[13px] font-bold text-warm-800 truncate">{it.nombre}</span>
                    <span className="text-[13px] font-bold text-warm-600 font-mono shrink-0">
                      {it.cantidad} {it.unidad_medida}
                    </span>
                    <button
                      onClick={() => quitarItem(idx)}
                      className="w-6 h-6 rounded-md flex items-center justify-center text-warm-300 hover:text-red-400 hover:bg-red-50 shrink-0 transition-colors"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                  {/* Fila 2: chips lote + vence */}
                  {(it.numero_lote || it.fecha_vencimiento) && (
                    <div className="grid grid-cols-2 gap-1.5">
                      {it.numero_lote && (
                        <FieldChip label="Lote" value={it.numero_lote} />
                      )}
                      {it.fecha_vencimiento && (
                        <FieldChip label="Vence" value={it.fecha_vencimiento.slice(5).replace('-', '/')} />
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* ── Quick-add panel o botón dashed ── */}
          {showQuickAdd ? (
            <QuickAddPanel
              productos={suggestedProducts}
              addQuery={addQuery}     setAddQuery={setAddQuery}
              addProducto={addProducto} setAddProducto={setAddProducto}
              addCantidad={addCantidad} setAddCantidad={setAddCantidad}
              addLote={addLote}       setAddLote={setAddLote}
              addVence={addVence}     setAddVence={setAddVence}
              onCancel={() => setShowQuickAdd(false)}
              onConfirm={confirmarAdd}
            />
          ) : (
            <button
              onClick={openQuickAdd}
              className="flex items-center justify-center gap-2 mx-4 mt-3 px-4 py-3.5 w-[calc(100%-2rem)] border-2 border-dashed border-warm-200 rounded-2xl text-[13px] font-semibold text-warm-400 hover:border-amber-400 hover:bg-amber-50 hover:text-amber-600 transition-colors bg-white active:scale-95"
            >
              <Plus size={14} />
              Agregar {items.length === 0 ? 'primer' : 'otro'} producto
            </button>
          )}

          {/* ── Foto de la factura ── */}
          <div className="mx-4 mt-4">
            <div className="bg-white rounded-2xl border border-warm-200 p-4 space-y-3">
              <p className="text-sm font-bold text-warm-700">
                Foto de la factura
                <span className="ml-1.5 text-xs font-normal text-warm-400">(opcional)</span>
              </p>
              <input ref={fileRef} type="file" accept="image/*" capture="environment" onChange={onFile} className="hidden" />
              {preview ? (
                <div className="relative">
                  <img src={preview} alt="preview" className="w-full h-36 object-cover rounded-xl border-2 border-amber-300" />
                  <button
                    onClick={quitarFoto}
                    className="absolute top-2 right-2 bg-black/60 text-white rounded-full w-7 h-7 flex items-center justify-center"
                  >
                    <X size={13} />
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => fileRef.current?.click()}
                  className="w-full h-28 border-2 border-dashed border-warm-200 rounded-xl flex flex-col items-center justify-center gap-2 hover:border-amber-400 hover:bg-amber-50 transition-colors"
                >
                  <Upload size={22} className="text-warm-300" />
                  <span className="text-xs text-warm-400 font-medium">Toca para fotografiar la factura</span>
                </button>
              )}
            </div>
          </div>

          {/* ── Campos opcionales ── */}
          <div className="mx-4 mt-4">
            <details className="bg-white border border-warm-100 rounded-2xl overflow-hidden">
              <summary className="px-4 py-3 text-[12px] font-semibold text-warm-500 cursor-pointer list-none flex items-center justify-between select-none">
                Datos adicionales
                <ChevronDown size={14} className="text-warm-300" />
              </summary>
              <div className="px-4 pb-4 pt-3 space-y-3 border-t border-warm-100">
                <div>
                  <label className="text-[10px] font-bold uppercase tracking-wide text-warm-400">N° Factura</label>
                  <input value={numeroFactura} onChange={e => setNumeroFactura(e.target.value)}
                    placeholder="Ej: FV-001"
                    className="w-full mt-1 border-2 border-warm-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-amber-400" />
                </div>
                <div>
                  <label className="text-[10px] font-bold uppercase tracking-wide text-warm-400">Tipo de pago</label>
                  <select value={tipoPago} onChange={e => setTipoPago(e.target.value as typeof tipoPago)}
                    className="w-full mt-1 border-2 border-warm-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-amber-400 bg-white">
                    <option value="contado">Contado (efectivo)</option>
                    <option value="credito">Crédito</option>
                    <option value="transferencia">Bancos</option>
                  </select>
                </div>
                <div>
                  <label className="text-[10px] font-bold uppercase tracking-wide text-warm-400">Fecha recibido</label>
                  <input type="date" value={fechaRecibido} onChange={e => setFechaRecibido(e.target.value)}
                    className="w-full mt-1 border-2 border-warm-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-amber-400" />
                </div>
              </div>
            </details>
          </div>

          {/* Feedback */}
          {error && (
            <div className="mx-4 mt-3 px-3 py-2.5 bg-red-50 border border-red-100 rounded-xl text-sm text-red-600">
              {error}
            </div>
          )}
          {exito && (
            <div className="mx-4 mt-3 px-3 py-2.5 bg-green-50 border border-green-100 rounded-xl flex items-center gap-2 text-sm font-semibold text-green-700">
              <Check size={15} /> Ingreso registrado correctamente
            </div>
          )}

          <div className="h-6" />
        </div>
      </div>

      {/* ── CTA sticky encima del nav ──
          Embebido: `sticky` al pie del panel. Standalone: `fixed` sobre el bottom-nav. */}
      <div
        className={`${embedded ? 'sticky' : 'fixed'} left-0 right-0 px-4 pt-3 pb-2 z-20`}
        style={{
          bottom: embedded ? 0 : 'calc(4.5rem + env(safe-area-inset-bottom, 0px))',
          background: 'linear-gradient(to top, oklch(98% 0.006 75) 75%, transparent)',
        }}
      >
        <div className="max-w-lg mx-auto">
          <button
            onClick={guardar}
            disabled={saving || !canSave}
            className="w-full py-4 rounded-2xl text-[15px] font-bold text-white disabled:opacity-40 transition-all flex items-center justify-center gap-2 active:scale-[0.98]"
            style={{
              background: 'oklch(35% 0.05 155)',
              boxShadow: canSave && !saving ? '0 6px 16px oklch(35% 0.05 155 / 0.25)' : 'none',
            }}
          >
            <Check size={16} strokeWidth={2.5} />
            {saving ? 'Guardando…' : valorTotal ? `Registrar · ${fmt(Number(valorTotal))}` : 'Registrar ingreso'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── FieldChip ───────────────────────────────────────────────────────────────

function FieldChip({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-1.5 px-2 py-1.5 bg-warm-50 border border-warm-100 rounded-lg">
      <span className="text-[9px] font-bold uppercase tracking-wide text-warm-400">{label}</span>
      <span className="text-[12px] font-semibold text-warm-700 font-mono flex-1 text-right">{value}</span>
    </div>
  )
}

// ─── HighlightText ───────────────────────────────────────────────────────────

function HighlightText({ text, match }: { text: string; match: string }) {
  if (!match) return <>{text}</>
  const idx = text.toLowerCase().indexOf(match.toLowerCase())
  if (idx < 0) return <>{text}</>
  return (
    <>
      {text.slice(0, idx)}
      <mark className="bg-amber-100 text-warm-800 rounded px-0.5 not-italic">
        {text.slice(idx, idx + match.length)}
      </mark>
      {text.slice(idx + match.length)}
    </>
  )
}

// ─── QuickAddPanel ───────────────────────────────────────────────────────────

interface QuickAddProps {
  productos: Producto[]
  addQuery: string;      setAddQuery: (v: string) => void
  addProducto: Producto | null; setAddProducto: (p: Producto | null) => void
  addCantidad: string;   setAddCantidad: (v: string) => void
  addLote: string;       setAddLote: (v: string) => void
  addVence: string;      setAddVence: (v: string) => void
  onCancel: () => void
  onConfirm: () => void
}

function QuickAddPanel({
  productos, addQuery, setAddQuery, addProducto, setAddProducto,
  addCantidad, setAddCantidad, addLote, setAddLote, addVence, setAddVence,
  onCancel, onConfirm,
}: QuickAddProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  useEffect(() => { inputRef.current?.focus() }, [])

  return (
    <div
      className="mx-4 mt-3 bg-white rounded-2xl p-3"
      style={{ border: '2px solid oklch(55% 0.12 155)', boxShadow: '0 8px 24px oklch(35% 0.05 155 / 0.15)' }}
    >
      <p className="text-[10px] font-bold uppercase tracking-widest mb-2.5" style={{ color: 'oklch(35% 0.05 155)' }}>
        Nuevo producto
      </p>

      {!addProducto ? (
        <>
          {/* Buscador */}
          <div className="flex items-center gap-2 px-3 py-2.5 bg-warm-50 border border-warm-200 rounded-xl mb-2">
            <Search size={13} className="text-warm-400 shrink-0" />
            <input
              ref={inputRef}
              value={addQuery}
              onChange={e => setAddQuery(e.target.value)}
              placeholder="Buscar producto…"
              className="flex-1 text-[13px] text-warm-700 bg-transparent outline-none placeholder:text-warm-300"
            />
          </div>
          {/* Lista */}
          <div className="max-h-40 overflow-y-auto rounded-xl border border-warm-100 divide-y divide-warm-50">
            {productos.slice(0, 8).map(p => (
              <button key={p.id} onClick={() => { setAddProducto(p); setAddQuery('') }}
                className="w-full text-left px-3 py-2.5 hover:bg-amber-50 transition-colors">
                <p className="text-[13px] font-semibold text-warm-700">{p.nombre}</p>
                <p className="text-[10px] text-warm-400">{p.categoria} · {p.unidad_medida}</p>
              </button>
            ))}
            {productos.length === 0 && (
              <p className="text-[12px] text-warm-400 text-center py-4">Sin resultados</p>
            )}
          </div>
        </>
      ) : (
        <>
          {/* Producto seleccionado */}
          <div className="flex items-center gap-2 mb-3 px-3 py-2 bg-amber-50 rounded-xl border border-amber-200">
            <Croissant size={14} className="text-amber-500 shrink-0" />
            <span className="text-[13px] font-bold text-warm-800 flex-1 truncate">{addProducto.nombre}</span>
            <button onClick={() => setAddProducto(null)} className="text-warm-300 hover:text-warm-500">
              <X size={13} />
            </button>
          </div>
          {/* Campos */}
          <div className="grid grid-cols-2 gap-2 mb-2">
            <CompactInput
              label={`Cantidad (${addProducto.unidad_medida})`}
              value={addCantidad} onChange={setAddCantidad}
              type="number" placeholder="0"
            />
            <CompactInput label="Lote" value={addLote} onChange={setAddLote} placeholder="—" />
            <CompactInput label="Vence" value={addVence} onChange={setAddVence} type="date" placeholder="" />
          </div>
        </>
      )}

      <div className="flex gap-2 mt-3">
        <button onClick={onCancel}
          className="flex-1 py-2.5 border border-warm-200 rounded-xl text-[12px] font-semibold text-warm-500 hover:bg-warm-50 transition-colors">
          Cancelar
        </button>
        <button onClick={onConfirm}
          disabled={!addProducto || !addCantidad}
          className="flex-[2] py-2.5 rounded-xl text-[12px] font-bold text-white disabled:opacity-40"
          style={{ background: 'oklch(35% 0.05 155)' }}>
          Agregar a la factura
        </button>
      </div>
    </div>
  )
}

// ─── CompactInput ────────────────────────────────────────────────────────────

function CompactInput({ label, value, onChange, type = 'text', placeholder, readOnly }: {
  label: string; value: string; onChange: (v: string) => void
  type?: string; placeholder?: string; readOnly?: boolean
}) {
  return (
    <div>
      <p className="text-[9px] font-bold uppercase tracking-wide text-warm-400 mb-1">{label}</p>
      <input
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        readOnly={readOnly}
        className="w-full px-2.5 py-2 border border-warm-200 rounded-lg text-[13px] font-semibold text-warm-700 font-mono focus:outline-none focus:border-amber-400 bg-white"
      />
    </div>
  )
}
