import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, ShoppingBag, Printer, ChevronUp, X, LayoutGrid } from 'lucide-react'
import { dark } from '../constants/darkTheme'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import CheckoutModal from '../components/CheckoutModal'
import TicketRecibo, { TicketData } from '../components/TicketRecibo'
import ProductGrid, { Producto } from '../components/ProductGrid'
import Cart, { CartItem } from '../components/Cart'
import { Toast, Sheet, Pill } from '../components/ui'
import DockBar from '../components/DockBar'
import PanelTurno from '../components/PanelTurno'
import BannerOperativo from '../components/BannerOperativo'
import { useRutinasEstado } from '../hooks/useRutinasEstado'
import Ingresos from './Ingresos'
import Mermas from './Mermas'
import Inventario from './Inventario'
import SolicitudPedido from './SolicitudPedido'
import SolicitudSencilla from './SolicitudSencilla'
import Consignaciones from './Consignaciones'

// ─── Helpers ───────────────────────────────────────────────────────────────

const fmtCO = (v: number) => `$${v.toLocaleString('es-CO')}`

// Shape que devuelve GET /pos/tickets (TicketOut del backend).
interface TicketApi {
  id: number
  fecha: string
  total: number
  cambio: number | null
  metodo_pago: 'efectivo' | 'tarjeta' | 'mixto'
  efectivo_recibido?: number | null
  monto_efectivo?: number | null
  monto_tarjeta?: number | null
  items: Array<{
    nombre_producto: string
    cantidad: number
    precio_unitario: number
    subtotal: number
    descuento?: number
  }>
}

function toTicketData(t: TicketApi): TicketData {
  return {
    id: t.id,
    fecha: t.fecha,
    total: t.total,
    cambio: t.cambio ?? 0,
    metodo_pago: t.metodo_pago,
    efectivo_recibido: t.efectivo_recibido ?? undefined,
    monto_efectivo: t.monto_efectivo ?? undefined,
    monto_tarjeta: t.monto_tarjeta ?? undefined,
    items: t.items.map(i => ({ ...i, descuento: i.descuento ?? 0 })),
  }
}

// ─── Guard wrapper ───────────────────────────────────────────────────────────

function GuardShell({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate()
  return (
    <div className="min-h-screen bg-warm-50 flex flex-col">
      <header className="bg-white border-b border-warm-200 px-4 pb-3 header-safe flex items-center gap-3 sticky top-0 z-10">
        <button
          onClick={() => navigate('/hub')}
          className="p-2 rounded-xl text-warm-400 hover:text-warm-700 hover:bg-warm-100 transition-colors -ml-1"
        >
          <ArrowLeft size={18} />
        </button>
        <span className="flex-1 text-sm font-bold text-warm-700">POS</span>
      </header>
      <main className="flex-1 p-4 max-w-lg mx-auto w-full pb-nav">{children}</main>
    </div>
  )
}

// ─── Componente ──────────────────────────────────────────────────────────────

export default function POS() {
  const { turno } = useTurno()
  const navigate = useNavigate()
  const { estados: rutinasEstado, bitacora: rutinaBitacora, registrar: registrarRutina } = useRutinasEstado(
    turno?.tienda_id ?? null,
  )
  const alertCount = rutinasEstado.filter(e => e.track && e.status === 'alert').length

  // Hooks antes de cualquier return condicional.
  const [productos, setProductos] = useState<Producto[]>([])
  const [cart, setCart] = useState<CartItem[]>([])
  const [search, setSearch] = useState('')
  const [catFiltro, setCatFiltro] = useState('todas')
  const [soloFavoritos, setSoloFavoritos] = useState(false)
  const [showCheckout, setShowCheckout] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [cancelToast, setCancelToast] = useState(false)
  const [loading, setLoading] = useState(true)
  const [cartSheet, setCartSheet] = useState(false)
  const [reprintTicket, setReprintTicket] = useState<TicketData | null>(null)
  const [reprintMsg, setReprintMsg] = useState('')
  const [activePanel, setActivePanel] = useState<string | null>(null)

  const PANELS: Record<string, React.ReactNode> = {
    ingresos:       <Ingresos />,
    mermas:         <Mermas />,
    inventario:     <Inventario />,
    pedido:         <SolicitudPedido />,
    sencilla:       <SolicitudSencilla />,
    consignaciones: <Consignaciones />,
    turno: (
      <PanelTurno
        turno={turno!}
        estados={rutinasEstado}
        bitacora={rutinaBitacora}
        onRegistrar={registrarRutina}
        onClose={() => setActivePanel(null)}
      />
    ),
  }

  const turnoListo = !!turno && turno.tiene_conteo_apertura

  useEffect(() => {
    if (!turnoListo) return
    setLoading(true)
    api
      .get<Producto[]>('/pos/productos')
      .then(r => setProductos(r.data))
      .catch(() => setLoadError('No se pudieron cargar los productos'))
      .finally(() => setLoading(false))
  }, [turnoListo])

  const total = useMemo(
    () => cart.reduce((s, i) => s + (i.precio_venta * i.cantidad - (i.descuento || 0)), 0),
    [cart],
  )
  const cartCount = useMemo(() => cart.reduce((s, i) => s + i.cantidad, 0), [cart])

  // ── Carrito ────────────────────────────────────────────────────────────────

  const addToCart = (p: Producto) => {
    setCart(prev => {
      const existing = prev.find(i => i.producto_id === p.id)
      if (existing) {
        return prev.map(i =>
          i.producto_id === p.id ? { ...i, cantidad: i.cantidad + 1 } : i,
        )
      }
      return [
        ...prev,
        { producto_id: p.id, nombre: p.nombre, cantidad: 1, precio_venta: p.precio_venta },
      ]
    })
  }

  const incItem = (producto_id: number) =>
    setCart(prev =>
      prev.map(i => (i.producto_id === producto_id ? { ...i, cantidad: i.cantidad + 1 } : i)),
    )

  const decItem = (producto_id: number) =>
    setCart(prev =>
      prev
        .map(i => (i.producto_id === producto_id ? { ...i, cantidad: i.cantidad - 1 } : i))
        .filter(i => i.cantidad > 0),
    )

  const removeItem = (producto_id: number) =>
    setCart(prev => prev.filter(i => i.producto_id !== producto_id))

  // Descuento libre por producto (clamp al bruto de la línea)
  const setItemDescuento = (producto_id: number, valor: number) =>
    setCart(prev => prev.map(i => {
      if (i.producto_id !== producto_id) return i
      const max = i.precio_venta * i.cantidad
      return { ...i, descuento: Math.max(0, Math.min(valor, max)) }
    }))

  // ── Reimprimir último ticket ─────────────────────────────────────────────────

  const reimprimirUltimo = async () => {
    if (!turno) return
    setReprintMsg('')
    try {
      const r = await api.get<TicketApi[]>('/pos/tickets', { params: { turno_id: turno.id } })
      const ultimo = r.data[0] // backend ordena por fecha desc
      if (!ultimo) {
        setReprintMsg('No hay tickets en este turno todavía')
        return
      }
      const data = toTicketData(ultimo)
      setReprintTicket(data)
      // El componente monta el DOM oculto; esperamos un frame y disparamos print.
      requestAnimationFrame(() => requestAnimationFrame(() => window.print()))
    } catch {
      setReprintMsg('No se pudo obtener el último ticket')
    }
  }

  const abrirCobro = () => {
    setCartSheet(false)
    setShowCheckout(true)
  }

  // ── Guards (después de todos los hooks) ──────────────────────────────────────

  if (!turno)
    return (
      <GuardShell>
        <div className="bg-warm-100 border border-warm-200 rounded-2xl p-5 text-sm text-bark-700 text-center mt-8">
          No hay turno abierto.{' '}
          <button onClick={() => navigate('/gestion-turno')} className="font-bold text-clay-600 underline">
            Abrir caja →
          </button>
        </div>
      </GuardShell>
    )

  if (!turno.tiene_conteo_apertura)
    return (
      <GuardShell>
        <div className="bg-warm-100 border border-warm-200 rounded-2xl p-5 text-sm text-bark-700 text-center mt-8">
          Completá el conteo de apertura primero.
          <button
            onClick={() => navigate('/conteo-apertura')}
            className="block mx-auto mt-2 font-bold text-clay-600 underline"
          >
            Ir al conteo →
          </button>
        </div>
      </GuardShell>
    )

  // ── Layout principal ─────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-warm-50 flex flex-col">
      {/* ── Header ── */}
      <header className="bg-white border-b border-warm-200 px-4 pb-3 header-safe flex items-center gap-2 sticky top-0 z-20">
        <button
          onClick={() => navigate('/hub')}
          className="p-2 rounded-xl text-warm-400 hover:text-warm-700 hover:bg-warm-100 transition-colors -ml-1 flex-shrink-0"
        >
          <ArrowLeft size={18} />
        </button>

        {/* Panel de Turno — botón permanente */}
        <button
          onClick={() => setActivePanel(activePanel === 'turno' ? null : 'turno')}
          className="relative flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl text-xs font-bold transition-colors flex-shrink-0"
          style={{
            background: activePanel === 'turno' ? dark.greenTint : dark.surfaceAlt,
            color:      activePanel === 'turno' ? dark.green     : dark.inkMuted,
            border: `1px solid ${activePanel === 'turno' ? dark.greenDim : dark.border}`,
          }}
        >
          <LayoutGrid size={13} />
          <span className="hidden sm:inline">Panel</span>
          {alertCount > 0 && (
            <span
              className="absolute -top-1.5 -right-1.5 flex items-center justify-center rounded-full text-white font-bold"
              style={{ minWidth: 16, height: 16, fontSize: 9, padding: '0 3px', background: dark.danger }}
            >
              {alertCount}
            </span>
          )}
        </button>

        <span className="flex-1 text-sm font-bold text-warm-700 truncate">POS · Cobros</span>
        <button
          onClick={reimprimirUltimo}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold text-warm-600 border border-warm-200 hover:bg-warm-100 transition-colors flex-shrink-0"
        >
          <Printer size={14} />
          <span className="hidden sm:inline">Reimprimir</span>
        </button>
      </header>

      {/* ── Cuerpo: POS + panel inline (se reparten el ancho sin solaparse) ── */}
      <div className="flex-1 flex min-h-0 overflow-hidden">

        {/* Columna POS scrollable */}
        <div className="flex-1 overflow-y-auto min-w-0">
          <main className="w-full max-w-7xl mx-auto px-4 pt-4 pb-[120px] lg:pb-[120px] lg:grid lg:grid-cols-[1fr_380px] lg:gap-6 lg:items-start">
            {/* Panel izquierdo: grilla */}
            <div className="flex flex-col gap-3">
              {loadError && (
                <Toast tone="danger">{loadError}</Toast>
              )}
              {reprintMsg && (
                <Toast tone="warm" duration={3500} onDismiss={() => setReprintMsg('')}>
                  {reprintMsg}
                </Toast>
              )}
              {cancelToast && (
                <Toast tone="warm" duration={3000} onDismiss={() => setCancelToast(false)}>
                  Cobro cancelado — tu cuenta sigue acá, podés reintentar.
                </Toast>
              )}

              <ProductGrid
                productos={productos}
                cart={cart}
                onAdd={addToCart}
                search={search}
                onSearch={setSearch}
                catFiltro={catFiltro}
                onCatFiltro={setCatFiltro}
                soloFavoritos={soloFavoritos}
                onToggleFavoritos={() => setSoloFavoritos(v => !v)}
                loading={loading}
              />
            </div>

            {/* Panel derecho: cuenta */}
            <aside className="hidden lg:block lg:sticky lg:top-[88px]">
              <div className="bg-white rounded-2xl border border-warm-200 p-4 flex flex-col max-h-[calc(100vh-170px)]">
                <Cart
                  items={cart}
                  onInc={incItem}
                  onDec={decItem}
                  onRemove={removeItem}
                  onDescuento={setItemDescuento}
                  onClear={() => setCart([])}
                  onCobrar={abrirCobro}
                />
              </div>
            </aside>
          </main>
        </div>

        {/* Panel de herramienta: inline en sm+ (ocupa su propia columna),
            overlay fixed en mobile (cubre pantalla sin backdrop) */}
        {activePanel && PANELS[activePanel] && (
          <div
            className="fixed sm:relative sm:flex-shrink-0 inset-0 sm:inset-auto sm:w-[420px] z-40 sm:z-auto flex flex-col border-l"
            style={{
              background: dark.bg,
              borderColor: dark.border,
              boxShadow: '-4px 0 20px rgba(0,0,0,0.06)',
            }}
          >
            <div
              className="flex justify-end p-2 flex-shrink-0 border-b"
              style={{ borderColor: dark.border }}
            >
              <button
                onClick={() => setActivePanel(null)}
                className="w-8 h-8 flex items-center justify-center rounded-full"
                style={{
                  background: dark.surface,
                  border: `1px solid ${dark.border}`,
                  color: dark.ink,
                }}
                aria-label="Cerrar panel"
              >
                <X size={16} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto pb-[60px]">
              {PANELS[activePanel]}
            </div>
          </div>
        )}

      </div>

      {/* ── Mobile (<lg): barra de carrito sobre la bottom-nav ── */}
      {cart.length > 0 && (
        <button
          onClick={() => setCartSheet(true)}
          className="lg:hidden fixed left-3 right-3 bottom-[116px] z-30 bg-clay text-white rounded-2xl shadow-lg shadow-clay/30 px-4 py-3 flex items-center justify-between active:scale-[0.99] transition-all"
          style={{ marginBottom: 'env(safe-area-inset-bottom, 0px)' }}
        >
          <span className="flex items-center gap-2 font-bold text-sm">
            <ShoppingBag size={18} />
            {cartCount} {cartCount === 1 ? 'ítem' : 'ítems'}
            <ChevronUp size={16} className="opacity-80" />
          </span>
          <span className="font-bold tabular-nums">{fmtCO(total)} · Cobrar</span>
        </button>
      )}

      {/* ── Hoja inferior con la cuenta (mobile) ── */}
      <Sheet
        open={cartSheet}
        onClose={() => setCartSheet(false)}
        title={
          <span className="flex items-center gap-2">
            Tu cuenta
            <Pill tone="clay" className="tabular-nums">
              {cartCount} {cartCount === 1 ? 'ítem' : 'ítems'}
            </Pill>
          </span>
        }
      >
        <div className="max-h-[60vh] flex flex-col pb-2">
          <div className="flex justify-end pb-2">
            {cart.length > 0 && (
              <button
                onClick={() => setCart([])}
                className="text-xs font-bold text-danger-500 hover:text-danger-700 transition-colors"
              >
                Limpiar
              </button>
            )}
          </div>
          <Cart
            items={cart}
            onInc={incItem}
            onDec={decItem}
            onRemove={removeItem}
            onDescuento={setItemDescuento}
            onClear={() => setCart([])}
            onCobrar={abrirCobro}
            hideHeader
          />
        </div>
      </Sheet>


      {/* ── Modal de cobro ── */}
      {showCheckout && (
        <CheckoutModal
          items={cart}
          totalEstimado={total}
          onClose={() => {
            setShowCheckout(false)
            // Solo cancelación: onSuccess limpia el carrito y NO pasa por acá.
            setCancelToast(true)
          }}
          onSuccess={() => {
            setShowCheckout(false)
            setCart([])
          }}
        />
      )}

      {/* ── Ticket oculto para reimpresión (window.print) ── */}
      {reprintTicket && <TicketRecibo ticket={reprintTicket} />}

      {/* ── Banner operativo: estado de rutinas, abre PanelTurno ── */}
      <BannerOperativo
        estados={rutinasEstado}
        panelOpen={activePanel === 'turno'}
        onOpen={() => setActivePanel(activePanel === 'turno' ? null : 'turno')}
      />

      {/* ── Dock: herramientas de alta frecuencia, siempre visible ── */}
      <DockBar active={activePanel} onSelect={setActivePanel} />
    </div>
  )
}
