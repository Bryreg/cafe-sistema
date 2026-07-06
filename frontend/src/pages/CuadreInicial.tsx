import { useEffect, useRef, useState } from 'react'
import { Check, AlertTriangle, Wallet } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { dark } from '../constants/darkTheme'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import ContadorEfectivo from '../components/ContadorEfectivo'
import DiferenciaCaja from '../components/DiferenciaCaja'

const fmt = (v: number) => `$${Math.round(v).toLocaleString('es-CO')}`

/**
 * Cuadre inicial de caja — último paso de la apertura, después del conteo de
 * inventario. Se cuenta el efectivo de la registradora contra lo que dejó el
 * cierre anterior (ventas en efectivo del día anterior, pendientes de consignar).
 * SIN foto: todavía no hay ventas que comprobar.
 */
interface SaldoDia {
  turno_id: number
  fecha_apertura: string
  fecha_cierre: string
  esperado: number
  consignado: number
  pendiente: number
}

const fmtDia = (f: string) => {
  const s = f.replace(' ', 'T').replace('+00:00', 'Z')
  return new Date(s.endsWith('Z') ? s : s + 'Z')
    .toLocaleDateString('es-CO', { weekday: 'long', day: 'numeric', month: 'short' })
}

export default function CuadreInicial() {
  const { turno, refresh } = useTurno()
  const navigate = useNavigate()
  const [contado, setContado] = useState(0)
  const [justificacion, setJustificacion] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [desglose, setDesglose] = useState<{ cierre: number; baseAyer: number; mismoDia: boolean } | null>(null)
  // Saldos pendientes por consignar de días anteriores: la barista marca cuáles
  // están FÍSICAMENTE en la caja (a veces conviven varios días sin consignar).
  const [saldos, setSaldos] = useState<SaldoDia[] | null>(null)
  const [marcados, setMarcados] = useState<Record<number, boolean>>({})
  // Candado síncrono contra doble click: el estado saving es async y deja una
  // ventana en la que un segundo click dispararía otro POST.
  const enviando = useRef(false)

  useEffect(() => {
    if (!turno) return
    api.get(`/caja/efectivo-inicio/${turno.tienda_id}`)
      .then(r => setDesglose({
        cierre: r.data?.efectivo_cierre_anterior ?? 0,
        baseAyer: r.data?.base_consignar_anterior ?? 0,
        mismoDia: !!r.data?.mismo_dia,
      }))
      .catch(() => setDesglose(null))
    api.get(`/consignaciones/pendiente/${turno.tienda_id}`)
      .then(r => {
        const items: SaldoDia[] = (r.data?.items ?? []).filter((s: SaldoDia) => s.turno_id !== turno.id)
        setSaldos(items)
        // Por defecto TODOS marcados (si no se consignó, la plata debería estar en caja)
        const ini: Record<number, boolean> = {}
        for (const s of items) ini[s.turno_id] = true
        setMarcados(ini)
      })
      .catch(() => setSaldos(null))
  }, [turno?.tienda_id])

  // Ya cuadrado (o sin turno): salir de acá
  useEffect(() => {
    if (!turno) return
    if (turno.tiene_cuadre_llegada) navigate(turno.es_operativo ? '/pos' : '/gestion-turno', { replace: true })
  }, [turno, navigate])

  if (!turno) return null

  // Con saldos por día: esperado = suma de los MARCADOS (el server lo recalcula
  // igual — esta suma es solo para mostrar). Sin saldos: legacy (último cierre).
  const modoSaldos = saldos !== null && saldos.length > 0
  const esperado = modoSaldos
    ? saldos!.reduce((acc, s) => acc + (marcados[s.turno_id] ? s.pendiente : 0), 0)
    : (turno.base_sistema ?? 0)
  const diff = Math.round(contado - esperado)
  const necesitaJustificacion = contado > 0 && diff !== 0

  const confirmar = async () => {
    if (contado <= 0 || enviando.current) return
    enviando.current = true
    setSaving(true); setError('')
    try {
      const fd = new FormData()
      fd.append('efectivo_real', String(contado))
      if (justificacion.trim()) fd.append('justificacion', justificacion.trim())
      if (modoSaldos) {
        const ids = saldos!.filter(s => marcados[s.turno_id]).map(s => s.turno_id)
        fd.append('saldos_incluidos', JSON.stringify(ids))
      }
      const { data } = await api.post(`/caja/${turno.id}/cuadre-inicial`, fd)
      await refresh()
      navigate(data?.es_operativo ? '/pos' : '/gestion-turno', { replace: true })
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al registrar el cuadre')
      enviando.current = false
      setSaving(false)
    }
  }

  return (
    <div className="min-h-screen flex flex-col" style={{ background: dark.bg }}>
      <div className="flex flex-col px-4 pt-14 pb-8 gap-4 max-w-md mx-auto w-full">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: dark.amber }}>
            Apertura de turno — Último paso
          </p>
          <p className="text-[18px] font-bold mt-0.5" style={{ color: dark.ink }}>
            Cuadre inicial de caja
          </p>
        </div>

        {/* Esperado: lo que dejó el día anterior */}
        <div className="rounded-2xl p-4" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
          <p className="text-[10px] font-bold uppercase tracking-widest mb-2 flex items-center gap-1.5" style={{ color: dark.inkSubtle }}>
            <Wallet size={12} /> Debería haber en la registradora
          </p>
          <p className="text-[28px] font-bold font-mono tabular-nums leading-none" style={{ color: dark.ink }}>
            {fmt(esperado)}
          </p>

          {modoSaldos ? (
            <div className="mt-3 space-y-1.5">
              <p className="text-[11px] font-bold uppercase tracking-wide" style={{ color: dark.amber }}>
                ¿La plata de qué días está en la caja?
              </p>
              {saldos!.map(s => (
                <button key={s.turno_id}
                  onClick={() => setMarcados(prev => ({ ...prev, [s.turno_id]: !prev[s.turno_id] }))}
                  className="w-full flex items-center gap-2.5 rounded-xl px-3 py-2.5 text-left transition-colors"
                  style={{
                    background: marcados[s.turno_id] ? dark.surfaceAlt : 'transparent',
                    border: `2px solid ${marcados[s.turno_id] ? dark.greenDim : dark.border}`,
                  }}>
                  <span className="w-5 h-5 rounded-md flex items-center justify-center shrink-0"
                    style={{
                      background: marcados[s.turno_id] ? dark.green : 'transparent',
                      border: marcados[s.turno_id] ? 'none' : `2px solid ${dark.inkSubtle}`,
                    }}>
                    {marcados[s.turno_id] && <Check size={13} strokeWidth={3} style={{ color: dark.bg }} />}
                  </span>
                  <span className="flex-1 text-[13px] font-semibold capitalize" style={{ color: dark.ink }}>
                    {fmtDia(s.fecha_apertura || s.fecha_cierre)}
                  </span>
                  <span className="text-[13px] font-bold font-mono tabular-nums"
                    style={{ color: marcados[s.turno_id] ? dark.green : dark.inkSubtle }}>
                    {fmt(s.pendiente)}
                  </span>
                </button>
              ))}
              <p className="text-[11px] mt-1" style={{ color: dark.inkSubtle }}>
                Marcá solo los días cuya plata está físicamente acá. Si un día ya se consignó
                o está apartado, destildalo.
              </p>
            </div>
          ) : desglose && !desglose.mismoDia ? (
            <p className="text-[11px] mt-2" style={{ color: dark.inkSubtle }}>
              Efectivo del cierre de ayer ({fmt(desglose.cierre)}) menos la base de ayer que se
              consigna completa ({fmt(desglose.baseAyer)}). Los pagos de contado de ayer ya
              salieron de la venta de ayer.
            </p>
          ) : desglose?.mismoDia ? (
            <p className="text-[11px] mt-2" style={{ color: dark.inkSubtle }}>
              Relevo del mismo día: queda todo el efectivo que dejó el cierre anterior (menos lo consignado).
            </p>
          ) : (
            <p className="text-[11px] mt-2" style={{ color: dark.inkSubtle }}>
              Lo que dejó el último cierre para arrancar el día.
            </p>
          )}
        </div>

        <ContadorEfectivo onTotal={setContado} />

        <DiferenciaCaja contado={contado} esperado={esperado} />

        {necesitaJustificacion && (
          <textarea
            value={justificacion}
            onChange={e => setJustificacion(e.target.value)}
            placeholder="Hay diferencia con lo esperado — escribí el motivo (obligatorio)"
            rows={2}
            className="w-full rounded-xl px-3 py-2.5 text-sm resize-none outline-none"
            style={{ background: dark.surface, border: `1px solid ${dark.amberDim}`, color: dark.ink }}
          />
        )}

        {error && (
          <div className="flex items-center gap-2 rounded-xl px-3 py-2.5 text-[12px]"
            style={{ background: dark.dangerTint, border: `1px solid ${dark.dangerDim}`, color: dark.danger }}>
            <AlertTriangle size={13} /> {error}
          </div>
        )}

        <button
          onClick={confirmar}
          disabled={saving || contado <= 0 || (necesitaJustificacion && !justificacion.trim())}
          className="w-full py-4 rounded-2xl font-bold text-[15px] text-white disabled:opacity-40 flex items-center justify-center gap-2"
          style={{ background: dark.green }}>
          <Check size={18} strokeWidth={2.5} />
          {saving ? 'Registrando...'
            : contado <= 0 ? 'Contá el efectivo primero'
            : (necesitaJustificacion && !justificacion.trim()) ? 'Escribí el motivo de la diferencia'
            : 'Confirmar cuadre y empezar a vender'}
        </button>
        <p className="text-[11px] text-center" style={{ color: dark.inkSubtle }}>
          Sin foto: todavía no hay ventas que comprobar.
        </p>
      </div>
    </div>
  )
}
