import { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import BaristaLayout from '../components/BaristaLayout'
import {
  CheckCircle2, Circle, ChevronLeft, ChevronRight,
  Trash2, ShieldCheck, ToggleLeft, ToggleRight, Plus, Pencil, Check, X,
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

  const deEstaSemana: Record<string, Registro> = {}
  registros.filter(r => r.semana === semana).forEach(r => { deEstaSemana[r.tarea_key] = r })
  const tareasActivas = tareas.filter(t => t.activa)
  const completadas   = tareasActivas.filter(t => deEstaSemana[t.key]).length

  const marcar = async (key: string) => {
    if (!user?.tienda_id || marcando) return
    setMarcando(key)
    try {
      const ahora    = new Date()
      const esHoy    = mes === ahora.getMonth() + 1 && anio === ahora.getFullYear() && semana === semanaDelMes(ahora)
      const dia      = (semana - 1) * 7 + 1
      // Fecha LOCAL: toISOString es UTC y despues de las 19:00 Colombia devuelve manana.
      const isoLocal = (d: Date) =>
        `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
      const fechaEnviar = esHoy ? isoLocal(ahora) : isoLocal(new Date(anio, mes - 1, dia))
      const { data } = await api.post(`/limpieza/${user.tienda_id}/semanal`, { tarea_key: key, fecha: fechaEnviar })
      setRegistros(prev => [...prev, data])
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
                      <button onClick={() => !hecho && !inactiva && marcar(tarea.key)}
                        disabled={hecho || inactiva || marcando === tarea.key}
                        className="shrink-0 mt-0.5 transition-all active:scale-95 disabled:cursor-default">
                        {marcando === tarea.key
                          ? <div className="w-5 h-5 rounded-full border-2 border-forest animate-spin border-t-transparent" />
                          : hecho
                            ? <CheckCircle2 size={20} className="text-forest-500" />
                            : <Circle size={20} className={inactiva ? 'text-warm-200' : 'text-warm-300'} />}
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
          Toca el círculo de una tarea para marcarla como realizada
        </p>
      )}
    </div>
  )

  if (isAdmin) return content

  return (
    <BaristaLayout title="Limpieza semanal" backTo="/">
      {content}
    </BaristaLayout>
  )
}
