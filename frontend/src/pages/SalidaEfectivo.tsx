import { useRef, useState } from 'react'
import { AlertTriangle, Camera, Check } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { dark } from '../constants/darkTheme'
import { useTurno } from '../contexts/TurnoContext'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import ContadorEfectivo from '../components/ContadorEfectivo'

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`

export default function SalidaEfectivo() {
  const { turno } = useTurno()
  const { resetKiosk } = useAuth()
  const navigate = useNavigate()
  const [efectivoContado, setEfectivoContado] = useState(0)
  const [datafono, setDatafono] = useState(String(Math.round(turno?.total_tarjeta ?? 0)))
  const [imagen, setImagen] = useState<File | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  if (!turno) return null

  const efectivoEsperado = turno.efectivo_esperado_actual ?? 0
  const datafonoVal = Number(datafono) || 0
  const diffEfectivo = Math.round((efectivoContado - efectivoEsperado) * 100) / 100
  const diffDatafono = Math.round((datafonoVal - (turno.total_tarjeta ?? 0)) * 100) / 100
  const hayDescuadre = diffEfectivo !== 0 || diffDatafono !== 0

  const cerrar = async () => {
    setSaving(true)
    setError('')
    try {
      const fd = new FormData()
      fd.append('efectivo_final_real', String(efectivoContado))
      fd.append('datafono_real', String(datafonoVal))
      if (imagen) fd.append('imagen', imagen)
      await api.post(`/caja/${turno.id}/salida`, fd)
      resetKiosk()
      navigate('/', { replace: true })
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al cerrar el turno')
      setSaving(false)
      setConfirming(false)
    }
  }

  if (confirming) {
    return (
      <div className="min-h-screen flex flex-col" style={{ background: dark.bg }}>
        <div className="flex flex-col px-4 pt-14 pb-6 gap-4 max-w-md mx-auto w-full">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: dark.danger }}>
              Confirmar cierre
            </p>
            <p className="text-[18px] font-bold mt-0.5" style={{ color: dark.ink }}>
              ¿Cerrar el turno ahora?
            </p>
          </div>

          {hayDescuadre && (
            <div className="rounded-2xl p-4" style={{ background: dark.dangerTint, border: `1px solid ${dark.dangerDim}` }}>
              <p className="text-[12px] font-bold mb-2 flex items-center gap-1.5" style={{ color: dark.danger }}>
                <AlertTriangle size={13} /> Diferencias detectadas — quedarán registradas
              </p>
              {diffEfectivo !== 0 && (
                <p className="text-[13px] font-mono" style={{ color: dark.danger }}>
                  Efectivo: {diffEfectivo > 0 ? '+' : ''}{fmt(diffEfectivo)}
                </p>
              )}
              {diffDatafono !== 0 && (
                <p className="text-[13px] font-mono" style={{ color: dark.danger }}>
                  Datáfono: {diffDatafono > 0 ? '+' : ''}{fmt(diffDatafono)}
                </p>
              )}
            </div>
          )}

          <div className="rounded-2xl p-4 space-y-2" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
            {[
              { l: 'Efectivo contado', v: fmt(efectivoContado) },
              { l: 'Datáfono a registrar', v: fmt(datafonoVal) },
              { l: 'Total ventas', v: fmt(turno.total_ventas ?? 0) },
            ].map(r => (
              <div key={r.l} className="flex justify-between text-[13px]">
                <span style={{ color: dark.inkSubtle }}>{r.l}</span>
                <span className="font-mono font-semibold" style={{ color: dark.ink }}>{r.v}</span>
              </div>
            ))}
          </div>

          {error && (
            <div className="flex items-center gap-2 rounded-xl px-3 py-2.5 text-[12px]"
              style={{ background: dark.dangerTint, border: `1px solid ${dark.dangerDim}`, color: dark.danger }}>
              <AlertTriangle size={13} /> {error}
            </div>
          )}

          <div className="space-y-2 mt-auto">
            <button
              onClick={cerrar}
              disabled={saving}
              className="w-full py-4 rounded-2xl font-bold text-[15px] text-white disabled:opacity-50"
              style={{ background: dark.danger }}
            >
              {saving ? 'Cerrando turno...' : 'Sí, cerrar turno'}
            </button>
            <button
              onClick={() => setConfirming(false)}
              className="w-full py-3 rounded-2xl font-semibold text-[14px]"
              style={{ background: dark.surface, color: dark.inkSubtle, border: `1px solid ${dark.border}` }}
            >
              Volver
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex flex-col" style={{ background: dark.bg }}>
      <div className="flex flex-col px-4 pt-14 pb-6 gap-5 max-w-md mx-auto w-full">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: dark.danger }}>
            Cierre de turno — Paso 2 de 2
          </p>
          <p className="text-[18px] font-bold mt-0.5" style={{ color: dark.ink }}>
            Cuadre de caja
          </p>
        </div>

        <div className="rounded-2xl p-4" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
          <div className="grid grid-cols-2 gap-2">
            {[
              { l: 'Total ventas', v: fmt(turno.total_ventas ?? 0) },
              { l: 'Efectivo esperado', v: fmt(efectivoEsperado) },
            ].map(r => (
              <div key={r.l}>
                <p className="text-[10px]" style={{ color: dark.inkSubtle }}>{r.l}</p>
                <p className="text-[14px] font-semibold font-mono mt-0.5" style={{ color: dark.ink }}>{r.v}</p>
              </div>
            ))}
          </div>
        </div>

        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest mb-2" style={{ color: dark.inkSubtle }}>
            Conteo de efectivo en caja
          </p>
          <ContadorEfectivo onTotal={setEfectivoContado} />
          {efectivoContado > 0 && diffEfectivo !== 0 && (
            <p className="text-[12px] font-semibold mt-2 pl-1" style={{ color: dark.danger }}>
              Diferencia: {diffEfectivo > 0 ? '+' : ''}{fmt(diffEfectivo)} vs sistema
            </p>
          )}
        </div>

        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest mb-2" style={{ color: dark.inkSubtle }}>
            Total datáfono Bold
          </p>
          <input
            type="number"
            inputMode="numeric"
            value={datafono}
            onChange={e => setDatafono(e.target.value)}
            placeholder="0"
            className="w-full rounded-xl px-4 py-3 text-[20px] font-mono font-bold outline-none"
            style={{ background: dark.surface, border: `1px solid ${dark.border}`, color: dark.ink }}
          />
          {diffDatafono !== 0 && (
            <p className="text-[12px] font-semibold mt-1.5 pl-1" style={{ color: dark.amber }}>
              Diferencia datáfono: {diffDatafono > 0 ? '+' : ''}{fmt(diffDatafono)}
            </p>
          )}
        </div>

        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest mb-2" style={{ color: dark.inkSubtle }}>
            Foto del datáfono (opcional)
          </p>
          <input ref={fileRef} type="file" accept="image/*" capture="environment" className="hidden"
            onChange={e => setImagen(e.target.files?.[0] ?? null)} />
          <button
            onClick={() => fileRef.current?.click()}
            className="w-full flex items-center gap-3 px-4 py-3.5 rounded-2xl"
            style={{ background: dark.surface, border: `1px solid ${imagen ? dark.green : dark.border}` }}
          >
            <Camera size={18} style={{ color: imagen ? dark.green : dark.inkSubtle }} />
            <span className="flex-1 text-left text-[13px]" style={{ color: imagen ? dark.green : dark.inkSubtle }}>
              {imagen ? imagen.name : 'Foto de comprobante (opcional)'}
            </span>
            {imagen && <Check size={14} style={{ color: dark.green }} />}
          </button>
        </div>

        <button
          onClick={() => setConfirming(true)}
          disabled={efectivoContado === 0}
          className="w-full py-4 rounded-2xl font-bold text-[15px] text-white disabled:opacity-40"
          style={{ background: dark.danger }}
        >
          {efectivoContado === 0 ? 'Contá el efectivo primero' : 'Revisar y cerrar turno'}
        </button>
      </div>
    </div>
  )
}
