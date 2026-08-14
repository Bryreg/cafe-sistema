import { useEffect, useState } from 'react'
import api from '../../api/client'
import {
  AlertTriangle, Check, ChevronLeft, ChevronRight, Copy, Loader2, Plus, Send,
  Trash2, X,
} from 'lucide-react'
import {
  aISO, fmtHoras, lunesDe, sumarDias, type BaristaSemana, type Semana,
  type TurnoProgramado,
} from './tipos'

/**
 * Armado del horario semanal: grilla barista × día.
 *
 * El total de cada barista se compara EN VIVO contra la jornada máxima vigente
 * esa semana, así el admin ve que alguien se pasa ANTES de enviar el horario —
 * que es el momento en que todavía se puede arreglar sin deberle horas extra
 * a nadie.
 */

interface Props { tiendaId: number }

const HORAS_SUGERIDAS = ['06:00', '07:00', '08:00', '12:00', '13:00', '14:00',
  '16:00', '18:00', '20:00', '22:00']

/** Duraciones de almuerzo que se usan de verdad. 0 = el turno no tiene. */
const MINUTOS_ALMUERZO = [0, 30, 45, 60, 90]

/** Lo que el formulario devuelve: el turno completo, almuerzo incluido. */
interface DatosTurno {
  hora_inicio: string
  hora_fin: string
  almuerzo_inicio: string | null
  almuerzo_minutos: number | null
}

/** Qué celda está abierta y, si se está editando, sobre qué turno. */
interface Edicion {
  usuarioId: number
  fecha: string
  turno?: TurnoProgramado
}

export default function SemanaGrid({ tiendaId }: Props) {
  const [lunes, setLunes] = useState(() => lunesDe(new Date()))
  const [data, setData] = useState<Semana | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [editando, setEditando] = useState<Edicion | null>(null)

  const cargar = () => {
    setLoading(true)
    api.get<Semana>('/horarios/semana', { params: { tienda_id: tiendaId, lunes: aISO(lunes) } })
      .then(r => setData(r.data))
      .catch(() => setError('No se pudo cargar la semana.'))
      .finally(() => setLoading(false))
  }

  useEffect(cargar, [tiendaId, lunes])

  const mover = (semanas: number) => setLunes(l => sumarDias(l, semanas * 7))

  const guardar = async (usuarioId: number, fecha: string, datos: DatosTurno) => {
    setBusy(true); setError(null); setAviso(null)
    try {
      // La clave natural es (barista, fecha, hora de entrada): guardar con la
      // misma entrada EDITA el turno, no lo duplica.
      await api.post('/horarios/turno', {
        tienda_id: tiendaId, usuario_id: usuarioId, fecha, ...datos,
      })
      // Si se editó un turno y le cambiaron la ENTRADA, la clave natural es otra
      // y el guardado creó uno nuevo: el viejo se borra después de que el nuevo
      // está guardado, para que un error no deje a la barista sin turno.
      const previo = editando?.turno
      if (previo && previo.hora_inicio !== datos.hora_inicio) {
        await api.delete(`/horarios/turno/${previo.id}`)
      }
      setEditando(null)
      cargar()
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'No se pudo guardar el turno.')
    } finally { setBusy(false) }
  }

  const borrar = async (turnoId: number) => {
    setBusy(true); setError(null)
    try {
      await api.delete(`/horarios/turno/${turnoId}`)
      cargar()
    } catch { setError('No se pudo borrar el turno.') }
    finally { setBusy(false) }
  }

  const publicar = async () => {
    setBusy(true); setError(null); setAviso(null)
    try {
      const { data: r } = await api.post('/horarios/publicar',
        { tienda_id: tiendaId, lunes: aISO(lunes) })
      setAviso(r.publicados
        ? `Horario enviado: ${r.publicados} turno(s) a ${r.avisados} barista(s).`
        : 'No había turnos nuevos para enviar.')
      cargar()
    } catch { setError('No se pudo enviar el horario.') }
    finally { setBusy(false) }
  }

  const copiarSemanaAnterior = async () => {
    setBusy(true); setError(null); setAviso(null)
    try {
      const { data: r } = await api.post('/horarios/copiar', {
        tienda_id: tiendaId,
        lunes_origen: aISO(sumarDias(lunes, -7)),
        lunes_destino: aISO(lunes),
      })
      setAviso(r.creados
        ? `Se copiaron ${r.creados} turno(s) como borrador. Revisalos y enviá.`
        : 'La semana anterior no tenía turnos para copiar.')
      cargar()
    } catch { setError('No se pudo copiar la semana.') }
    finally { setBusy(false) }
  }

  if (loading && !data) {
    return <p className="text-sm text-warm-400 py-10 text-center animate-pulse">Cargando la semana…</p>
  }
  if (!data) return null

  const rango = `${data.lunes} → ${data.domingo}`

  return (
    <div className="space-y-3">
      {/* ── Barra de semana ── */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1 bg-white border border-warm-200 rounded-xl p-1">
          <button onClick={() => mover(-1)} className="p-1.5 rounded-lg hover:bg-warm-100 text-warm-500">
            <ChevronLeft size={16} />
          </button>
          <span className="text-xs font-mono font-semibold text-warm-700 px-2">{rango}</span>
          <button onClick={() => mover(1)} className="p-1.5 rounded-lg hover:bg-warm-100 text-warm-500">
            <ChevronRight size={16} />
          </button>
        </div>
        <button
          onClick={() => setLunes(lunesDe(new Date()))}
          className="px-3 py-2 rounded-xl text-xs font-semibold bg-white border border-warm-200 text-warm-600 hover:bg-warm-100"
        >
          Esta semana
        </button>
        <button
          onClick={copiarSemanaAnterior}
          disabled={busy}
          className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold bg-white border border-warm-200 text-warm-600 hover:bg-warm-100 disabled:opacity-40"
        >
          <Copy size={14} /> Copiar la semana anterior
        </button>
        <div className="flex-1" />
        <button
          onClick={publicar}
          disabled={busy || !data.hay_borradores}
          className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-semibold bg-forest text-white hover:bg-forest/90 disabled:opacity-40"
        >
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
          Enviar a las baristas
        </button>
      </div>

      <p className="text-xs text-warm-400">
        Jornada máxima cargada para esta semana: <b>{data.jornada_max_semanal} h</b>{' '}
        (vigencia del {data.tasa.vigente_desde}
        {data.tasa.confirmar_contador && ' · sin confirmar con el contador'}).
        Se envían solo los turnos en borrador; los ya enviados no se reenvían.
        Los totales son horas <b>trabajadas</b>: el almuerzo no cuenta.
      </p>

      {error && <Aviso tono="error">{error}</Aviso>}
      {aviso && <Aviso tono="ok">{aviso}</Aviso>}

      {/* ── Grilla ── */}
      <div className="overflow-x-auto">
        <table className="min-w-[900px] w-full border-separate border-spacing-0">
          <thead>
            <tr>
              <th className="text-left text-xs font-bold text-warm-500 px-3 py-2 sticky left-0 bg-warm-50">
                Barista
              </th>
              {data.dias.map(d => (
                <th key={d.fecha} className="text-xs font-bold text-warm-500 px-2 py-2 text-center">
                  {d.nombre}
                  <span className="block font-mono font-normal text-warm-400">
                    {d.fecha.slice(8)}/{d.fecha.slice(5, 7)}
                  </span>
                </th>
              ))}
              <th className="text-xs font-bold text-warm-500 px-3 py-2 text-right">Total</th>
            </tr>
          </thead>
          <tbody>
            {data.baristas.map(b => (
              <FilaBarista
                key={b.usuario_id}
                barista={b}
                dias={data.dias}
                jornada={data.jornada_max_semanal}
                editando={editando}
                setEditando={setEditando}
                onGuardar={guardar}
                onBorrar={borrar}
                busy={busy}
              />
            ))}
          </tbody>
        </table>
      </div>

      {data.baristas.length === 0 && (
        <p className="text-sm text-warm-400 text-center py-8">
          Esta sede no tiene baristas activas cargadas.
        </p>
      )}
    </div>
  )
}

function FilaBarista({
  barista, dias, jornada, editando, setEditando, onGuardar, onBorrar, busy,
}: {
  barista: BaristaSemana
  dias: { fecha: string; nombre: string }[]
  jornada: number
  editando: Edicion | null
  setEditando: (v: Edicion | null) => void
  onGuardar: (usuarioId: number, fecha: string, datos: DatosTurno) => void
  onBorrar: (turnoId: number) => void
  busy: boolean
}) {
  const porFecha = (fecha: string) => barista.turnos.filter(t => t.fecha === fecha)

  return (
    <tr className="align-top">
      <td className="px-3 py-2 sticky left-0 bg-warm-50">
        <p className="text-sm font-semibold text-warm-700 whitespace-nowrap">{barista.nombre}</p>
        {!barista.activa && (
          <span className="text-[10px] text-warm-400">fuera de esta sede</span>
        )}
      </td>

      {dias.map(d => {
        const turnos = porFecha(d.fecha)
        const abierto = editando?.usuarioId === barista.usuario_id && editando?.fecha === d.fecha
        return (
          <td key={d.fecha} className="px-1 py-1">
            <div className="space-y-1">
              {turnos.map(t => (
                <Chip
                  key={t.id}
                  turno={t}
                  onEditar={() => setEditando({
                    usuarioId: barista.usuario_id, fecha: d.fecha, turno: t,
                  })}
                  onBorrar={() => onBorrar(t.id)}
                  busy={busy}
                />
              ))}
              {abierto ? (
                <FormTurno
                  // Remonta al saltar de un turno a otro en la misma celda: si
                  // no, el formulario se queda con los valores del anterior.
                  key={editando?.turno?.id ?? 'nuevo'}
                  turno={editando?.turno}
                  onCancelar={() => setEditando(null)}
                  onGuardar={datos => onGuardar(barista.usuario_id, d.fecha, datos)}
                  busy={busy}
                />
              ) : (
                <button
                  onClick={() => setEditando({ usuarioId: barista.usuario_id, fecha: d.fecha })}
                  className="w-full flex items-center justify-center gap-1 py-1.5 rounded-lg border border-dashed border-warm-200 text-warm-400 hover:text-forest hover:border-forest text-[11px]"
                >
                  <Plus size={12} /> Turno
                </button>
              )}
            </div>
          </td>
        )
      })}

      <td className="px-3 py-2 text-right whitespace-nowrap">
        <span className={`text-sm font-bold font-mono ${
          barista.excede_jornada ? 'text-danger-700' : 'text-warm-700'}`}>
          {fmtHoras(barista.total_horas)}
        </span>
        {barista.minutos_almuerzo > 0 && (
          <span className="block text-[10px] text-warm-400">
            sin {fmtHoras(barista.minutos_almuerzo / 60)} de almuerzo
          </span>
        )}
        {barista.excede_jornada && (
          <span className="flex items-center justify-end gap-1 text-[10px] text-danger-500 font-semibold">
            <AlertTriangle size={11} />
            {fmtHoras(barista.horas_sobre_jornada)} sobre {jornada} h
          </span>
        )}
        {barista.borradores > 0 && (
          <span className="block text-[10px] text-warm-400">
            {barista.borradores} sin enviar
          </span>
        )}
      </td>
    </tr>
  )
}

function Chip({ turno, onEditar, onBorrar, busy }: {
  turno: TurnoProgramado; onEditar: () => void; onBorrar: () => void; busy: boolean
}) {
  const publicado = turno.estado === 'publicado'
  return (
    <div className={`group flex items-center gap-1 rounded-lg px-1.5 py-1 text-[11px] font-mono border ${
      publicado
        ? 'bg-forest-50 border-forest-100 text-forest-700'
        : 'bg-warm-100 border-warm-200 text-warm-600 border-dashed'
    }`}>
      <button
        onClick={onEditar}
        className="flex-1 text-left whitespace-nowrap hover:underline"
        title="Editar el turno o su almuerzo"
      >
        {turno.hora_inicio}–{turno.hora_fin}
        {turno.cruza_medianoche && <span title="Termina al día siguiente">+1</span>}
        {turno.almuerzo_minutos ? (
          // La hora de almuerzo se muestra en la grilla y no escondida en el
          // formulario: es lo que explica por qué el total no es la resta de
          // entrada y salida.
          <span className="block text-[9px] opacity-70">
            🍽 {turno.almuerzo_inicio} · {turno.almuerzo_minutos}′
          </span>
        ) : null}
      </button>
      <button
        onClick={onBorrar}
        disabled={busy}
        className="opacity-0 group-hover:opacity-100 text-warm-400 hover:text-danger-500"
        title="Quitar turno"
      >
        <Trash2 size={11} />
      </button>
    </div>
  )
}

function FormTurno({ turno, onGuardar, onCancelar, busy }: {
  turno?: TurnoProgramado
  onGuardar: (datos: DatosTurno) => void
  onCancelar: () => void
  busy: boolean
}) {
  const [ini, setIni] = useState(turno?.hora_inicio ?? '08:00')
  const [fin, setFin] = useState(turno?.hora_fin ?? '16:00')
  const [almIni, setAlmIni] = useState(turno?.almuerzo_inicio ?? '13:00')
  const [almMin, setAlmMin] = useState(turno?.almuerzo_minutos ?? 0)

  const enviar = () => onGuardar({
    hora_inicio: ini,
    hora_fin: fin,
    // Sin minutos no hay almuerzo: los dos campos viajan en null y el turno se
    // liquida entero. Es el default, y es lo que tienen todos los turnos viejos.
    almuerzo_inicio: almMin > 0 ? almIni : null,
    almuerzo_minutos: almMin > 0 ? almMin : null,
  })

  return (
    <div className="rounded-lg border border-forest-100 bg-white p-1.5 space-y-1">
      <div className="flex items-center gap-1">
        <input
          type="time" value={ini} onChange={e => setIni(e.target.value)}
          list="horas-sugeridas" title="Entrada"
          className="w-full text-[11px] font-mono border border-warm-200 rounded px-1 py-0.5"
        />
        <input
          type="time" value={fin} onChange={e => setFin(e.target.value)}
          list="horas-sugeridas" title="Salida"
          className="w-full text-[11px] font-mono border border-warm-200 rounded px-1 py-0.5"
        />
      </div>
      <datalist id="horas-sugeridas">
        {HORAS_SUGERIDAS.map(h => <option key={h} value={h} />)}
      </datalist>

      <div className="flex items-center gap-1">
        <span className="text-[10px] text-warm-400" title="Almuerzo">🍽</span>
        <select
          value={almMin}
          onChange={e => setAlmMin(Number(e.target.value))}
          title="Cuánto dura el almuerzo"
          className="text-[11px] font-mono border border-warm-200 rounded px-1 py-0.5"
        >
          {MINUTOS_ALMUERZO.map(m => (
            <option key={m} value={m}>{m === 0 ? 'sin' : `${m}′`}</option>
          ))}
        </select>
        {almMin > 0 && (
          <input
            type="time" value={almIni} onChange={e => setAlmIni(e.target.value)}
            title="A qué hora arranca el almuerzo"
            className="flex-1 min-w-0 text-[11px] font-mono border border-warm-200 rounded px-1 py-0.5"
          />
        )}
      </div>

      <div className="flex items-center gap-1">
        <button
          onClick={enviar} disabled={busy}
          className="flex-1 flex items-center justify-center gap-1 py-1 rounded bg-forest text-white text-[11px] font-semibold disabled:opacity-40"
        >
          <Check size={11} /> Poner
        </button>
        <button onClick={onCancelar} className="p-1 rounded text-warm-400 hover:bg-warm-100">
          <X size={12} />
        </button>
      </div>
    </div>
  )
}

export function Aviso({ tono, children }: { tono: 'ok' | 'error' | 'info'; children: React.ReactNode }) {
  const estilos = {
    ok: 'bg-forest-50 border-forest-100 text-forest-700',
    error: 'bg-danger-50 border-danger-200 text-danger-700',
    info: 'bg-warm-100 border-warm-200 text-warm-600',
  }[tono]
  return (
    <div className={`rounded-xl border px-3 py-2 text-xs ${estilos}`}>{children}</div>
  )
}
