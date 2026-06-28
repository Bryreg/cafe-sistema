import { Plus, Minus } from 'lucide-react'
import { dark } from '../constants/darkTheme'

interface Props {
  valor: number
  label: string
  isBillete: boolean
  cantidad: number
  onChange: (n: number) => void
  /**
   * Accent color for the "+" increment button and the subtotal text.
   * - "amber": used in Apertura (opening flow accent)
   * - "green": used in Cierre (closing/confirmation flow accent)
   */
  accentColor?: 'amber' | 'green'
}

export default function FilaDenom({
  valor, label, isBillete, cantidad, onChange, accentColor = 'amber',
}: Props) {
  const subtotal = valor * cantidad
  const accent = accentColor === 'green' ? dark.green : dark.amber

  return (
    <div className="flex items-center gap-2 px-3 py-2 transition-colors" style={{
      background: cantidad > 0
        ? (isBillete ? 'oklch(94% 0.04 155 / 0.6)' : 'oklch(95% 0.045 70 / 0.6)')
        : 'transparent',
    }}>
      {/* Zona 1: label fijo */}
      <div className="w-16 shrink-0 text-center py-1 rounded-lg text-[11px] font-bold" style={{
        background: isBillete ? dark.greenTint : dark.amberTint,
        color: isBillete ? dark.green : dark.amber,
      }}>
        {label}
      </div>

      {/* Zona 2: control compacto [−|input|+] como un único grupo */}
      <div className="inline-flex shrink-0 rounded-lg overflow-hidden" style={{ border: `1.5px solid ${dark.border}` }}>
        <button
          onClick={() => onChange(Math.max(0, cantidad - 1))}
          disabled={cantidad === 0}
          className="w-8 h-8 flex items-center justify-center transition-colors"
          style={{
            background: dark.surfaceAlt,
            color: dark.inkMuted,
            opacity: cantidad === 0 ? 0.3 : 1,
            borderRight: `1px solid ${dark.border}`,
          }}
        >
          <Minus size={13} />
        </button>
        <input
          type="number"
          value={cantidad === 0 ? '' : cantidad}
          onChange={e => onChange(Math.max(0, parseInt(e.target.value) || 0))}
          placeholder="0"
          inputMode="numeric"
          className="w-12 h-8 text-center text-base font-bold outline-none"
          style={{
            background: dark.surface,
            border: 'none',
            color: dark.ink,
            fontFamily: '"JetBrains Mono", monospace',
          }}
          onFocus={e => {
            const parent = e.target.parentElement
            if (parent) parent.style.borderColor = accent
          }}
          onBlur={e => {
            const parent = e.target.parentElement
            if (parent) parent.style.borderColor = dark.border
          }}
        />
        <button
          onClick={() => onChange(cantidad + 1)}
          className="w-8 h-8 flex items-center justify-center transition-colors"
          style={{
            background: accent,
            color: dark.bg,
            borderLeft: `1px solid ${dark.border}`,
          }}
        >
          <Plus size={13} />
        </button>
      </div>

      {/* Zona 3: subtotal empujado a la derecha */}
      <div className="ml-auto w-24 text-right shrink-0" style={{ fontFamily: '"JetBrains Mono", monospace' }}>
        <span
          className="text-sm font-bold"
          style={{
            color: subtotal > 0
              ? (accentColor === 'green' ? dark.ink : dark.amber)
              : dark.inkSubtle,
          }}
        >
          {`$${subtotal.toLocaleString('es-CO')}`}
        </span>
      </div>
    </div>
  )
}
