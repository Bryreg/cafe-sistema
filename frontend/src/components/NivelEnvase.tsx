import { useId, useRef } from 'react'

/**
 * Conteo de un producto a granel: unidades SELLADAS (enteras) + el NIVEL de la unidad
 * ABIERTA, que se marca arrastrando una línea sobre un dibujo de bolsa/botella.
 * Total = selladas + nivel (ej: 3 selladas + ½ abierta = 3,5). Controlado por el padre.
 *
 * readOnly: solo muestra el nivel (para el admin: ver de un vistazo cuánto queda).
 */
interface Props {
  envase: 'bolsa' | 'botella'
  unidad?: string
  selladas?: number
  nivel: number              // 0..1
  onChange?: (selladas: number, nivel: number) => void
  readOnly?: boolean
}

const GEO = {
  bolsa:   { top: 46, fill: '#9FE1CB', line: '#0F6E56' },
  botella: { top: 60, fill: '#F4C0D1', line: '#993556' },
}
const BOT = 180

function nivelLabel(f: number): string {
  const q = Math.round(f * 4) / 4
  if (Math.abs(f - q) < 0.06) {
    return ({ 0: 'Vacía', 0.25: '¼', 0.5: '½', 0.75: '¾', 1: 'Llena' } as Record<number, string>)[q]
  }
  return Math.round(f * 100) + '%'
}

function Envase({ envase, y }: { envase: 'bolsa' | 'botella'; y: number }) {
  const clipId = useId().replace(/:/g, '')
  return (
    <>
      <defs><clipPath id={clipId}>
        {envase === 'bolsa'
          ? <rect x="26" y="46" width="68" height="134" rx="10" />
          : <rect x="34" y="60" width="52" height="120" rx="8" />}
      </clipPath></defs>
      {envase === 'bolsa' ? (
        <>
          <path d="M40 46 L44 30 L76 30 L80 46 Z" fill="#f4f1ea" stroke="#b9b6ac" strokeWidth="1.5" />
          <rect x="26" y="46" width="68" height="134" rx="10" fill="#f4f1ea" stroke="#b9b6ac" strokeWidth="1.5" />
        </>
      ) : (
        <>
          <rect x="52" y="22" width="16" height="18" fill="#f4f1ea" stroke="#b9b6ac" strokeWidth="1.5" />
          <path d="M46 60 Q46 42 52 40 L68 40 Q74 42 74 60 Z" fill="#f4f1ea" stroke="#b9b6ac" strokeWidth="1.5" />
          <rect x="34" y="60" width="52" height="120" rx="8" fill="#f4f1ea" stroke="#b9b6ac" strokeWidth="1.5" />
        </>
      )}
      <rect x={envase === 'bolsa' ? 26 : 34} y={y} width={envase === 'bolsa' ? 68 : 52} height={BOT - y}
        clipPath={`url(#${clipId})`} fill={GEO[envase].fill} />
    </>
  )
}

export default function NivelEnvase({ envase, unidad, selladas = 0, nivel, onChange, readOnly }: Props) {
  const svgRef = useRef<SVGSVGElement>(null)
  const drag = useRef(false)
  const g = GEO[envase]
  const top = g.top
  const y = BOT - Math.min(1, Math.max(0, nivel)) * (BOT - top)

  if (readOnly) {
    return (
      <svg viewBox="0 0 120 200" width="34" height="56" role="img" aria-label={`Nivel ${nivelLabel(nivel)}`}>
        <Envase envase={envase} y={y} />
      </svg>
    )
  }

  const uWord = unidad ?? envase
  const setFromEvent = (e: React.PointerEvent) => {
    const svg = svgRef.current
    if (!svg || !onChange) return
    const r = svg.getBoundingClientRect()
    const yv = ((e.clientY - r.top) / r.height) * 200
    let f = Math.min(1, Math.max(0, (BOT - yv) / (BOT - top)))
    f = Math.round(f * 20) / 20
    onChange(selladas, f)
  }
  const total = selladas + nivel
  const totalTxt = total.toFixed(2).replace(/\.?0+$/, '').replace('.', ',')

  return (
    <div className="flex items-center gap-3">
      <svg
        ref={svgRef}
        viewBox="0 0 120 200" width="76" height="126"
        style={{ touchAction: 'none', cursor: 'ns-resize', flexShrink: 0 }}
        role="img" aria-label={`Nivel de la ${envase} abierta`}
        onPointerDown={e => { drag.current = true; svgRef.current?.setPointerCapture(e.pointerId); setFromEvent(e) }}
        onPointerMove={e => { if (drag.current) setFromEvent(e) }}
        onPointerUp={() => { drag.current = false }}
      >
        <Envase envase={envase} y={y} />
        <line x1={envase === 'bolsa' ? 20 : 28} y1={y} x2={envase === 'bolsa' ? 100 : 92} y2={y}
          stroke={g.line} strokeWidth="2.5" strokeDasharray="4 3" />
        <circle cx={envase === 'bolsa' ? 94 : 86} cy={y} r="5" fill={g.line} />
      </svg>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1.5">
          <span className="text-[11px] text-gray-400">Selladas</span>
          <button type="button" onClick={() => onChange && selladas > 0 && onChange(selladas - 1, nivel)}
            className="w-7 h-7 rounded-lg border border-gray-200 text-gray-500 leading-none">−</button>
          <span className="text-base font-bold w-5 text-center tabular-nums">{selladas}</span>
          <button type="button" onClick={() => onChange && onChange(selladas + 1, nivel)}
            className="w-7 h-7 rounded-lg border border-gray-200 text-gray-500 leading-none">+</button>
        </div>
        <p className="text-[11px] text-gray-400">Abierta: <span className="font-semibold" style={{ color: g.line }}>{nivelLabel(nivel)}</span></p>
        <p className="text-[15px] font-bold mt-0.5 tabular-nums">{totalTxt} <span className="text-xs font-normal text-gray-500">{uWord}{total === 1 ? '' : 's'}</span></p>
      </div>
    </div>
  )
}
