import { useState } from 'react'
import { Coins, ChevronDown, ChevronUp } from 'lucide-react'
import { dark } from '../constants/darkTheme'
import FilaDenom from './FilaDenom'

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`

const MONEDAS = [
  { valor: 50,    label: '$50'    },
  { valor: 100,   label: '$100'   },
  { valor: 200,   label: '$200'   },
  { valor: 500,   label: '$500'   },
  { valor: 1000,  label: '$1.000' },
]
const BILLETES = [
  { valor: 2000,   label: '$2.000'   },
  { valor: 5000,   label: '$5.000'   },
  { valor: 10000,  label: '$10.000'  },
  { valor: 20000,  label: '$20.000'  },
  { valor: 50000,  label: '$50.000'  },
  { valor: 100000, label: '$100.000' },
]

// Contador de efectivo por denominaciones (billetes + monedas). Llama onTotal con la suma.
export default function ContadorEfectivo({ onTotal }: { onTotal: (total: number) => void }) {
  const [cantidades, setCantidades] = useState<Record<number, number>>({})
  const [showMonedas, setShowMonedas] = useState(true)
  const [showBilletes, setShowBilletes] = useState(true)

  const setCantidad = (valor: number, isBillete: boolean, n: number) => {
    const key = isBillete ? valor + 1000000 : valor
    const nuevo = { ...cantidades, [key]: n }
    setCantidades(nuevo)
    onTotal(calcTotal(nuevo))
  }

  const getCantidad = (valor: number, isBillete: boolean) => {
    const key = isBillete ? valor + 1000000 : valor
    return cantidades[key] ?? 0
  }

  const calcTotal = (c: Record<number, number>) => {
    let t = 0
    MONEDAS.forEach(m => { t += m.valor * (c[m.valor] ?? 0) })
    BILLETES.forEach(b => { t += b.valor * (c[b.valor + 1000000] ?? 0) })
    return t
  }

  const total         = calcTotal(cantidades)
  const totalBilletes = BILLETES.reduce((s, b) => s + b.valor * (cantidades[b.valor + 1000000] ?? 0), 0)
  const totalMonedas  = MONEDAS.reduce((s, m) => s + m.valor * (cantidades[m.valor] ?? 0), 0)
  const hayAlgo       = total > 0

  return (
    <div className="rounded-2xl overflow-hidden" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
      <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: `1px solid ${dark.border}` }}>
        <div className="flex items-center gap-2">
          <Coins size={15} style={{ color: dark.amber }} />
          <span className="text-sm font-bold" style={{ color: dark.ink }}>Contador de efectivo</span>
        </div>
        {hayAlgo && (
          <button onClick={() => { setCantidades({}); onTotal(0) }}
            className="text-xs transition-colors" style={{ color: dark.inkSubtle }}
            onMouseEnter={e => (e.currentTarget.style.color = dark.danger)}
            onMouseLeave={e => (e.currentTarget.style.color = dark.inkSubtle)}>
            Limpiar
          </button>
        )}
      </div>

      {/* Billetes */}
      <button onClick={() => setShowBilletes(!showBilletes)}
        className="w-full flex items-center justify-between px-4 py-2.5 transition-colors" style={{ background: dark.surfaceAlt }}>
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold uppercase tracking-wide" style={{ color: dark.green }}>Billetes</span>
          {totalBilletes > 0 && (
            <span className="text-xs font-bold px-2 py-0.5 rounded-full font-mono" style={{ background: dark.greenTint, color: dark.green }}>
              {fmt(totalBilletes)}
            </span>
          )}
        </div>
        {showBilletes ? <ChevronUp size={14} style={{ color: dark.inkMuted }} /> : <ChevronDown size={14} style={{ color: dark.inkMuted }} />}
      </button>
      {showBilletes && (
        <div>
          {BILLETES.map(b => (
            <div key={b.valor} style={{ borderBottom: `1px solid ${dark.border}` }}>
              <FilaDenom valor={b.valor} label={b.label} isBillete={true}
                cantidad={getCantidad(b.valor, true)} onChange={n => setCantidad(b.valor, true, n)} />
            </div>
          ))}
        </div>
      )}

      {/* Monedas */}
      <button onClick={() => setShowMonedas(!showMonedas)}
        className="w-full flex items-center justify-between px-4 py-2.5 transition-colors"
        style={{ background: dark.surfaceAlt, borderTop: `1px solid ${dark.border}` }}>
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold uppercase tracking-wide" style={{ color: dark.amber }}>Monedas</span>
          {totalMonedas > 0 && (
            <span className="text-xs font-bold px-2 py-0.5 rounded-full font-mono" style={{ background: dark.amberTint, color: dark.amber }}>
              {fmt(totalMonedas)}
            </span>
          )}
        </div>
        {showMonedas ? <ChevronUp size={14} style={{ color: dark.inkMuted }} /> : <ChevronDown size={14} style={{ color: dark.inkMuted }} />}
      </button>
      {showMonedas && (
        <div>
          {MONEDAS.map(m => (
            <div key={m.valor} style={{ borderBottom: `1px solid ${dark.border}` }}>
              <FilaDenom valor={m.valor} label={m.label} isBillete={false}
                cantidad={getCantidad(m.valor, false)} onChange={n => setCantidad(m.valor, false, n)} />
            </div>
          ))}
        </div>
      )}

      {/* Total */}
      <div className="px-4 py-4" style={{
        borderTop: `2px solid ${hayAlgo ? dark.amberDim : dark.border}`,
        background: hayAlgo ? dark.amberTint : dark.surface,
      }}>
        <div className="flex items-center justify-between">
          <span className="text-sm font-semibold" style={{ color: dark.inkMuted }}>Total contado</span>
          <span className="text-2xl font-bold font-mono"
            style={{ color: hayAlgo ? dark.amber : dark.inkSubtle, fontFamily: '"JetBrains Mono", monospace' }}>
            {hayAlgo ? fmt(total) : '$0'}
          </span>
        </div>
        {hayAlgo && (
          <p className="text-xs mt-1 text-right font-mono" style={{ color: dark.amberDim }}>
            {fmt(totalBilletes)} billetes · {fmt(totalMonedas)} monedas
          </p>
        )}
      </div>
    </div>
  )
}
