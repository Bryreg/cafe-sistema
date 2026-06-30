import { useEffect, useState } from 'react'
import api from '../api/client'
import { useAuth } from '../contexts/AuthContext'
import { estadoPush, activarPush, desactivarPush, type EstadoPush } from '../lib/push'
import {
  Bell, Smartphone, Check, Save, Send, BellOff, AlertTriangle, Loader2,
} from 'lucide-react'

// ─── Tipos ────────────────────────────────────────────────────────────────────
interface Regla {
  id: number
  tipo: string
  label: string
  descripcion: string
  unidad: string
  umbral: number
  activa: boolean
  canal_bell: boolean
  canal_push: boolean
  nivel: string
}

const fmtNum = (v: number) => (v || 0).toLocaleString('es-CO')

// ─── Toggle ─────────────────────────────────────────────────────────────────
function Switch({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors ${
        checked ? 'bg-forest' : 'bg-gray-300'
      }`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
          checked ? 'translate-x-6' : 'translate-x-1'
        }`}
      />
    </button>
  )
}

// ─── Checkbox de canal ────────────────────────────────────────────────────────
function CanalCheck({
  checked, onChange, Icon, label,
}: { checked: boolean; onChange: (v: boolean) => void; Icon: typeof Bell; label: string }) {
  return (
    <label className="flex items-center gap-1.5 cursor-pointer select-none">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 rounded border-gray-300 text-forest focus:ring-forest"
      />
      <Icon size={14} className="text-gray-400" />
      <span className="text-xs font-medium text-gray-600">{label}</span>
    </label>
  )
}

// ─── Página ───────────────────────────────────────────────────────────────────
export default function NotificacionesConfig() {
  const { user } = useAuth()
  const tiendaId = user?.tienda_id ?? null

  const [reglas, setReglas] = useState<Regla[]>([])
  const [loading, setLoading] = useState(true)
  const [guardando, setGuardando] = useState(false)
  const [guardado, setGuardado] = useState(false)

  // Estado del canal push en este dispositivo
  const [estado, setEstado] = useState<EstadoPush | null>(null)
  const [pushBusy, setPushBusy] = useState(false)
  const [pushError, setPushError] = useState<string | null>(null)
  const [pruebaMsg, setPruebaMsg] = useState<string | null>(null)

  // ── Carga de reglas ──
  useEffect(() => {
    if (!tiendaId) return
    setLoading(true)
    api.get<Regla[]>(`/notificaciones/reglas/${tiendaId}`)
      .then((r) => setReglas(r.data))
      .catch(() => setReglas([]))
      .finally(() => setLoading(false))
  }, [tiendaId])

  // ── Estado push ──
  useEffect(() => {
    estadoPush().then(setEstado).catch(() => setEstado('unsupported'))
  }, [])

  const patchRegla = (id: number, cambios: Partial<Regla>) => {
    setReglas((prev) => prev.map((r) => (r.id === id ? { ...r, ...cambios } : r)))
    setGuardado(false)
  }

  const guardar = async () => {
    if (!tiendaId) return
    setGuardando(true)
    setGuardado(false)
    try {
      const { data } = await api.put<Regla[]>(`/notificaciones/reglas/${tiendaId}`, reglas)
      setReglas(data)
      setGuardado(true)
    } catch {
      // dejar el estado actual; el usuario puede reintentar
    } finally {
      setGuardando(false)
    }
  }

  // ── Acciones push ──
  const handleActivar = async () => {
    if (!tiendaId) return
    setPushBusy(true)
    setPushError(null)
    setPruebaMsg(null)
    try {
      const nuevo = await activarPush(tiendaId)
      setEstado(nuevo)
    } catch (e) {
      setPushError(e instanceof Error ? e.message : 'No se pudo activar el push.')
    } finally {
      setPushBusy(false)
    }
  }

  const handleDesactivar = async () => {
    setPushBusy(true)
    setPushError(null)
    setPruebaMsg(null)
    try {
      await desactivarPush()
      setEstado('default')
    } catch (e) {
      setPushError(e instanceof Error ? e.message : 'No se pudo desactivar el push.')
    } finally {
      setPushBusy(false)
    }
  }

  const handlePrueba = async () => {
    if (!tiendaId) return
    setPushBusy(true)
    setPruebaMsg(null)
    setPushError(null)
    try {
      const { data } = await api.post(`/notificaciones/push/test/${tiendaId}`)
      if (data.push_habilitado === false) {
        setPushError('Push no configurado en el servidor (falta VAPID_PRIVATE_KEY).')
      } else {
        setPruebaMsg(`Prueba enviada · ${data.enviados ?? 0} dispositivo(s)`)
      }
    } catch {
      setPushError('No se pudo enviar la prueba.')
    } finally {
      setPushBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-2">
        <Bell size={20} className="text-forest" />
        <h1 className="text-lg font-bold text-gray-800">Notificaciones</h1>
      </div>

      {/* ── Avisos push en este dispositivo ── */}
      <div className="bg-white rounded-2xl border border-gray-200 p-4">
        <div className="flex items-center gap-2 mb-1">
          <Smartphone size={16} className="text-forest" />
          <p className="text-sm font-bold text-gray-800">Avisos push en este dispositivo</p>
        </div>
        <p className="text-xs text-gray-400 mb-3">
          Recibí alertas en el celular aunque no tengas la app abierta. Activá el push una vez por
          dispositivo.
        </p>

        {estado === null && (
          <p className="text-sm text-gray-400 animate-pulse">Revisando estado…</p>
        )}

        {estado === 'unsupported' && (
          <div className="flex items-start gap-2 rounded-xl bg-amber-50 border border-amber-200 px-3 py-2.5">
            <AlertTriangle size={16} className="text-amber-500 shrink-0 mt-0.5" />
            <p className="text-xs text-amber-700">
              Este navegador no soporta notificaciones push. En iPhone, primero instalá la app en la
              pantalla de inicio (Compartir → “Agregar a inicio”) y abrila desde ahí.
            </p>
          </div>
        )}

        {estado === 'denied' && (
          <div className="flex items-start gap-2 rounded-xl bg-danger-50 border border-danger-200 px-3 py-2.5">
            <BellOff size={16} className="text-danger-500 shrink-0 mt-0.5" />
            <p className="text-xs text-danger-600">
              Bloqueaste las notificaciones. Habilitalas desde los ajustes del navegador para este
              sitio y volvé a intentar.
            </p>
          </div>
        )}

        {estado === 'default' && (
          <button
            onClick={handleActivar}
            disabled={pushBusy}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm font-semibold bg-forest hover:bg-forest/90 disabled:opacity-40 text-white transition-colors"
          >
            {pushBusy ? <Loader2 size={14} className="animate-spin" /> : <Bell size={14} />}
            Activar push en este dispositivo
          </button>
        )}

        {estado === 'suscrito' && (
          <div className="space-y-3">
            <div className="flex items-center gap-1.5 text-sm font-semibold text-forest">
              <Check size={16} /> Push activo en este dispositivo
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={handlePrueba}
                disabled={pushBusy}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold bg-white border border-gray-200 hover:bg-gray-50 disabled:opacity-40 text-gray-600 transition-colors"
              >
                {pushBusy ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                Enviar prueba
              </button>
              <button
                onClick={handleDesactivar}
                disabled={pushBusy}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold bg-white border border-gray-200 hover:bg-gray-50 disabled:opacity-40 text-danger-500 transition-colors"
              >
                <BellOff size={14} /> Desactivar
              </button>
            </div>
          </div>
        )}

        {pushError && <p className="text-xs text-danger-500 mt-2">{pushError}</p>}
        {pruebaMsg && <p className="text-xs text-forest mt-2 font-medium">{pruebaMsg}</p>}
      </div>

      {/* ── Reglas de notificación ── */}
      {loading && (
        <p className="text-sm text-gray-400 text-center py-8 animate-pulse">Cargando reglas…</p>
      )}

      {!loading && reglas.length === 0 && (
        <div className="bg-white border border-gray-200 rounded-2xl px-4 py-12 text-center">
          <Bell size={28} className="text-gray-300 mx-auto mb-2" />
          <p className="text-sm text-gray-500">No hay reglas de notificación configurables.</p>
        </div>
      )}

      {!loading && reglas.length > 0 && (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {reglas.map((regla) => (
              <div key={regla.id} className="bg-white rounded-2xl border border-gray-200 p-4">
                <div className="flex items-start justify-between gap-3 mb-3">
                  <div>
                    <p className="text-sm font-bold text-gray-800">{regla.label}</p>
                    <p className="text-xs text-gray-400 mt-0.5">{regla.descripcion}</p>
                  </div>
                  <Switch
                    checked={regla.activa}
                    onChange={(v) => patchRegla(regla.id, { activa: v })}
                  />
                </div>

                {regla.unidad === '$' && (
                  <div className="flex items-center gap-2 mb-3">
                    <span className="text-xs font-medium text-gray-500">Umbral</span>
                    <div className="relative">
                      <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-sm text-gray-400">
                        $
                      </span>
                      <input
                        type="text"
                        inputMode="numeric"
                        value={fmtNum(regla.umbral)}
                        onChange={(e) => {
                          const raw = Number(e.target.value.replace(/[^\d]/g, '')) || 0
                          patchRegla(regla.id, { umbral: raw })
                        }}
                        className="w-32 border border-gray-200 rounded-lg pl-6 pr-2 py-1.5 text-sm font-mono text-right bg-white focus:outline-none focus:ring-1 focus:ring-forest"
                      />
                    </div>
                  </div>
                )}

                <div className="flex items-center gap-4 pt-2 border-t border-gray-50">
                  <CanalCheck
                    checked={regla.canal_bell}
                    onChange={(v) => patchRegla(regla.id, { canal_bell: v })}
                    Icon={Bell}
                    label="Campana"
                  />
                  <CanalCheck
                    checked={regla.canal_push}
                    onChange={(v) => patchRegla(regla.id, { canal_push: v })}
                    Icon={Smartphone}
                    label="Push al celular"
                  />
                </div>
              </div>
            ))}
          </div>

          {/* Guardar */}
          <div className="flex items-center gap-3">
            <button
              onClick={guardar}
              disabled={guardando}
              className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-semibold bg-forest hover:bg-forest/90 disabled:opacity-40 text-white transition-colors"
            >
              {guardando ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              Guardar cambios
            </button>
            {guardado && (
              <span className="flex items-center gap-1 text-sm text-forest font-medium">
                <Check size={14} /> Cambios guardados
              </span>
            )}
          </div>
        </>
      )}
    </div>
  )
}
