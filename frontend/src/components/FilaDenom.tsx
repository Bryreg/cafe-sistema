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
  // Acento fuerte: sirve como borde de foco y como fondo del botón "+" con
  // texto claro (dark.bg) encima. En modo día el acento debe ser saturado.
  const accent = accentColor === 'green' ? dark.green : dark.amber

  return (
    <div className="flex items-center gap-3 px-4 py-2.5 transition-colors" style={{
      background: cantidad > 0
        ? (isBillete ? 'oklch(94% 0.04 155 / 0.6)' : 'oklch(95% 0.045 70 / 0.6)')
        : 'transparent',
    }}>
      <div className="w-16 shrink-0 text-center py-1 rounded-lg text-[11px] font-bold" style={{
        background: isBillete ? dark.greenTint : dark.amberTint,
        color: isBillete ? dark.green : dark.amber,
      }}>
        {label}
      </div>
      <div className="flex items-center gap-2 flex-1 justify-center">
        <button
          onClick={() => onChange(Math.max(0, cantidad - 1))}
          disabled={cantidad === 0}
          className="w-9 h-9 rounded-xl flex items-center justify-center transition-colors"
          style={{ background: dark.surfaceAlt, color: dark.inkMuted, opacity: cantidad === 0 ? 0.3 : 1 }}
        >
          <Minus size={13} />
        </button>
        <input
          type="number"
          value={cantidad === 0 ? '' : cantidad}
          onChange={e => onChange(Math.max(0, parseInt(e.target.value) || 0))}
          placeholder="0"
          inputMode="numeric"
          className="w-14 text-center rounded-xl py-1.5 text-base font-bold outline-none"
          style={{
            background: dark.surface,
            border: `2px solid ${dark.border}`,
            color: dark.ink,
            fontFamily: '"JetBrains Mono", monospace',
          }}
          onFocus={e => (e.target.style.borderColor = accent)}
          onBlur={e => (e.target.style.borderColor = dark.border)}
        />
        <button
          onClick={() => onChange(cantidad + 1)}
          className="w-9 h-9 rounded-xl flex items-center justify-center transition-colors"
          style={{ background: accent, color: dark.bg }}
        >
          <Plus size={13} />
        </button>
      </div>
      <div className="w-20 text-right shrink-0" style={{ fontFamily: '"JetBrains Mono", monospace' }}>
        {subtotal > 0
          ? <span className="text-sm font-bold" style={{ color: accentColor === 'green' ? dark.ink : dark.amber }}>{`$${subtotal.toLocaleString('es-CO')}`}</span>
          : <span className="text-xs" style={{ color: dark.inkSubtle }}>—</span>
        }
      </div>
    </div>
  )
}
