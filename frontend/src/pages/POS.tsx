import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Minus, Plus, Trash2, ShoppingBag, AlertTriangle } from 'lucide-react'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import BaristaLayout from '../components/BaristaLayout'
import CheckoutModal from '../components/CheckoutModal'

// ─── Tipos ───────────────────────────────────────────────────────────────────

interface Producto {
  id: number
  nombre: string
  categoria: string
  precio_venta: number
  controla_stock: boolean
  unidad_medida: string
}

interface CartItem {
  producto_id: number
  nombre: string
  cantidad: number
  precio_venta: number
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const fmtCO = (v: number) => `$${v.toLocaleString('es-CO')}`

const CAT_LABEL: Record<string, string> = {
  bebida: 'Bebidas',
  pasteleria: 'Pastelería',
  insumo: 'Insumos',
}

const CAT_COLOR: Record<string, { bg: string; text: string }> = {
  bebida:     { bg: 'oklch(95% 0.015 155)', text: 'oklch(30% 0.10 155)' },
  pasteleria: { bg: 'oklch(96% 0.015 60)',  text: 'oklch(40% 0.12 55)'  },
  insumo:     { bg: 'oklch(95% 0.015 245)', text: 'oklch(30% 0.12 245)' },
}

// ─── Componente ──────────────────────────────────────────────────────────────

export default function POS() {
  const { turno } = useTurno()
  const navigate = useNavigate()

  // Todos los hooks van antes de cualquier return condicional
  const [productos, setProductos] = useState<Producto[]>([])
  const [catFiltro, setCatFiltro] = useState<string>('todas')
  const [cart, setCart] = useState<CartItem[]>([])
  const [showCheckout, setShowCheckout] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [cancelToast, setCancelToast] = useState(false)

  const turnoListo = !!turno && turno.tiene_conteo_apertura

  useEffect(() => {
    if (!turnoListo) return
    api.get<Producto[]>('/pos/productos')
      .then(r => setProductos(r.data))
      .catch(() => setLoadError('No se pudieron cargar los productos'))
  }, [turnoListo])

  // Guards — después de todos los hooks
  if (!turno) return (
    <BaristaLayout title="POS">
      <div className="bg-amber-50 border border-amber-200 rounded-2xl p-5 text-sm text-amber-700 text-center mt-8">
        No hay turno abierto.{' '}
        <button onClick={() => navigate('/apertura')} className="font-bold underline">
          Abrir caja →
        </button>
      </div>
    </BaristaLayout>
  )

  if (!turno.tiene_conteo_apertura) return (
    <BaristaLayout title="POS">
      <div className="bg-amber-50 border border-amber-200 rounded-2xl p-5 text-sm text-amber-700 text-center mt-8">
        Completa el conteo de apertura primero.
        <button onClick={() => navigate('/conteo-apertura')} className="block mx-auto mt-2 font-bold underline">
          Ir al conteo →
        </button>
      </div>
    </BaristaLayout>
  )

  // Categorías dinámicas desde los datos
  const categorias = Array.from(new Set(productos.map(p => p.categoria))).sort()

  const productosFiltrados = catFiltro === 'todas'
    ? productos
    : productos.filter(p => p.categoria === catFiltro)

  // ── Carrito ────────────────────────────────────────────────────────────────

  const addToCart = (p: Producto) => {
    setCart(prev => {
      const existing = prev.find(i => i.producto_id === p.id)
      if (existing) {
        return prev.map(i => i.producto_id === p.id ? { ...i, cantidad: i.cantidad + 1 } : i)
      }
      return [...prev, { producto_id: p.id, nombre: p.nombre, cantidad: 1, precio_venta: p.precio_venta }]
    })
  }

  const updateCantidad = (producto_id: number, delta: number) => {
    setCart(prev =>
      prev
        .map(i => i.producto_id === producto_id ? { ...i, cantidad: i.cantidad + delta } : i)
        .filter(i => i.cantidad > 0)
    )
  }

  const removeFromCart = (producto_id: number) => {
    setCart(prev => prev.filter(i => i.producto_id !== producto_id))
  }

  const total = cart.reduce((s, i) => s + i.precio_venta * i.cantidad, 0)
  const cartCount = cart.reduce((s, i) => s + i.cantidad, 0)

  return (
    <BaristaLayout title="POS · Cobros" backTo="/hub">
      <div className="flex flex-col gap-4">

        {loadError && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl">
            <AlertTriangle size={14} className="shrink-0" /> {loadError}
          </div>
        )}

        {/* Toast de cancelación — aparece ~3s cuando se cierra el modal sin cobrar */}
        {cancelToast && (
          <div className="flex items-center gap-2 bg-amber-50 border border-amber-200 text-amber-800 text-sm px-4 py-3 rounded-xl">
            <AlertTriangle size={14} className="shrink-0 text-amber-500" />
            <span>Cobro cancelado — tu cuenta sigue acá, podés reintentar.</span>
          </div>
        )}

        {/* ── Filtros de categoría ─────────────────────────────────────────── */}
        <div className="flex gap-2 overflow-x-auto pb-1 -mx-1 px-1">
          <button
            onClick={() => setCatFiltro('todas')}
            className="px-3 py-1.5 rounded-xl text-xs font-semibold border-2 transition-all shrink-0"
            style={catFiltro === 'todas' ? {
              background: 'oklch(35% 0.05 155)', borderColor: 'oklch(35% 0.05 155)', color: '#fff',
            } : {
              background: '#fff', borderColor: 'oklch(88% 0.006 75)', color: 'oklch(40% 0.01 60)',
            }}
          >
            Todos
          </button>
          {categorias.map(cat => {
            const colors = CAT_COLOR[cat] ?? { bg: 'oklch(95% 0.005 60)', text: 'oklch(40% 0.005 60)' }
            const isActive = catFiltro === cat
            return (
              <button
                key={cat}
                onClick={() => setCatFiltro(cat)}
                className="px-3 py-1.5 rounded-xl text-xs font-semibold border-2 transition-all shrink-0"
                style={isActive ? {
                  background: colors.bg, borderColor: colors.text, color: colors.text,
                } : {
                  background: '#fff', borderColor: 'oklch(88% 0.006 75)', color: 'oklch(40% 0.01 60)',
                }}
              >
                {CAT_LABEL[cat] ?? cat}
              </button>
            )
          })}
        </div>

        {/* ── Grilla de productos ──────────────────────────────────────────── */}
        {productosFiltrados.length === 0 && !loadError && (
          <div className="text-center text-sm text-gray-400 py-10">
            {productos.length === 0 ? 'Cargando productos...' : 'Sin productos en esta categoría'}
          </div>
        )}

        <div className="grid grid-cols-2 gap-2.5">
          {productosFiltrados.map(p => {
            const inCart = cart.find(i => i.producto_id === p.id)
            const colors = CAT_COLOR[p.categoria] ?? { bg: 'oklch(95% 0.005 60)', text: 'oklch(40% 0.005 60)' }
            return (
              <button
                key={p.id}
                onClick={() => addToCart(p)}
                className="relative flex flex-col gap-1 p-3.5 bg-white rounded-2xl border-2 text-left active:scale-95 transition-all"
                style={inCart ? {
                  borderColor: 'oklch(48% 0.12 155)',
                  background: 'oklch(97% 0.015 155)',
                } : {
                  borderColor: 'oklch(88% 0.006 75)',
                }}
              >
                {inCart && (
                  <span
                    className="absolute top-2 right-2 w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold text-white"
                    style={{ background: 'oklch(48% 0.12 155)' }}
                  >
                    {inCart.cantidad}
                  </span>
                )}
                <span
                  className="text-[9px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-md self-start"
                  style={{ background: colors.bg, color: colors.text }}
                >
                  {CAT_LABEL[p.categoria] ?? p.categoria}
                </span>
                <p className="text-sm font-bold text-gray-800 leading-tight">{p.nombre}</p>
                <p className="text-base font-bold" style={{ color: 'oklch(35% 0.10 155)' }}>
                  {fmtCO(p.precio_venta)}
                </p>
              </button>
            )
          })}
        </div>

        {/* ── Carrito ──────────────────────────────────────────────────────── */}
        {cart.length > 0 && (
          <div className="bg-white rounded-2xl border border-gray-100 overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-50 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <ShoppingBag size={15} style={{ color: 'oklch(48% 0.12 155)' }} />
                <p className="text-xs font-bold uppercase tracking-wide text-gray-400">
                  Cuenta — {cartCount} {cartCount === 1 ? 'ítem' : 'ítems'}
                </p>
              </div>
              <button
                onClick={() => setCart([])}
                className="text-xs text-red-400 hover:text-red-600 font-semibold transition-colors"
              >
                Limpiar
              </button>
            </div>

            <div className="divide-y divide-gray-50">
              {cart.map(item => (
                <div key={item.producto_id} className="flex items-center gap-3 px-4 py-3">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-gray-800 truncate">{item.nombre}</p>
                    <p className="text-xs text-gray-400">
                      {fmtCO(item.precio_venta)} c/u · subtotal{' '}
                      <span className="font-bold text-gray-600">{fmtCO(item.precio_venta * item.cantidad)}</span>
                    </p>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      onClick={() => updateCantidad(item.producto_id, -1)}
                      className="w-7 h-7 rounded-lg border-2 border-gray-200 flex items-center justify-center text-gray-500 hover:border-gray-300 active:scale-90 transition-all"
                    >
                      <Minus size={12} />
                    </button>
                    <span className="w-6 text-center text-sm font-bold text-gray-800">{item.cantidad}</span>
                    <button
                      onClick={() => updateCantidad(item.producto_id, 1)}
                      className="w-7 h-7 rounded-lg border-2 flex items-center justify-center text-white active:scale-90 transition-all"
                      style={{ borderColor: 'oklch(48% 0.12 155)', background: 'oklch(48% 0.12 155)' }}
                    >
                      <Plus size={12} />
                    </button>
                    <button
                      onClick={() => removeFromCart(item.producto_id)}
                      className="w-7 h-7 rounded-lg flex items-center justify-center text-red-300 hover:text-red-500 hover:bg-red-50 transition-colors ml-1"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                </div>
              ))}
            </div>

            <div className="px-4 pt-3 pb-1 border-t border-gray-100 flex items-center justify-between">
              <span className="text-sm font-semibold text-gray-500">Total estimado</span>
              <span className="text-2xl font-bold" style={{ color: 'oklch(28% 0.01 60)' }}>{fmtCO(total)}</span>
            </div>
            <p className="px-4 pb-3 text-[10px] text-gray-400">
              * El total real lo confirma el servidor al cobrar
            </p>
          </div>
        )}

        {/* ── Botón cobrar (sticky sobre bottom nav) ───────────────────────── */}
        {cart.length > 0 && (
          <div className="sticky bottom-20 z-20">
            <button
              onClick={() => setShowCheckout(true)}
              className="w-full font-bold py-4 rounded-2xl text-base flex items-center justify-center gap-2 transition-all active:scale-[0.98] shadow-lg"
              style={{ background: 'linear-gradient(135deg, oklch(48% 0.12 155), oklch(40% 0.12 155))', color: '#fff' }}
            >
              <ShoppingBag size={18} />
              Cobrar {fmtCO(total)}
            </button>
          </div>
        )}
      </div>

      {/* ── Modal de cobro ───────────────────────────────────────────────────── */}
      {showCheckout && (
        <CheckoutModal
          items={cart}
          totalEstimado={total}
          onClose={() => {
            setShowCheckout(false)
            // Solo muestra el toast de cancelación si se cerró sin confirmar
            // (onSuccess limpia el carrito → este handler no se llama en caso de éxito)
            setCancelToast(true)
            setTimeout(() => setCancelToast(false), 3000)
          }}
          onSuccess={() => {
            setShowCheckout(false)
            setCart([])
            // No se toca cancelToast — el carrito se limpió, la venta fue exitosa
          }}
        />
      )}
    </BaristaLayout>
  )
}
