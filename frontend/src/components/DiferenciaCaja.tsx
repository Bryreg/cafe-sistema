import { dark } from '../constants/darkTheme'

const fmt = (v: number) => `$${Math.round(v).toLocaleString('es-CO')}`

interface Props {
  /** Efectivo contado por la barista (total del contador). */
  contado: number
  /** Efectivo que debería haber en caja (esperado). */
  esperado: number
}

/**
 * Veredicto en vivo del cuadre: compara lo que la barista contó contra lo que
 * debería haber, y le dice claramente si cuadra, o cuánto falta / sobra.
 * No aparece hasta que empieza a contar (contado > 0).
 */
export default function DiferenciaCaja({ contado, esperado }: Props) {
  if (contado <= 0) return null

  const diff = Math.round(contado - esperado)
  const ok = diff === 0
  const sobra = diff > 0

  const color = ok ? dark.green : sobra ? dark.amber : dark.danger
  const tint = ok ? dark.greenTint : sobra ? dark.amberTint : dark.dangerTint
  const dim = ok ? dark.greenDim : sobra ? dark.amberDim : dark.dangerDim

  const titulo = ok ? '✓ Cuadra exacto' : sobra ? 'Sobra efectivo' : 'Falta efectivo'
  const detalle = ok
    ? 'Contaste exactamente lo que debería haber en caja.'
    : sobra
      ? 'Contaste más de lo esperado.'
      : 'Contaste menos de lo esperado.'

  return (
    <div className="rounded-2xl p-4" style={{ background: tint, border: `1px solid ${dim}` }}>
      <div className="flex items-center justify-between">
        <span className="text-[13px]" style={{ color: dark.inkMuted }}>Contaste</span>
        <span className="text-[14px] font-semibold font-mono tabular-nums" style={{ color: dark.ink }}>{fmt(contado)}</span>
      </div>
      <div className="flex items-center justify-between mt-1.5">
        <span className="text-[13px]" style={{ color: dark.inkMuted }}>Debería haber</span>
        <span className="text-[14px] font-semibold font-mono tabular-nums" style={{ color: dark.ink }}>{fmt(esperado)}</span>
      </div>
      <div className="flex items-center justify-between pt-3 mt-2.5" style={{ borderTop: `1px solid ${dim}` }}>
        <div className="min-w-0">
          <p className="text-[15px] font-bold" style={{ color }}>{titulo}</p>
          <p className="text-[11px] mt-0.5" style={{ color: dark.inkSubtle }}>{detalle}</p>
        </div>
        {!ok && (
          <span className="text-[20px] font-bold font-mono tabular-nums shrink-0 ml-3" style={{ color }}>
            {sobra ? '+' : '−'}{fmt(Math.abs(diff))}
          </span>
        )}
      </div>
    </div>
  )
}
