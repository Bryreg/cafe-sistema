import { useEffect, useState } from 'react'
import api from '../../api/client'
import { AlertTriangle, Check, Loader2, Save } from 'lucide-react'
import { Aviso } from './SemanaGrid'
import { fmtPct, type FestivoRow, type Tasa } from './tipos'

/**
 * Tasas de ley y festivos.
 *
 * Estos números NO son una afirmación del sistema: son lo que está cargado, y
 * se pueden editar. Cada vigencia trae la nota de dónde salió y una marca de
 * "sin confirmar" que se baja cuando el contador la valida. El copy de esta
 * pantalla dice «según lo que cargaste», nunca «según la ley».
 */

interface Props { anio: number }

export default function TasasPanel({ anio }: Props) {
  const [tasas, setTasas] = useState<Tasa[]>([])
  const [festivos, setFestivos] = useState<FestivoRow[]>([])
  const [loading, setLoading] = useState(true)
  const [guardando, setGuardando] = useState<number | null>(null)
  const [guardado, setGuardado] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const cargar = () => {
    setLoading(true)
    Promise.all([
      api.get<Tasa[]>('/horarios/tasas'),
      api.get<FestivoRow[]>('/horarios/festivos', { params: { anio } }),
    ])
      .then(([t, f]) => { setTasas(t.data); setFestivos(f.data) })
      .catch(() => setError('No se pudieron cargar las tasas.'))
      .finally(() => setLoading(false))
  }
  useEffect(cargar, [anio])

  const patch = (id: number, cambios: Partial<Tasa>) => {
    setTasas(prev => prev.map(t => (t.id === id ? { ...t, ...cambios } : t)))
    setGuardado(null)
  }

  const guardar = async (t: Tasa) => {
    setGuardando(t.id); setError(null)
    try {
      const { data } = await api.patch<Tasa>(`/horarios/tasas/${t.id}`, {
        jornada_max_semanal: t.jornada_max_semanal,
        hora_inicio_nocturna: t.hora_inicio_nocturna,
        hora_fin_nocturna: t.hora_fin_nocturna,
        recargo_nocturno: t.recargo_nocturno,
        recargo_dominical: t.recargo_dominical,
        extra_diurna: t.extra_diurna,
        extra_nocturna: t.extra_nocturna,
        divisor_hora_mensual: t.divisor_hora_mensual,
        confirmar_contador: t.confirmar_contador,
      })
      setTasas(prev => prev.map(x => (x.id === data.id ? data : x)))
      setGuardado(t.id)
    } catch { setError('No se pudo guardar la tasa.') }
    finally { setGuardando(null) }
  }

  if (loading) {
    return <p className="text-sm text-warm-400 py-10 text-center animate-pulse">Cargando…</p>
  }

  const sinConfirmar = tasas.filter(t => t.confirmar_contador).length

  return (
    <div className="space-y-4">
      {error && <Aviso tono="error">{error}</Aviso>}

      <div className="bg-white rounded-2xl border border-warm-200 p-4 space-y-1">
        <p className="text-sm font-bold text-warm-700">Cómo se usan estas tasas</p>
        <p className="text-xs text-warm-500">
          Cada turno se liquida con la tasa vigente EL DÍA DEL TURNO, no con la de hoy:
          por eso recalcular un mes viejo siempre da lo mismo. Son valores editables —
          el sistema no reemplaza al contador.
        </p>
        {sinConfirmar > 0 && (
          <p className="text-xs text-clay-600 font-semibold flex items-center gap-1.5 pt-1">
            <AlertTriangle size={13} />
            {sinConfirmar} vigencia(s) todavía sin confirmar con tu contador. Revisá la nota
            de cada una y destildá «sin confirmar» cuando te las valide.
          </p>
        )}
      </div>

      {/* ── Vigencias ── */}
      <div className="space-y-2">
        {tasas.map(t => (
          <div key={t.id} className="bg-white rounded-2xl border border-warm-200 p-4 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-bold text-warm-700 font-mono">
                Desde {t.vigente_desde}
              </span>
              {t.confirmar_contador && (
                <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-clay-100 text-clay-600">
                  sin confirmar
                </span>
              )}
              <div className="flex-1" />
              <button
                onClick={() => guardar(t)}
                disabled={guardando === t.id}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-forest text-white hover:bg-forest/90 disabled:opacity-40"
              >
                {guardando === t.id ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                Guardar
              </button>
              {guardado === t.id && (
                <span className="flex items-center gap-1 text-xs text-forest-700 font-medium">
                  <Check size={12} /> guardado
                </span>
              )}
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <Campo label="Jornada máx. semanal" sufijo="h"
                value={t.jornada_max_semanal}
                onChange={v => patch(t.id, { jornada_max_semanal: v })} />
              <Campo label="Noche empieza" sufijo="h"
                value={t.hora_inicio_nocturna}
                onChange={v => patch(t.id, { hora_inicio_nocturna: v })} />
              <Campo label="Noche termina" sufijo="h"
                value={t.hora_fin_nocturna}
                onChange={v => patch(t.id, { hora_fin_nocturna: v })} />
              <Campo label="Divisor hora/mes"
                value={t.divisor_hora_mensual}
                onChange={v => patch(t.id, { divisor_hora_mensual: v })} />
              <CampoPct label="Recargo nocturno" value={t.recargo_nocturno}
                onChange={v => patch(t.id, { recargo_nocturno: v })} />
              <CampoPct label="Dominical/festivo" value={t.recargo_dominical}
                onChange={v => patch(t.id, { recargo_dominical: v })} />
              <CampoPct label="Extra diurna" value={t.extra_diurna}
                onChange={v => patch(t.id, { extra_diurna: v })} />
              <CampoPct label="Extra nocturna" value={t.extra_nocturna}
                onChange={v => patch(t.id, { extra_nocturna: v })} />
            </div>

            <p className="text-[11px] text-warm-400">
              Dominical + nocturno se calcula solo:{' '}
              <b className="font-mono">{fmtPct(t.recargo_dominical_nocturno_efectivo)}</b>
              {' '}(dominical + nocturno). Así los dos números no pueden quedar en desacuerdo.
            </p>

            {t.nota && <p className="text-[11px] text-warm-500 leading-relaxed">{t.nota}</p>}

            <label className="flex items-center gap-2 text-xs text-warm-600">
              <input
                type="checkbox" checked={t.confirmar_contador}
                onChange={e => patch(t.id, { confirmar_contador: e.target.checked })}
                className="h-4 w-4 rounded border-warm-200 text-forest focus:ring-forest"
              />
              Todavía sin confirmar con el contador
            </label>
          </div>
        ))}
      </div>

      {/* ── Festivos ── */}
      <div className="bg-white rounded-2xl border border-warm-200 p-4">
        <p className="text-sm font-bold text-warm-700 mb-1">Festivos {anio}</p>
        <p className="text-xs text-warm-400 mb-3">
          Los calcula el sistema (fechas fijas, traslado al lunes de la Ley Emiliani y los
          que dependen de la Pascua). Un día de estos cuenta con recargo dominical/festivo.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-1">
          {festivos.map(f => (
            <div key={f.fecha} className="flex items-baseline gap-2 text-xs">
              <span className={`font-mono ${f.es_festivo ? 'text-warm-700' : 'text-warm-400 line-through'}`}>
                {f.fecha}
              </span>
              <span className={f.es_festivo ? 'text-warm-500' : 'text-warm-400'}>{f.nombre}</span>
              {f.origen !== 'calculado' && (
                <span className="text-[10px] text-clay-600">{f.origen}</span>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function Campo({ label, value, onChange, sufijo }: {
  label: string; value: number; onChange: (v: number) => void; sufijo?: string
}) {
  return (
    <label className="block">
      <span className="text-[11px] font-semibold text-warm-400">{label}</span>
      <div className="flex items-center gap-1">
        <input
          type="number" step="any" value={value}
          onChange={e => onChange(Number(e.target.value))}
          className="mt-0.5 w-full border border-warm-200 rounded-lg px-2 py-1 text-sm font-mono"
        />
        {sufijo && <span className="text-xs text-warm-400">{sufijo}</span>}
      </div>
    </label>
  )
}

function CampoPct({ label, value, onChange }: {
  label: string; value: number; onChange: (v: number) => void
}) {
  return (
    <label className="block">
      <span className="text-[11px] font-semibold text-warm-400">{label}</span>
      <div className="flex items-center gap-1">
        <input
          type="number" step="1" value={Math.round(value * 100)}
          onChange={e => onChange(Number(e.target.value) / 100)}
          className="mt-0.5 w-full border border-warm-200 rounded-lg px-2 py-1 text-sm font-mono"
        />
        <span className="text-xs text-warm-400">%</span>
      </div>
    </label>
  )
}
