import { useEffect, useMemo, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import BaristaLayout from '../components/BaristaLayout'
import { BaristaAvatar } from '../components/BaristaAvatar'
import {
  CheckCircle2, Circle, ChevronLeft, ChevronRight,
  Trash2, ShieldCheck, ToggleLeft, ToggleRight, Plus, Pencil, Check, X, Sparkles,
} from 'lucide-react'

interface Tarea {
  id: number; key: string; label: string; activa: boolean; orden: number
}

interface Registro {
  id: number; tarea_key: string; fecha: string; semana: number
  usuario_nombre: string; usuario_id: number; vobo: boolean
  barista_nombre?: string | null; creado?: string | null
}

const MESES = [
  'Enero','Febrero','Marzo','Abril','Mayo','Junio',
  'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre',
]

function semanaDelMes(d: Date) {
  return Math.floor((d.getDate() - 1) / 7) + 1
}

// Los timestamps se guardan en UTC; parsear como UTC para mostrar hora local Colombia.
const parseUTC = (s: string) => {
  const t = s.replace(' ', 'T').replace('+00:00', 'Z')
  return new Date(t.endsWith('Z') ? t : t + 'Z')
}
const fmtHora = (s: string) => parseUTC(s).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })
const esMismoDiaLocal = (a: Date, b: Date) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()

// Mensaje de aliento según el avance de la semana.
const mensajeMotivador = (hechas: number, total: number) => {
  if (total === 0) return 'Sin tareas configuradas'
  if (hechas === 0) return `¡Arrancá! ${total} tareas te esperan`
  if (hechas === total) return '¡Semana completa! Gran trabajo 🎉'
  const faltan = total - hechas
  if (faltan <= 2) return `¡Ya casi! Falta${faltan > 1 ? 'n' : ''} ${faltan}`
  if (hechas / total < 0.5) return '¡Buen comienzo, seguí así!'
  return `¡Vas muy bien, faltan ${faltan}!`
}

// Anillo de progreso X/total, se llena verde a medida que se marca.
function AnilloProgreso({ hechas, total }: { hechas: number; total: number }) {
  const r = 46, c = 2 * Math.PI * r
  const pct = total ? hechas / total : 0
  const completo = total > 0 && hechas === total
  const color = completo ? 'oklch(55% 0.16 145)' : 'oklch(48% 0.12 155)'
  return (
    <div style={{ position: 'relative', width: 104, height: 104, flexShrink: 0 }}>
      <svg width={104} height={104} viewBox="0 0 104 104">
        <circle cx={52} cy={52} r={r} fill="none" stroke="oklch(90% 0.02 75)" strokeWidth={9} />
        <circle cx={52} cy={52} r={r} fill="none" stroke={color} strokeWidth={9} strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - pct)} transform="rotate(-90 52 52)"
          style={{ transition: 'stroke-dashoffset 500ms ease-out, stroke 300ms' }} />
      </svg>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ fontSize: 38, fontWeight: 800, lineHeight: 1, color: 'oklch(35% 0.06 155)', fontVariantNumeric: 'tabular-nums' }}>{hechas}</span>
        <span style={{ fontSize: 12, color: 'oklch(60% 0.02 75)', fontWeight: 600 }}>/{total}</span>
      </div>
    </div>
  )
}

// Confeti CSS al completar la semana (se respeta prefers-reduced-motion vía index.css).
const CONFETI_COLORES = ['oklch(55% 0.16 145)', 'oklch(48% 0.12 155)', 'oklch(72% 0.15 65)', 'oklch(60% 0.16 25)']
function Confeti() {
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 60, pointerEvents: 'none', overflow: 'hidden' }}>
      {Array.from({ length: 16 }).map((_, i) => (
        <span key={i} className="limpieza-confetti-piece" style={{
          position: 'absolute', top: 0, left: `${(i * 6.2 + 3) % 100}%`,
          width: 8, height: 12, borderRadius: 2, background: CONFETI_COLORES[i % CONFETI_COLORES.length],
          animationDelay: `${(i % 5) * 0.12}s`,
        }} />
      ))}
    </div>
  )
}

export default function Limpieza() {
  const { user } = useAuth()
  const isAdmin = user?.rol === 'admin'

  const hoy = new Date()
  const [mes,    setMes]    = useState(hoy.getMonth() + 1)
  const [anio,   setAnio]   = useState(hoy.getFullYear())
  const [semana, setSemana] = useState(semanaDelMes(hoy))

  const [tareas,    setTareas]    = useState<Tarea[]>([])
  const [registros, setRegistros] = useState<Registro[]>([])
  const [loading,   setLoading]   = useState(false)
  const [marcando,  setMarcando]  = useState<string | null>(null)
  // "¿Quién lo hizo?" — al tocar una tarea, se elige la barista antes de marcar.
  const [baristas,  setBaristas]  = useState<{ id: number; nombre: string }[]>([])
  const [pickKey,   setPickKey]   = useState<string | null>(null)
  const [justCompleted, setJustCompleted] = useState(false)   // dispara la celebración 13/13

  // Admin edit state
  const [editingId,   setEditingId]   = useState<number | null>(null)
  const [editLabel,   setEditLabel]   = useState('')
  const [addingLabel, setAddingLabel] = useState('')
  const [showAdd,     setShowAdd]     = useState(false)
  const [saving,      setSaving]      = useState(false)

  const cargarTareas = async () => {
    if (!user?.tienda_id) return
    try {
      const { data } = await api.get(`/limpieza/${user.tienda_id}/tareas`, {
        params: isAdmin ? { incluir_inactivas: true } : {},
      })
      setTareas(data)
    } catch {}
  }

  const cargarRegistros = async () => {
    if (!user?.tienda_id) return
    setLoading(true)
    try {
      const { data } = await api.get(`/limpieza/${user.tienda_id}/semanal`, { params: { mes, anio } })
      setRegistros(data)
    } catch {
      setRegistros([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { cargarTareas() },    [user?.tienda_id])
  useEffect(() => { cargarRegistros() }, [mes, anio, user?.tienda_id])
  useEffect(() => {
    if (isAdmin) return
    api.get('/auth/baristas').then(({ data }) => setBaristas(data ?? [])).catch(() => {})
  }, [isAdmin])

  const deEstaSemana: Record<string, Registro> = {}
  registros.filter(r => r.semana === semana).forEach(r => { deEstaSemana[r.tarea_key] = r })
  const tareasActivas = tareas.filter(t => t.activa)
  const completadas   = tareasActivas.filter(t => deEstaSemana[t.key]).length

  // Progreso por semana (para la tira de 4 semanas) + equipo de la semana / de hoy.
  const regsPorSemana = useMemo(() => {
    const w: Record<number, Record<string, Registro>> = { 1: {}, 2: {}, 3: {}, 4: {} }
    registros.forEach(r => { const s = Math.min(r.semana || 1, 4); w[s][r.tarea_key] = r })
    return w
  }, [registros])
  const hechasSemana = (s: number) => tareasActivas.filter(t => regsPorSemana[s]?.[t.key]).length
  const equipoSemana = Array.from(new Set(registros.filter(r => r.semana === semana).map(r => r.barista_nombre || r.usuario_nombre)))
  const hoyTeam = registros.filter(r => r.semana === semana && r.creado && esMismoDiaLocal(parseUTC(r.creado), new Date()))
  const hoyEquipo = Array.from(new Set(hoyTeam.map(r => r.barista_nombre || r.usuario_nombre)))

  const marcar = async (key: string, barista?: { id: number; nombre: string }) => {
    if (!user?.tienda_id || marcando) return
    const antes = completadas   // conteo de la semana visible ANTES de este marcado
    setMarcando(key); setPickKey(null)
    try {
      const ahora    = new Date()
      const esHoy    = mes === ahora.getMonth() + 1 && anio === ahora.getFullYear() && semana === semanaDelMes(ahora)
      const dia      = (semana - 1) * 7 + 1
      // Fecha LOCAL: toISOString es UTC y despues de las 19:00 Colombia devuelve manana.
      const isoLocal = (d: Date) =>
        `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
      const fechaEnviar = esHoy ? isoLocal(ahora) : isoLocal(new Date(anio, mes - 1, dia))
      const body: Record<string, unknown> = { tarea_key: key, fecha: fechaEnviar }
      if (barista) { body.barista_id = barista.id; body.barista_nombre = barista.nombre }
      const { data } = await api.post(`/limpieza/${user.tienda_id}/semanal`, body)
      setRegistros(prev => [...prev, data])
      // ¿Este marcado cerró la semana? (transición total-1 → total) → celebración.
      if (tareasActivas.length > 0 && antes + 1 === tareasActivas.length) {
        setJustCompleted(true)
        setTimeout(() => setJustCompleted(false), 3600)
      }
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Error al registrar tarea')
    } finally {
      setMarcando(null)
    }
  }

  const eliminar = async (reg: Registro) => {
    if (!user?.tienda_id || !confirm('¿Eliminar este registro?')) return
    try {
      await api.delete(`/limpieza/${user.tienda_id}/semanal/${reg.id}`)
      setRegistros(prev => prev.filter(r => r.id !== reg.id))
    } catch (e: any) { alert(e.response?.data?.detail || 'Error al eliminar') }
  }

  const toggleVobo = async (reg: Registro) => {
    if (!user?.tienda_id) return
    try {
      await api.patch(`/limpieza/${user.tienda_id}/semanal/${reg.id}/vobo`, { valor: !reg.vobo })
      setRegistros(prev => prev.map(r => r.id === reg.id ? { ...r, vobo: !r.vobo } : r))
    } catch { alert('Error al actualizar VoBo') }
  }

  // ── Admin: toggle activa ────────────────────────────────────────────────────
  const toggleActiva = async (tarea: Tarea) => {
    if (!user?.tienda_id) return
    try {
      const { data } = await api.patch(`/limpieza/${user.tienda_id}/tareas/${tarea.id}`, { activa: !tarea.activa })
      setTareas(prev => prev.map(t => t.id === tarea.id ? { ...t, activa: data.activa } : t))
    } catch { alert('Error al actualizar tarea') }
  }

  // ── Admin: rename ───────────────────────────────────────────────────────────
  const startEdit = (tarea: Tarea) => { setEditingId(tarea.id); setEditLabel(tarea.label) }

  const saveEdit = async () => {
    if (!user?.tienda_id || editingId === null || !editLabel.trim()) return
    setSaving(true)
    try {
      const { data } = await api.patch(`/limpieza/${user.tienda_id}/tareas/${editingId}`, { label: editLabel.trim() })
      setTareas(prev => prev.map(t => t.id === editingId ? { ...t, label: data.label } : t))
      setEditingId(null)
    } catch { alert('Error al guardar') }
    finally { setSaving(false) }
  }

  // ── Admin: nueva tarea ──────────────────────────────────────────────────────
  const addTarea = async () => {
    if (!user?.tienda_id || !addingLabel.trim()) return
    setSaving(true)
    try {
      const { data } = await api.post(`/limpieza/${user.tienda_id}/tareas`, { label: addingLabel.trim() })
      setTareas(prev => [...prev, data])
      setAddingLabel('')
      setShowAdd(false)
    } catch (e: any) { alert(e.response?.data?.detail || 'Error al agregar') }
    finally { setSaving(false) }
  }

  const prevMes = () => { if (mes === 1) { setMes(12); setAnio(a => a - 1) } else setMes(m => m - 1); setSemana(1) }
  const nextMes = () => { if (mes === 12) { setMes(1); setAnio(a => a + 1) } else setMes(m => m + 1); setSemana(1) }

  const content = (
    <div className="space-y-4 pb-10">
      {/* Month nav */}
      <div className="flex items-center justify-between">
        <button onClick={prevMes} className="p-2 rounded-lg hover:bg-warm-100 transition-colors">
          <ChevronLeft size={18} className="text-warm-600" />
        </button>
        <div className="text-center">
          <p className="text-base font-bold text-warm-700 capitalize">{MESES[mes - 1]} {anio}</p>
          <p className="text-xs text-warm-400">{completadas} / {tareasActivas.length} tareas esta semana</p>
        </div>
        <button onClick={nextMes} className="p-2 rounded-lg hover:bg-warm-100 transition-colors">
          <ChevronRight size={18} className="text-warm-600" />
        </button>
      </div>

      {/* Week selector */}
      <div className="flex gap-2">
        {[1, 2, 3, 4].map(s => (
          <button key={s} onClick={() => setSemana(s)}
            className="flex-1 py-2 rounded-xl text-xs font-semibold transition-all"
            style={{
              background: semana === s ? 'oklch(35% 0.05 155)' : 'oklch(96% 0.008 75)',
              color: semana === s ? 'white' : 'oklch(40% 0.01 60)',
            }}>
            Semana {s}
          </button>
        ))}
      </div>

      {/* Progress bar */}
      <div className="w-full bg-warm-200 rounded-full h-1.5">
        <div className="h-1.5 rounded-full transition-all"
          style={{ width: `${tareasActivas.length ? (completadas / tareasActivas.length) * 100 : 0}%`, background: 'oklch(48% 0.12 155)' }} />
      </div>

      {/* Task list */}
      {loading ? (
        <p className="text-sm text-warm-400 text-center py-8 animate-pulse">Cargando...</p>
      ) : (
        <div className="bg-white rounded-2xl border border-warm-200 overflow-hidden">
          <div className="divide-y divide-warm-100">
            {tareas.map((tarea, i) => {
              const reg           = deEstaSemana[tarea.key]
              const hecho         = !!reg && tarea.activa
              const inactiva      = !tarea.activa
              const puedoEliminar = reg && (reg.usuario_id === user?.user_id || isAdmin)
              const isEditing     = editingId === tarea.id

              return (
                <div key={tarea.id}
                  className="px-4 py-3.5 transition-colors"
                  style={{ background: inactiva ? 'oklch(97% 0.003 75)' : hecho ? 'oklch(97% 0.025 155)' : undefined }}>
                  <div className="flex items-start gap-3">

                    {/* Status icon (baristas) / Toggle (admin) */}
                    {isAdmin ? (
                      <button onClick={() => toggleActiva(tarea)} className="shrink-0 mt-0.5">
                        {tarea.activa
                          ? <ToggleRight size={20} className="text-forest-500" />
                          : <ToggleLeft  size={20} className="text-warm-300" />}
                      </button>
                    ) : (
                      <button onClick={() => !hecho && !inactiva && setPickKey(pickKey === tarea.key ? null : tarea.key)}
                        disabled={hecho || inactiva || marcando === tarea.key}
                        className="shrink-0 mt-0.5 transition-all active:scale-95 disabled:cursor-default">
                        {marcando === tarea.key
                          ? <div className="w-5 h-5 rounded-full border-2 border-forest animate-spin border-t-transparent" />
                          : hecho
                            ? <CheckCircle2 size={20} className="text-forest-500" />
                            : <Circle size={20} className={inactiva ? 'text-warm-200' : (pickKey === tarea.key ? 'text-forest-500' : 'text-warm-300')} />}
                      </button>
                    )}

                    {/* Label / inline edit */}
                    <div className="flex-1 min-w-0">
                      {isEditing ? (
                        <div className="flex items-center gap-2">
                          <input
                            autoFocus
                            value={editLabel}
                            onChange={e => setEditLabel(e.target.value)}
                            onKeyDown={e => { if (e.key === 'Enter') saveEdit(); if (e.key === 'Escape') setEditingId(null) }}
                            className="flex-1 text-sm border border-warm-300 rounded-lg px-2 py-1 outline-none focus:border-forest"
                          />
                          <button onClick={saveEdit} disabled={saving} className="p-1 text-forest-600 hover:text-forest-700"><Check size={14} /></button>
                          <button onClick={() => setEditingId(null)} className="p-1 text-warm-400 hover:text-warm-600"><X size={14} /></button>
                        </div>
                      ) : (
                        <>
                          <p className={`text-sm leading-snug ${inactiva ? 'text-warm-300 line-through' : hecho ? 'text-warm-700 font-medium' : 'text-warm-500'}`}>
                            <span className="text-[10px] font-bold text-warm-300 mr-1.5">{String(i + 1).padStart(2, '0')}</span>
                            {tarea.label}
                            {inactiva && <span className="ml-2 text-[10px] text-warm-300 font-semibold normal-case no-underline">(inactiva)</span>}
                          </p>
                          {hecho && (
                            <p className="text-xs text-forest mt-0.5">
                              <span className="font-semibold">{reg.barista_nombre || reg.usuario_nombre}</span>
                              {' · '}{new Date(reg.fecha).toLocaleDateString('es-CO', { day: 'numeric', month: 'short' })}
                              {reg.creado && <span className="text-warm-400"> · {fmtHora(reg.creado)}</span>}
                              {reg.vobo && (
                                <span className="ml-2 inline-flex items-center gap-0.5 text-forest-500 font-semibold">
                                  <ShieldCheck size={11} /> VoBo
                                </span>
                              )}
                            </p>
                          )}
                          {/* Selector "¿Quién lo hizo?" — se abre al tocar la tarea pendiente */}
                          {!hecho && !inactiva && pickKey === tarea.key && (
                            <div className="mt-2 rounded-xl p-2.5" style={{ background: 'oklch(97% 0.02 155)', border: '1px solid oklch(88% 0.05 155)' }}>
                              <p className="text-[11px] font-bold text-forest-700 mb-1.5">¿Quién lo hizo?</p>
                              {baristas.length === 0 ? (
                                <p className="text-[11px] text-warm-500">No hay baristas cargadas.</p>
                              ) : (
                                <div className="flex flex-wrap gap-1.5">
                                  {baristas.map(b => (
                                    <button key={b.id} onClick={() => marcar(tarea.key, b)}
                                      className="px-3 py-1.5 rounded-lg text-xs font-semibold text-white transition-colors active:scale-95"
                                      style={{ background: 'oklch(48% 0.12 155)' }}>
                                      {b.nombre}
                                    </button>
                                  ))}
                                  <button onClick={() => setPickKey(null)}
                                    className="px-2.5 py-1.5 rounded-lg text-xs font-semibold text-warm-500 border border-warm-200">
                                    Cancelar
                                  </button>
                                </div>
                              )}
                            </div>
                          )}
                        </>
                      )}
                    </div>

                    {/* Actions */}
                    {!isEditing && (
                      <div className="flex items-center gap-1.5 shrink-0">
                        {isAdmin && (
                          <button onClick={() => startEdit(tarea)}
                            className="p-1.5 rounded-lg text-warm-300 hover:text-warm-600 hover:bg-warm-100 transition-colors">
                            <Pencil size={13} />
                          </button>
                        )}
                        {isAdmin && hecho && (
                          <button onClick={() => toggleVobo(reg)}
                            className="p-1.5 rounded-lg transition-colors"
                            style={{
                              background: reg.vobo ? 'oklch(90% 0.025 155)' : 'oklch(92% 0.006 75)',
                              color:      reg.vobo ? 'oklch(35% 0.05 155)'  : 'oklch(58% 0.01 60)',
                            }}>
                            <ShieldCheck size={14} />
                          </button>
                        )}
                        {puedoEliminar && (
                          <button onClick={() => eliminar(reg)}
                            className="p-1.5 rounded-lg text-warm-300 hover:text-red-500 hover:bg-red-50 transition-colors">
                            <Trash2 size={14} />
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Admin: agregar tarea */}
      {isAdmin && (
        showAdd ? (
          <div className="flex gap-2">
            <input
              autoFocus
              placeholder="Nombre de la nueva tarea..."
              value={addingLabel}
              onChange={e => setAddingLabel(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') addTarea(); if (e.key === 'Escape') setShowAdd(false) }}
              className="flex-1 text-sm border border-warm-300 rounded-xl px-3 py-2.5 outline-none focus:border-forest"
            />
            <button onClick={addTarea} disabled={saving || !addingLabel.trim()}
              className="px-4 py-2.5 rounded-xl text-sm font-semibold text-white disabled:opacity-40"
              style={{ background: 'oklch(48% 0.12 155)' }}>
              Agregar
            </button>
            <button onClick={() => { setShowAdd(false); setAddingLabel('') }}
              className="px-3 py-2.5 rounded-xl text-sm text-warm-500 border border-warm-200">
              <X size={16} />
            </button>
          </div>
        ) : (
          <button onClick={() => setShowAdd(true)}
            className="w-full flex items-center justify-center gap-2 py-3 rounded-xl text-sm font-semibold border border-dashed border-warm-300 text-warm-500 hover:border-forest-400 hover:text-forest-600 transition-colors">
            <Plus size={15} /> Agregar tarea personalizada
          </button>
        )
      )}

      {!isAdmin && (
        <p className="text-xs text-warm-400 text-center">
          Tocá el círculo de una tarea y elegí quién la hizo para marcarla
        </p>
      )}
    </div>
  )

  if (isAdmin) return content

  // ── Vista de la BARISTA: visual + motivadora ──────────────────────────────
  const contentBarista = (
    <div className="space-y-4 pb-10">
      {/* Nav mes */}
      <div className="flex items-center justify-between">
        <button onClick={prevMes} className="p-2 rounded-lg hover:bg-warm-100 transition-colors"><ChevronLeft size={18} className="text-warm-600" /></button>
        <p className="text-base font-bold text-warm-700 capitalize">{MESES[mes - 1]} {anio}</p>
        <button onClick={nextMes} className="p-2 rounded-lg hover:bg-warm-100 transition-colors"><ChevronRight size={18} className="text-warm-600" /></button>
      </div>

      {/* HERO: anillo de progreso + aliento + equipo de la semana */}
      <div className="rounded-3xl border border-warm-200 p-5 flex flex-col sm:flex-row items-center gap-4"
        style={{ background: tareasActivas.length > 0 && completadas === tareasActivas.length ? 'oklch(97% 0.025 155)' : '#fff' }}>
        <AnilloProgreso hechas={completadas} total={tareasActivas.length} />
        <div className="flex-1 text-center sm:text-left">
          <p className="text-base font-bold text-warm-700">Semana {semana}</p>
          <p className="text-sm font-bold mt-0.5" style={{ color: tareasActivas.length > 0 && completadas === tareasActivas.length ? 'oklch(40% 0.13 145)' : 'oklch(45% 0.1 155)' }}>
            {mensajeMotivador(completadas, tareasActivas.length)}
          </p>
          {equipoSemana.length > 0 && (
            <div className="flex items-center mt-2.5 justify-center sm:justify-start">
              {equipoSemana.slice(0, 6).map((n, i) => <span key={i} style={{ marginLeft: i ? -6 : 0 }}><BaristaAvatar nombre={n} size={24} /></span>)}
              {equipoSemana.length > 6 && <span className="text-[11px] text-warm-400 ml-1.5">+{equipoSemana.length - 6}</span>}
            </div>
          )}
        </div>
      </div>

      {/* Tira del mes: 4 semanas con progreso, y selector */}
      <div className="flex gap-2">
        {[1, 2, 3, 4].map(s => {
          const hs = hechasSemana(s), tot = tareasActivas.length
          const completa = tot > 0 && hs === tot
          const esHoySem = mes === hoy.getMonth() + 1 && anio === hoy.getFullYear() && s === semanaDelMes(hoy)
          const activa = semana === s
          return (
            <button key={s} onClick={() => setSemana(s)} className="flex-1 rounded-xl px-2 py-2 transition-all"
              style={{ background: activa ? 'oklch(98% 0.012 155)' : 'oklch(97% 0.006 75)',
                boxShadow: activa ? 'inset 0 0 0 2px oklch(48% 0.12 155)' : 'inset 0 0 0 1px oklch(90% 0.006 75)' }}>
              <p className="text-[11px] font-bold" style={{ color: 'oklch(40% 0.02 60)' }}>S{s}{esHoySem ? ' · hoy' : ''}</p>
              <div className="my-1 rounded-full overflow-hidden" style={{ height: 5, background: 'oklch(90% 0.02 75)' }}>
                <div style={{ height: '100%', width: `${tot ? (hs / tot) * 100 : 0}%`, background: completa ? 'oklch(55% 0.16 145)' : hs > 0 ? 'oklch(72% 0.15 65)' : 'oklch(90% 0.02 75)', transition: 'width 300ms' }} />
              </div>
              <p className="text-[10px] font-bold tabular-nums" style={{ color: 'oklch(58% 0.02 75)' }}>{hs}/{tot}</p>
            </button>
          )
        })}
      </div>

      {/* Banda de hoy: el equipo ya marcó N (refuerzo positivo, nunca culpa) */}
      {hoyTeam.length > 0 && (
        <div className="rounded-2xl px-4 py-3 flex items-center gap-3" style={{ background: 'oklch(97% 0.025 155)', border: '1px solid oklch(88% 0.05 155)' }}>
          <div className="flex items-center">
            {hoyEquipo.slice(0, 4).map((n, i) => <span key={i} style={{ marginLeft: i ? -6 : 0 }}><BaristaAvatar nombre={n} size={30} /></span>)}
          </div>
          <p className="text-sm font-bold" style={{ color: 'oklch(35% 0.08 155)' }}>Hoy se marcaron {hoyTeam.length} tarea{hoyTeam.length > 1 ? 's' : ''}. ¡Gracias!</p>
        </div>
      )}

      {/* Lista de tareas (tarjetas tocables) */}
      {loading ? (
        <p className="text-sm text-warm-400 text-center py-8 animate-pulse">Cargando...</p>
      ) : (
        <div className="space-y-2">
          {tareasActivas.map((tarea, i) => {
            const reg = deEstaSemana[tarea.key]
            const hecho = !!reg
            const quien = reg ? (reg.barista_nombre || reg.usuario_nombre) : null
            const puedoEliminar = reg && reg.usuario_id === user?.user_id
            const abierto = pickKey === tarea.key
            const cargando = marcando === tarea.key
            return (
              <div key={tarea.id} className="rounded-2xl border transition-colors"
                style={{ background: hecho ? 'oklch(97% 0.025 155)' : '#fff',
                  borderColor: hecho ? 'oklch(88% 0.05 155)' : 'oklch(90% 0.006 75)',
                  borderLeft: hecho ? '4px solid oklch(55% 0.16 145)' : undefined }}>
                <div onClick={() => { if (!hecho && !cargando) setPickKey(abierto ? null : tarea.key) }}
                  className="flex items-center gap-3 px-4 py-3" style={{ minHeight: 58, cursor: hecho ? 'default' : 'pointer' }}>
                  <span className="shrink-0 flex items-center justify-center" style={{ minWidth: 40, minHeight: 40 }}>
                    {cargando
                      ? <div className="w-6 h-6 rounded-full border-2 border-forest animate-spin border-t-transparent" />
                      : hecho
                        ? <span className="limpieza-pop"><BaristaAvatar nombre={quien!} size={30} /></span>
                        : <Circle size={26} className={abierto ? 'text-forest-500' : 'text-warm-300'} />}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className={`text-sm leading-snug ${hecho ? 'text-warm-700 font-medium' : 'text-warm-600'}`}>
                      <span className="text-[10px] font-bold text-warm-300 mr-1.5">{String(i + 1).padStart(2, '0')}</span>{tarea.label}
                    </p>
                    {hecho && (
                      <p className="text-xs text-forest mt-0.5">
                        <span className="font-semibold">{quien}</span>
                        {' · '}{new Date(reg.fecha).toLocaleDateString('es-CO', { day: 'numeric', month: 'short' })}
                        {reg.creado && <span className="text-warm-400"> · {fmtHora(reg.creado)}</span>}
                        {reg.vobo && <span className="ml-2 inline-flex items-center gap-0.5 text-forest-500 font-semibold"><ShieldCheck size={11} /> VoBo</span>}
                      </p>
                    )}
                  </div>
                  {!hecho && !abierto && <span className="text-[11px] font-semibold text-warm-400 shrink-0">marcar ›</span>}
                  {puedoEliminar && (
                    <button onClick={e => { e.stopPropagation(); eliminar(reg) }}
                      className="p-1.5 rounded-lg text-warm-300 hover:text-red-500 hover:bg-red-50 transition-colors shrink-0"><Trash2 size={14} /></button>
                  )}
                </div>
                {!hecho && abierto && (
                  <div className="px-4 pb-3">
                    <div className="rounded-xl p-2.5" style={{ background: 'oklch(97% 0.02 155)', border: '1px solid oklch(88% 0.05 155)' }}>
                      <p className="text-[11px] font-bold text-forest-700 mb-1.5">¿Quién lo hizo?</p>
                      {baristas.length === 0 ? (
                        <p className="text-[11px] text-warm-500">No hay baristas cargadas.</p>
                      ) : (
                        <div className="flex flex-wrap gap-1.5">
                          {baristas.map(b => (
                            <button key={b.id} onClick={() => marcar(tarea.key, b)}
                              className="flex items-center gap-1.5 pl-1.5 pr-3 rounded-lg text-xs font-semibold text-white active:scale-95"
                              style={{ background: 'oklch(48% 0.12 155)', minHeight: 40 }}>
                              <BaristaAvatar nombre={b.nombre} size={24} /> {b.nombre}
                            </button>
                          ))}
                          <button onClick={() => setPickKey(null)}
                            className="px-3 rounded-lg text-xs font-semibold text-warm-500 border border-warm-200" style={{ minHeight: 40 }}>
                            Cancelar
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      <p className="text-xs text-warm-400 text-center">Tocá una tarea y elegí quién la hizo para marcarla</p>
    </div>
  )

  return (
    <BaristaLayout title="Limpieza semanal" backTo="/">
      {contentBarista}
      {justCompleted && (
        <>
          <Confeti />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-6" style={{ pointerEvents: 'none' }}>
            <div className="limpieza-pop rounded-3xl px-7 py-6 text-center" style={{ background: '#fff', boxShadow: '0 24px 60px -20px rgba(28,55,42,.55)', border: '1px solid oklch(88% 0.05 155)' }}>
              <Sparkles size={32} style={{ color: 'oklch(55% 0.16 145)', margin: '0 auto' }} />
              <p className="text-lg font-extrabold mt-1.5" style={{ color: 'oklch(35% 0.1 145)' }}>¡Semana completa!</p>
              <p className="text-sm text-warm-500 mt-0.5">Gran trabajo, equipo 🎉</p>
            </div>
          </div>
        </>
      )}
    </BaristaLayout>
  )
}
