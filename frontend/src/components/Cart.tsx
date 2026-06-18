import { ShoppingBag, Trash2 } from 'lucide-react'
import { Stepper, SectionLabel } from './ui'

// ─── Tipos ───────────────────────────────────────────────────────────────────

export interface CartItem {
  producto_id: number
  nombre: string
  cantidad: number
  precio_venta: number
}

interface Props {
  items: CartItem[]
  onInc: (producto_id: number) => void
  onDec: (producto_id: number) => void
  onRemove: (producto_id: number) => void
  onClear: () => void
  onCobrar: () => void
  /** Oculta el header "Cuenta · N ítems" cuando el contenedor ya lo muestra (hoja mobile). */
  hideHeader?: boolean
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const fmtCO = (v: number) => `$${v.toLocaleString('es-CO')}`

// ─── Componente ──────────────────────────────────────────────────────────────

/**
 * Panel de cuenta del POS: líneas con stepper, total grande y botón Cobrar.
 * Presentacional — la lógica del carrito vive en POS.tsx. Se usa tanto en el
 * panel sticky de PC como dentro de la hoja inferior en mobile.
 */
export default function Cart({
  items,
  onInc,
  onDec,
  onRemove,
  onClear,
  onCobrar,
  hideHeader = false,
}: Props) {
  const total = items.reduce((s, i) => s + i.precio_venta * i.cantidad, 0)
  const count = items.reduce((s, i) => s + i.cantidad, 0)
  const vacio = items.length === 0

  return (
    <div className="flex flex-col h-full">
      {/* ── Header ── */}
      {!hideHeader && (
        <div className="flex items-center justify-between px-1 pb-3 shrink-0">
          <div className="flex items-center gap-2">
            <ShoppingBag size={16} className="text-forest" />
            <SectionLabel className="text-warm-500">
              Cuenta — {count} {count === 1 ? 'ítem' : 'ítems'}
            </SectionLabel>
          </div>
          {!vacio && (
            <button
              onClick={onClear}
              className="text-xs font-bold text-danger-500 hover:text-danger-700 transition-colors"
            >
              Limpiar
            </button>
          )}
        </div>
      )}

      {/* ── Líneas ── */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {vacio ? (
          <div className="flex flex-col items-center justify-center text-center gap-2 py-10 text-warm-400">
            <ShoppingBag size={28} className="text-warm-300" />
            <p className="text-sm font-semibold">Tu cuenta está vacía</p>
            <p className="text-xs">Tocá un producto para agregarlo</p>
          </div>
        ) : (
          <div className="divide-y divide-warm-100">
            {items.map(item => (
              <div key={item.producto_id} className="flex items-center gap-3 py-3">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-bold text-bark-800 truncate">{item.nombre}</p>
                  <p className="text-xs text-warm-400 tabular-nums">
                    {fmtCO(item.precio_venta)} c/u ·{' '}
                    <span className="font-bold text-warm-600">
                      {fmtCO(item.precio_venta * item.cantidad)}
                    </span>
                  </p>
                </div>
                <Stepper
                  value={item.cantidad}
                  min={1}
                  onDec={() => onDec(item.producto_id)}
                  onInc={() => onInc(item.producto_id)}
                />
                <button
                  onClick={() => onRemove(item.producto_id)}
                  aria-label="Quitar"
                  className="w-7 h-7 shrink-0 rounded-lg flex items-center justify-center text-danger-400 hover:text-danger-600 hover:bg-danger-50 transition-colors"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Total + Cobrar ── */}
      {!vacio && (
        <div className="shrink-0 pt-3 mt-1 border-t border-warm-200">
          <div className="flex items-end justify-between mb-1">
            <span className="text-sm font-bold text-warm-500">Total estimado</span>
            <span className="text-3xl font-bold text-bark-800 tabular-nums">{fmtCO(total)}</span>
          </div>
          <p className="text-[10px] text-warm-400 mb-3">
            * El total real lo confirma el servidor al cobrar
          </p>
          <button
            onClick={onCobrar}
            className="w-full bg-clay hover:bg-clay-600 text-white font-bold py-4 rounded-2xl text-base flex items-center justify-center gap-2 transition-all active:scale-[0.98] shadow-lg shadow-clay/20"
          >
            <ShoppingBag size={18} />
            Cobrar {fmtCO(total)}
          </button>
        </div>
      )}
    </div>
  )
}
