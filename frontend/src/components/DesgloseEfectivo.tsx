import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { dark } from '../constants/darkTheme'

// ─── Tipos ───────────────────────────────────────────────────────────────────

export interface MovimientoDesglose {
  tipo: string // 'ingreso' | 'egreso'
  concepto: string
  valor: number
  fecha?: string | null
}

interface Props {
  /** Efectivo con el que empezó el turno (base contada al abrir). */
  base: number
  /** Ventas en efectivo del POS hasta este momento. */
  ventasEfectivo: number
  /** Otros ingresos de efectivo a la caja (movimientos tipo ingreso). */
  ingresos: number
  /** Salidas de efectivo de la caja (movimientos tipo egreso). */
  egresos: number
  /** Resultado: lo que debería haber en caja. Autoritativo (viene del backend). */
  esperado: number
  /** Reserva de caja fuerte, guardada aparte. Se muestra como nota, NO entra en el cálculo. */
  cajaFuerte?: number
  /** Movimientos de caja para itemizar salidas/ingresos. Opcional. */
  movimientos?: MovimientoDesglose[]
  /** Venta de ayer separada y guardada: la base no se cuenta; el esperado que llega
   *  ya viene SIN la base (solo registradora). */
  baseSeparada?: boolean
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const fmt = (v: number) => `$${Math.round(v).toLocaleString('es-CO')}`
const fmtHora = (s?: string | null) => {
  if (!s) return ''
  const t = s.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1').replace('+00:00', 'Z')
  const d = new Date(t.endsWith('Z') ? t : t + 'Z')
  return d.toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })
}

// ─── Componente ──────────────────────────────────────────────────────────────

/**
 * Desglose del efectivo esperado, en forma de ecuación clara para que la barista
 * ENTIENDA y confíe en el número contra el que cuadra:
 *   base + ventas en efectivo + otros ingresos − salidas = debería haber en caja.
 * Las salidas se pueden desplegar itemizadas (concepto + hora + valor).
 */
export default function DesgloseEfectivo({
  base,
  ventasEfectivo,
  ingresos,
  egresos,
  esperado,
  cajaFuerte = 0,
  movimientos = [],
  baseSeparada = false,
}: Props) {
  const [openSalidas, setOpenSalidas] = useState(false)
  const salidas = movimientos.filter(m => m.tipo === 'egreso')
  const haySalidas = egresos > 0 || salidas.length > 0

  return (
    <div className="rounded-2xl p-4" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
      <p className="text-[10px] font-bold uppercase tracking-widest mb-3" style={{ color: dark.inkSubtle }}>
        Cómo se calcula lo que debería haber en caja
      </p>

      <div className="space-y-2.5">
        {/* Base inicial — si la venta de ayer está separada, no entra al conteo */}
        {baseSeparada ? (
          <div className="flex items-center justify-between rounded-lg px-2 py-1.5" style={{ background: dark.amberTint }}>
            <span className="text-[13px]" style={{ color: dark.amber }}>
              Venta de ayer separada y guardada (no se cuenta)
            </span>
            <span className="text-[14px] font-semibold font-mono tabular-nums" style={{ color: dark.amber, textDecoration: 'line-through' }}>{fmt(base)}</span>
          </div>
        ) : (
          <div className="flex items-center justify-between">
            <span className="text-[13px]" style={{ color: dark.inkMuted }}>Con lo que empezaste (base)</span>
            <span className="text-[14px] font-semibold font-mono tabular-nums" style={{ color: dark.ink }}>{fmt(base)}</span>
          </div>
        )}

        {/* Ventas en efectivo */}
        <div className="flex items-center justify-between">
          <span className="text-[13px]" style={{ color: dark.inkMuted }}>
            <span style={{ color: dark.green }}>+</span> Ventas en efectivo
          </span>
          <span className="text-[14px] font-semibold font-mono tabular-nums" style={{ color: dark.green }}>{fmt(ventasEfectivo)}</span>
        </div>

        {/* Otros ingresos (solo si hay) */}
        {ingresos > 0 && (
          <div className="flex items-center justify-between">
            <span className="text-[13px]" style={{ color: dark.inkMuted }}>
              <span style={{ color: dark.green }}>+</span> Otros ingresos
            </span>
            <span className="text-[14px] font-semibold font-mono tabular-nums" style={{ color: dark.green }}>{fmt(ingresos)}</span>
          </div>
        )}

        {/* Salidas de efectivo (desplegable) */}
        {haySalidas && (
          <div>
            <button
              type="button"
              onClick={() => setOpenSalidas(o => !o)}
              className="w-full flex items-center justify-between"
              disabled={salidas.length === 0}
            >
              <span className="text-[13px] flex items-center gap-1" style={{ color: dark.inkMuted }}>
                <span style={{ color: dark.danger }}>−</span> Salidas de efectivo
                {salidas.length > 0 && (
                  openSalidas
                    ? <ChevronUp size={13} style={{ color: dark.inkSubtle }} />
                    : <ChevronDown size={13} style={{ color: dark.inkSubtle }} />
                )}
              </span>
              <span className="text-[14px] font-semibold font-mono tabular-nums" style={{ color: dark.danger }}>−{fmt(egresos)}</span>
            </button>

            {openSalidas && salidas.length > 0 && (
              <div className="mt-2 ml-3 pl-3 space-y-1.5" style={{ borderLeft: `1px solid ${dark.border}` }}>
                {salidas.map((m, i) => (
                  <div key={i} className="flex items-center justify-between gap-2">
                    <span className="text-[12px] truncate" style={{ color: dark.inkSubtle }}>
                      {m.concepto}
                      {m.fecha && <span className="ml-1.5" style={{ color: dark.inkSubtle, opacity: 0.7 }}>{fmtHora(m.fecha)}</span>}
                    </span>
                    <span className="text-[12px] font-mono tabular-nums shrink-0" style={{ color: dark.danger }}>−{fmt(m.valor)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Resultado */}
        <div className="flex items-center justify-between pt-2.5 mt-1" style={{ borderTop: `1px solid ${dark.border}` }}>
          <span className="text-[13px] font-bold" style={{ color: dark.ink }}>
            {baseSeparada ? '= A contar en la registradora' : '= Debería haber en caja'}
          </span>
          <span className="text-[19px] font-bold font-mono tabular-nums" style={{ color: dark.ink }}>{fmt(esperado)}</span>
        </div>
      </div>

      {/* Caja fuerte — aparte, no cuenta en el cuadre de la registradora */}
      {cajaFuerte > 0 && (
        <div className="flex items-center justify-between mt-3 pt-3" style={{ borderTop: `1px dashed ${dark.border}` }}>
          <span className="text-[11px]" style={{ color: dark.inkSubtle }}>
            Caja fuerte (aparte, no cuenta acá)
          </span>
          <span className="text-[12px] font-semibold font-mono tabular-nums" style={{ color: dark.inkMuted }}>{fmt(cajaFuerte)}</span>
        </div>
      )}
    </div>
  )
}
