/**
 * Numpad — teclado numérico en pantalla para montos en efectivo.
 *
 * Diseño:
 * - Botones grandes (touch-friendly) para dígitos 0-9 y borrar (⌫).
 * - Fila de atajos de billetes colombianos filtrada para mostrar solo los
 *   que sean >= totalEstimado (misma lógica que los montos rápidos del F0).
 * - La fila "Exacto" + billetes siempre visible encima del grid numérico.
 * - `onValue` recibe el string numérico acumulado (sin formato).
 * - `onQuick` dispara una selección directa de un monto específico.
 */

interface NumpadProps {
  /** Valor actual como string (controlado externamente). */
  value: string
  /** Llamado con el nuevo string al pulsar un dígito o borrar. */
  onValue: (v: string) => void
  /** Llamado al seleccionar un monto rápido (billete o Exacto). */
  onQuick: (amount: number) => void
  /** Total de la venta — filtra los atajos de billetes. */
  totalEstimado: number
}

const BILLETES = [1_000, 2_000, 5_000, 10_000, 20_000, 50_000, 100_000]

/** Formatea abreviando: 1000→$1k, 50000→$50k, 100000→$100k */
function fmtBillete(n: number): string {
  if (n >= 1_000_000) return `$${n / 1_000_000}M`
  if (n >= 1_000) return `$${n / 1_000}k`
  return `$${n}`
}

export default function Numpad({ value, onValue, onQuick, totalEstimado }: NumpadProps) {
  const press = (d: string) => {
    // Evita ceros iniciales múltiples
    if (value === '0' && d !== '.') { onValue(d); return }
    const next = value + d
    // Límite razonable: 10 dígitos (~$9.999.999.999)
    if (next.replace('.', '').length > 10) return
    onValue(next)
  }

  const backspace = () => {
    if (value.length <= 1) { onValue(''); return }
    onValue(value.slice(0, -1))
  }

  // Atajos: Exacto siempre + billetes >= total (hasta 4 opciones)
  const billetes = BILLETES.filter(b => b >= totalEstimado).slice(0, 4)

  const btnBase =
    'flex items-center justify-center rounded-2xl font-bold select-none transition-all active:scale-95 active:brightness-95'
  const digitBtn =
    `${btnBase} bg-warm-50 border border-warm-200 text-bark-800 text-xl h-14`
  const zeroBtn =
    `${btnBase} bg-warm-50 border border-warm-200 text-bark-800 text-xl h-14 col-span-2`
  const delBtn =
    `${btnBase} bg-warm-100 border border-warm-200 text-warm-600 text-base h-14`
  const quickBtn =
    `${btnBase} bg-clay-50 border border-clay-200 text-clay-600 text-xs h-10 px-1`
  const exactoBtn =
    `${btnBase} bg-clay-100 border border-clay-400 text-clay-700 text-xs font-extrabold h-10 px-2`

  return (
    <div className="space-y-2.5">
      {/* Atajos de billetes */}
      <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${1 + billetes.length}, 1fr)` }}>
        <button className={exactoBtn} onClick={() => onQuick(totalEstimado)}>
          Exacto
        </button>
        {billetes.map(b => (
          <button key={b} className={quickBtn} onClick={() => onQuick(b)}>
            {fmtBillete(b)}
          </button>
        ))}
      </div>

      {/* Grid numérico 3×4 */}
      <div className="grid grid-cols-3 gap-2">
        {(['7','8','9','4','5','6','1','2','3'] as const).map(d => (
          <button key={d} className={digitBtn} onClick={() => press(d)}>
            {d}
          </button>
        ))}
        {/* Última fila: 0 (ancho 2) + ⌫ */}
        <button className={zeroBtn} onClick={() => press('0')}>0</button>
        <button className={delBtn} onClick={backspace}>⌫</button>
      </div>
    </div>
  )
}
