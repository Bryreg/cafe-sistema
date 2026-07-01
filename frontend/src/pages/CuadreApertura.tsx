import { useEffect, useRef, useState } from 'react'
import { Camera, Check, AlertTriangle } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { dark } from '../constants/darkTheme'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import ContadorEfectivo from '../components/ContadorEfectivo'
import DesgloseEfectivo, { MovimientoDesglose } from '../components/DesgloseEfectivo'
import DiferenciaCaja from '../components/DiferenciaCaja'

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
  const [movimientos, setMovimientos] = useState<MovimientoDesglose[]>([])

  useEffect(() => {
    if (!turno) return
    api.get(`/caja/${turno.id}/movimientos`)
      .then(r => setMovimientos((r.data ?? []).map((m: any) => ({ tipo: m.tipo, concepto: m.concepto, valor: m.valor, fecha: m.fecha }))))
      .catch(() => setMovimientos([]))
  }, [turno?.id])

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

        <DesgloseEfectivo
          base={turno.base_real ?? 0}
          ventasEfectivo={turno.total_efectivo ?? 0}
          ingresos={turno.ingresos_movimientos ?? 0}
          egresos={turno.egresos_movimientos ?? 0}
          esperado={turno.efectivo_esperado_actual ?? 0}
          cajaFuerte={turno.caja_fuerte ?? 0}
          movimientos={movimientos}
        />
        <div className="flex items-center justify-between px-1 -mt-1">
          <span className="text-[11px]" style={{ color: dark.inkSubtle }}>Ventas del día {fmt(turno.total_ventas ?? 0)}</span>
          <span className="text-[11px]" style={{ color: dark.inkSubtle }}>Tarjeta esperada {fmt(turno.total_tarjeta ?? 0)}</span>
        </div>

        <ContadorEfectivo onTotal={setEfectivoReal} />

        <DiferenciaCaja contado={efectivoReal} esperado={turno.efectivo_esperado_actual ?? 0} />

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
