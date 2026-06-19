import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import { Check, ChevronLeft, Lock, AlertTriangle } from 'lucide-react'
import { dark } from '../constants/darkTheme'

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`
const fmtSigned = (v: number) => (v === 0 ? '$0' : (v > 0 ? '+' : '') + fmt(Math.abs(v)))

export default function CuadreLlegada() {
  const { user, tipo_turno, setCuadreLlegadaDone } = useAuth()
  const { turno, loading } = useTurno()
  const navigate = useNavigate()

  const [efectivoReal, setEfectivoReal] = useState('')
  const [ventasBold, setVentasBold]     = useState('')
  const [nota, setNota]                 = useState('')
  const [error, setError]               = useState('')
  const [saving, setSaving]             = useState(false)

  if (loading) return (
    <div className="min-h-screen flex items-center justify-center" style={{ background: 'oklch(10% 0.005 60)' }}>
      <p className="text-sm animate-pulse" style={{ color: 'oklch(55% 0.01 60)' }}>Consultando turno...</p>
    </div>
  )

  if (!turno) return (
    <div className="min-h-screen flex items-center justify-center p-6" style={{ background: 'oklch(10% 0.005 60)' }}>
      <p className="text-sm text-center" style={{ color: 'oklch(55% 0.01 60)' }}>
        No hay turno activo para esta sede.<br />Contacta al encargado de apertura.
      </p>
    </div>
  )

  const ef       = Number(efectivoReal) || 0
  const esperado = turno.efectivo_esperado_actual ?? 0
  const diff     = efectivoReal.trim() !== '' ? ef - esperado : null

  const step1Done = ef > 0
  const step2Done = ventasBold.trim() !== ''   // Verifica Bold
  const currentStep = !step1Done ? 1 : !step2Done ? 2 : 3
  const canSubmit   = step1Done

  // Turno info
  const esCierre   = tipo_turno === 'cierre'
  const turnoLabel = esCierre ? 'Cierre' : 'Intermedio'

  const guardar = async () => {
    setSaving(true); setError('')
    try {
      const form = new FormData()
      form.append('efectivo_real', String(ef))
      form.append('tipo_turno', tipo_turno ?? 'intermedio')
      const notaFull = [
        nota.trim(),
        ventasBold ? `Bold: ${ventasBold}` : '',
      ].filter(Boolean).join(' | ')
      if (notaFull) form.append('nota', notaFull)
      await api.post(`/caja/${turno.id}/cuadre-llegada`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setCuadreLlegadaDone(turno.id)
      navigate('/hub', { replace: true })
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al registrar cuadre')
    } finally {
      setSaving(false)
    }
  }

  const StepHeader = ({ n, title, done, active: isActive }: {
    n: number; title: string; done: boolean; active: boolean
  }) => (
    <div className="flex items-center gap-2.5 mb-2.5">
      <div className="w-[22px] h-[22px] rounded-full flex items-center justify-center shrink-0 text-[11px] font-bold"
        style={{
          background: done ? dark.greenDim : isActive ? dark.amberDim : 'rgba(255,255,255,0.06)',
          color: done || isActive ? '#fff' : dark.inkSubtle,
        }}>
        {done ? <Check size={12} strokeWidth={2.5} /> : n}
      </div>
      <span className="text-[13px] font-bold uppercase tracking-wide"
        style={{ color: done ? dark.green : isActive ? dark.amber : dark.inkSubtle }}>
        {title}
      </span>
      {isActive && (
        <span className="ml-auto text-[10px] font-bold uppercase tracking-wide" style={{ color: dark.amber }}>
          Paso actual
        </span>
      )}
    </div>
  )

  return (
    <div className="min-h-screen flex flex-col" style={{ background: dark.bg }}>

      {/* Header */}
      <header className="flex items-center gap-2.5 px-4 pb-2.5 pt-3 shrink-0" style={{ background: dark.bg }}>
        <button
          onClick={() => navigate('/hub')}
          className="w-7 h-7 rounded-lg flex items-center justify-center"
          style={{ background: 'rgba(255,255,255,0.06)', color: dark.inkMuted }}
          aria-label="Volver"
        >
          <ChevronLeft size={16} />
        </button>
        <div className="flex-1 min-w-0">
          <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: dark.amber }}>
            Cuadre de llegada
          </p>
          <p className="text-[14px] font-bold leading-tight" style={{ color: dark.ink }}>
            Turno {turnoLabel} · {user?.nombre}
          </p>
        </div>
        <span className="text-[11px] font-mono font-semibold" style={{ color: dark.inkSubtle }}>
          {currentStep > 2 ? '2/2' : `${Math.max(0, currentStep - 1)}/2`}
        </span>
      </header>

      {/* Body */}
      <div className="flex-1 overflow-auto px-4 pb-28 space-y-4 pt-1">

        {/* Ventas del día */}
        <div className="rounded-2xl p-4"
          style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
          <p className="text-[10px] font-bold uppercase tracking-widest mb-2" style={{ color: dark.inkSubtle }}>
            Ventas del día
          </p>
          <p className="text-[28px] font-bold font-mono leading-none mb-3"
            style={{ color: dark.ink, letterSpacing: '-1px' }}>
            {fmt(turno.total_ventas ?? 0)}
          </p>
          <div className="grid grid-cols-2 gap-2 pt-3" style={{ borderTop: `1px solid ${dark.border}` }}>
            {[
              { l: 'Efectivo',  v: fmt(turno.total_efectivo ?? 0) },
              { l: 'Tarjeta',   v: fmt(turno.total_tarjeta ?? 0) },
            ].map(row => (
              <div key={row.l} className="flex justify-between items-baseline gap-2">
                <span className="text-[11px]" style={{ color: dark.inkSubtle }}>{row.l}</span>
                <span className="text-[12px] font-semibold font-mono" style={{ color: dark.ink }}>{row.v}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Hero — efectivo esperado */}
        <div className="rounded-2xl p-4"
          style={{ background: 'oklch(16% 0.015 55)', border: `1px solid ${dark.border}` }}>
          <p className="text-[10px] font-bold uppercase tracking-widest mb-2" style={{ color: dark.inkSubtle }}>
            Lo que debe haber en caja
          </p>
          <p className="text-[36px] font-bold font-mono leading-none mb-3"
            style={{ color: dark.ink, letterSpacing: '-1.5px' }}>
            {fmt(esperado)}
          </p>
          <div className="grid grid-cols-2 gap-2 pt-3" style={{ borderTop: `1px solid ${dark.border}` }}>
            {[
              { l: 'Base apertura',  v: fmt(turno.base_real ?? 0) },
              { l: '+ Ventas ef.',   v: fmt(turno.total_efectivo ?? 0) },
              { l: '+ Ing. mov.',    v: fmt(turno.ingresos_movimientos ?? 0) },
              { l: '− Egr. mov.',    v: fmt(turno.egresos_movimientos ?? 0) },
            ].map(row => (
              <div key={row.l} className="flex justify-between items-baseline gap-2">
                <span className="text-[11px]" style={{ color: dark.inkSubtle }}>{row.l}</span>
                <span className="text-[12px] font-semibold font-mono" style={{ color: dark.ink }}>{row.v}</span>
              </div>
            ))}
            {(turno.consignaciones_turno ?? 0) > 0 && (
              <div className="col-span-2 flex justify-between items-baseline gap-2 mt-1 pt-1"
                style={{ borderTop: `1px solid ${dark.border}` }}>
                <span className="text-[11px]" style={{ color: dark.inkSubtle }}>− Consignación</span>
                <span className="text-[12px] font-semibold font-mono" style={{ color: dark.dangerDim }}>
                  {fmt(turno.consignaciones_turno ?? 0)}
                </span>
              </div>
            )}
          </div>
        </div>

        {error && (
          <div className="flex items-center gap-2 rounded-xl px-3 py-2.5 text-[12px]"
            style={{ background: 'oklch(20% 0.08 25)', border: `1px solid ${dark.dangerDim}`, color: dark.danger }}>
            <AlertTriangle size={13} /> {error}
          </div>
        )}

        {/* Paso 1 — Cuenta el efectivo */}
        <div className="space-y-2">
          <StepHeader n={1} title="Cuenta el efectivo" done={step1Done} active={currentStep === 1} />
          <div className="rounded-xl px-4 py-3 flex items-center justify-between gap-3"
            style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
            <span className="text-[12px]" style={{ color: dark.inkMuted }}>Efectivo real en caja</span>
            <input
              type="number"
              inputMode="numeric"
              value={efectivoReal}
              onChange={e => setEfectivoReal(e.target.value)}
              placeholder="0"
              className="text-[22px] font-bold font-mono text-right bg-transparent outline-none w-40"
              style={{ color: dark.ink }}
            />
          </div>

          {diff !== null && (
            <div className="rounded-xl flex items-center justify-between px-4 py-2.5"
              style={{
                background: diff === 0 ? 'oklch(22% 0.08 155 / 0.4)' : 'oklch(22% 0.12 25 / 0.4)',
                border: `1px solid ${diff === 0 ? 'oklch(38% 0.10 155 / 0.6)' : 'oklch(40% 0.16 25 / 0.6)'}`,
              }}>
              <span className="text-[11px] flex items-center gap-1.5" style={{ color: dark.inkMuted }}>
                {diff === 0
                  ? <Check size={12} color={dark.green} />
                  : <AlertTriangle size={12} color={dark.danger} />}
                Diferencia
              </span>
              <span className="text-[18px] font-bold font-mono"
                style={{ color: diff === 0 ? dark.green : dark.danger, letterSpacing: '-0.3px' }}>
                {fmtSigned(diff)}
              </span>
            </div>
          )}
        </div>

        {/* Paso 2 — Verifica Bold */}
        <div className="space-y-2">
          <StepHeader n={2} title="Verifica Bold" done={step2Done} active={currentStep === 2} />
          <div className="rounded-xl px-4 py-3 flex items-center justify-between gap-3"
            style={{ background: dark.surface, border: `1px solid ${currentStep === 2 ? dark.amberDim : dark.border}` }}>
            <div>
              <p className="text-[12px] font-semibold" style={{ color: dark.ink }}>Ventas tarjeta Bold</p>
              <p className="text-[10px] mt-0.5" style={{ color: dark.inkSubtle }}>
                Sistema: {fmt(turno.total_tarjeta ?? 0)}
              </p>
            </div>
            <input
              type="number"
              inputMode="numeric"
              value={ventasBold}
              onChange={e => setVentasBold(e.target.value)}
              placeholder="$ ___"
              className="text-[22px] font-bold font-mono text-right bg-transparent outline-none w-40"
              style={{ color: dark.amber }}
            />
          </div>
          <p className="text-[11px] pl-1" style={{ color: dark.inkSubtle }}>
            Total mostrado en el datáfono
          </p>
        </div>

        {/* Notas */}
        <div>
          <p className="text-[10px] font-bold uppercase tracking-wide mb-2" style={{ color: dark.inkSubtle }}>
            Observaciones (opcional)
          </p>
          <textarea
            value={nota}
            onChange={e => setNota(e.target.value)}
            placeholder="Ej: faltaban $5.000 en el cajón..."
            rows={2}
            className="w-full rounded-xl px-3 py-2.5 text-sm resize-none outline-none"
            style={{
              background: dark.surface,
              border: `1px solid ${dark.border}`,
              color: dark.ink,
            }}
          />
        </div>
      </div>

      {/* CTA sticky */}
      <div className="fixed bottom-0 left-0 right-0 px-4 pb-8 pt-3"
        style={{
          background: `linear-gradient(to top, ${dark.bg} 70%, transparent)`,
          borderTop: `1px solid ${dark.border}`,
        }}>
        <button
          onClick={canSubmit ? guardar : undefined}
          disabled={!canSubmit || saving}
          className="w-full py-4 rounded-2xl text-[15px] font-bold flex items-center justify-center gap-2 transition-all"
          style={{
            background: canSubmit ? dark.greenDim : 'oklch(20% 0.04 155)',
            color: '#fff',
            opacity: !canSubmit || saving ? 0.55 : 1,
            cursor: !canSubmit ? 'not-allowed' : 'pointer',
          }}
        >
          {saving ? 'Registrando...'
            : !canSubmit ? <><Lock size={14} /> Cuenta el efectivo primero</>
            : <><Check size={16} strokeWidth={2.5} /> Confirmar llegada</>
          }
        </button>
      </div>
    </div>
  )
}
