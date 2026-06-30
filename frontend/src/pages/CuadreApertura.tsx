import { useRef, useState } from 'react'
import { Camera, Check, AlertTriangle } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { dark } from '../constants/darkTheme'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import ContadorEfectivo from '../components/ContadorEfectivo'

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`

export default function CuadreApertura() {
  const { turno, refresh } = useTurno()
  const navigate = useNavigate()
  const [efectivoReal, setEfectivoReal] = useState(0)
  const [ventasTarjetaBold, setVentasTarjetaBold] = useState('')
  const [imagen, setImagen] = useState<File | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  if (!turno) return null

  const canConfirm = efectivoReal > 0 && ventasTarjetaBold.trim() !== '' && imagen !== null

  const confirmar = async () => {
    if (!canConfirm) return
    setSaving(true)
    setError('')
    try {
      const fd = new FormData()
      fd.append('efectivo_real', String(efectivoReal))
      fd.append('ventas_tarjeta_bold', String(Number(ventasTarjetaBold) || 0))
      fd.append('imagen', imagen!)
      await api.post(`/caja/${turno.id}/entrega`, fd)
      await refresh()
      navigate('/gestion-turno')
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al registrar cuadre')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="min-h-screen flex flex-col" style={{ background: dark.bg }}>
      <div className="flex flex-col px-4 pt-14 pb-8 gap-4 max-w-md mx-auto w-full">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: dark.amber }}>
            Apertura de turno — Paso 3 de 5
          </p>
          <p className="text-[18px] font-bold mt-0.5" style={{ color: dark.ink }}>
            Cuadre de caja
          </p>
        </div>

        <div className="rounded-2xl p-4" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
          <p className="text-[10px] font-bold uppercase tracking-widest mb-3" style={{ color: dark.inkSubtle }}>
            Estado esperado al abrir
          </p>
          <div className="grid grid-cols-2 gap-3">
            {[
              { l: 'Ventas del día',    v: fmt(turno.total_ventas ?? 0) },
              { l: 'Efectivo esperado', v: fmt(turno.efectivo_esperado_actual ?? 0) },
              { l: 'Tarjeta',           v: fmt(turno.total_tarjeta ?? 0) },
              { l: 'Efectivo ventas',   v: fmt(turno.total_efectivo ?? 0) },
            ].map(r => (
              <div key={r.l}>
                <p className="text-[10px]" style={{ color: dark.inkSubtle }}>{r.l}</p>
                <p className="text-[14px] font-semibold font-mono mt-0.5" style={{ color: dark.ink }}>{r.v}</p>
              </div>
            ))}
          </div>
        </div>

        <ContadorEfectivo onTotal={setEfectivoReal} />

        <div className="rounded-2xl p-4 space-y-2" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
          <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: dark.inkSubtle }}>
            Ventas tarjeta Bold
          </p>
          <input
            type="number" min="0" step="100"
            value={ventasTarjetaBold}
            onChange={e => setVentasTarjetaBold(e.target.value)}
            placeholder="$0"
            className="w-full bg-transparent text-[18px] font-mono font-semibold outline-none"
            style={{ color: dark.ink }}
          />
        </div>

        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest mb-2"
            style={{ color: imagen ? dark.inkSubtle : dark.danger }}>
            Foto de comprobante (obligatoria)
          </p>
          <input ref={fileRef} type="file" accept="image/*" capture="environment" className="hidden"
            onChange={e => setImagen(e.target.files?.[0] ?? null)} />
          <button onClick={() => fileRef.current?.click()}
            className="w-full flex items-center gap-3 px-4 py-3.5 rounded-2xl"
            style={{ background: dark.surface, border: `1px solid ${imagen ? dark.green : dark.dangerDim}` }}>
            <Camera size={18} style={{ color: imagen ? dark.green : dark.danger }} />
            <span className="flex-1 text-left text-[13px]" style={{ color: imagen ? dark.green : dark.danger }}>
              {imagen ? imagen.name : 'Foto de pantalla + datáfono (obligatoria)'}
            </span>
            {imagen && <Check size={14} style={{ color: dark.green }} />}
          </button>
        </div>

        {error && (
          <div className="flex items-center gap-2 rounded-xl px-3 py-2.5 text-[12px]"
            style={{ background: dark.dangerTint, border: `1px solid ${dark.dangerDim}`, color: dark.danger }}>
            <AlertTriangle size={13} /> {error}
          </div>
        )}

        <button onClick={confirmar} disabled={saving || !canConfirm}
          className="w-full py-4 rounded-2xl font-bold text-[15px] text-white disabled:opacity-40 flex items-center justify-center gap-2"
          style={{ background: dark.green }}>
          <Check size={18} strokeWidth={2.5} />
          {saving ? 'Registrando...' : 'Confirmar cuadre de apertura'}
        </button>
      </div>
    </div>
  )
}
