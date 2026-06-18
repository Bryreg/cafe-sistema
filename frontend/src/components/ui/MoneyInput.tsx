interface MoneyInputProps {
  /** Label en mayúsculas encima del input. Opcional: sin label, solo el campo. */
  label?: string
  /** Valor controlado (string para permitir vacío / edición libre). */
  value: string
  onChange: (v: string) => void
  placeholder?: string
  /** Texto de ayuda debajo del label. */
  hint?: string
  /** Tamaño del campo: `lg` (3xl, para totales) o `sm` (xl, para subcampos). */
  size?: 'sm' | 'lg'
  /** Auto-focus al montar (útil en bottom-sheets de cobro). */
  autoFocus?: boolean
  /** Ref al input subyacente. */
  inputRef?: React.Ref<HTMLInputElement>
  className?: string
}

/**
 * Input numérico con prefijo `$` para montos en pesos (formato es-CO).
 * Usa tokens del sistema (warm/clay) — sin oklch() inline.
 *
 * NOTA DE COLISIÓN: existe un `components/MoneyInput.tsx` legacy con una API
 * distinta (`{ label, dark, size }` con `dark` booleano para tema oscuro).
 * Este nuevo vive en `components/ui/MoneyInput.tsx` y NO rompe los imports
 * existentes (que apuntan a `../components/MoneyInput`). Para componentes
 * nuevos importá este desde el barrel `components/ui`. El legacy se migra
 * en una fase posterior. Este NO soporta modo oscuro (el rediseño POS es claro).
 */
export default function MoneyInput({
  label,
  value,
  onChange,
  placeholder = '0',
  hint,
  size = 'lg',
  autoFocus = false,
  inputRef,
  className = '',
}: MoneyInputProps) {
  const textSize = size === 'lg' ? 'text-3xl' : 'text-xl'
  const py = size === 'lg' ? 'py-4' : 'py-3'

  return (
    <div className={className}>
      {label && (
        <label className="text-[11px] font-bold uppercase tracking-wide text-warm-500 block mb-1.5">
          {label}
        </label>
      )}
      {hint && <p className="text-xs text-warm-500 mb-2">{hint}</p>}
      <div className="relative">
        <span className="absolute left-4 top-1/2 -translate-y-1/2 text-xl font-bold text-warm-300">$</span>
        <input
          ref={inputRef}
          type="number"
          inputMode="numeric"
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder}
          autoFocus={autoFocus}
          className={`w-full pl-10 pr-4 ${py} ${textSize} font-bold font-mono tabular-nums text-bark-800 bg-white border-2 border-warm-200 rounded-xl outline-none transition-colors focus:border-clay-400 placeholder:text-warm-300`}
        />
      </div>
    </div>
  )
}
