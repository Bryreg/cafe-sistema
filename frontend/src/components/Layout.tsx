import { useState, useEffect, useRef } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import {
  Coffee, LogOut, Bell, Menu, X, CheckCheck,
} from 'lucide-react'
import { NAV_ADMIN } from '../constants/nav'

// ─── Notificaciones ──────────────────────────────────────────────────────────
interface Notif {
  id: number; tipo: string; mensaje: string
  nivel: 'info' | 'advertencia' | 'critico'
  leida: boolean; fecha: string
}

const NIVEL_CFG = {
  critico:     { dot: 'bg-red-500',    text: 'text-red-700',    bg: 'bg-red-50'    },
  advertencia: { dot: 'bg-amber-500',  text: 'text-amber-700',  bg: 'bg-amber-50'  },
  info:        { dot: 'bg-blue-400',   text: 'text-blue-700',   bg: 'bg-blue-50'   },
}

function fmtFecha(iso: string) {
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z')
  return d.toLocaleDateString('es-CO', { day: 'numeric', month: 'short' })
    + ' ' + d.toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })
}

function NotifBell({ tiendaId }: { tiendaId: number }) {
  const [notifs, setNotifs] = useState<Notif[]>([])
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  const unread = notifs.filter(n => !n.leida).length

  const fetchNotifs = () => {
    api.get(`/notificaciones/${tiendaId}`)
      .then(r => setNotifs(r.data))
      .catch(e => console.error('Error al cargar notificaciones:', e))
  }

  useEffect(() => {
    fetchNotifs()
    const t = setInterval(fetchNotifs, 60_000)
    return () => clearInterval(t)
  }, [tiendaId])

  // cerrar al click fuera
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const marcarTodas = () => {
    api.patch(`/notificaciones/${tiendaId}/leer-todas`)
      .then(() => setNotifs(prev => prev.map(n => ({ ...n, leida: true }))))
      .catch(e => console.error('Error al marcar notificaciones:', e))
  }

  const marcarUna = (id: number) => {
    api.patch(`/notificaciones/${tiendaId}/${id}/leer`)
      .then(() => setNotifs(prev => prev.map(n => n.id === id ? { ...n, leida: true } : n)))
      .catch(e => console.error('Error al marcar notificación:', e))
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(v => !v)}
        className="relative p-1.5 text-warm-400 hover:text-warm-700 transition-colors"
        aria-label="Notificaciones"
      >
        <Bell size={17} />
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 rounded-full bg-red-500 text-white text-[10px] font-bold flex items-center justify-center px-0.5">
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-80 bg-white rounded-2xl shadow-xl border border-warm-200 z-50 overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-warm-100">
            <span className="font-semibold text-sm text-warm-700">
              Notificaciones {unread > 0 && <span className="text-red-500">({unread} sin leer)</span>}
            </span>
            {unread > 0 && (
              <button
                onClick={marcarTodas}
                className="flex items-center gap-1 text-xs text-warm-400 hover:text-forest transition-colors"
              >
                <CheckCheck size={12} /> Marcar todas
              </button>
            )}
          </div>
          {/* Lista */}
          <div className="max-h-80 overflow-y-auto divide-y divide-warm-50">
            {notifs.length === 0 ? (
              <p className="text-center text-sm text-warm-400 py-8">Sin notificaciones</p>
            ) : notifs.map(n => {
              const cfg = NIVEL_CFG[n.nivel] ?? NIVEL_CFG.info
              return (
                <button
                  key={n.id}
                  onClick={() => marcarUna(n.id)}
                  className={`w-full text-left px-4 py-3 hover:bg-warm-50 transition-colors ${n.leida ? 'opacity-50' : ''}`}
                >
                  <div className="flex items-start gap-2">
                    <span className={`w-2 h-2 rounded-full flex-shrink-0 mt-1.5 ${cfg.dot}`} />
                    <div className="flex-1 min-w-0">
                      <p className={`text-xs font-semibold uppercase ${cfg.text}`}>{n.nivel}</p>
                      <p className="text-sm text-warm-700 leading-snug">{n.mensaje}</p>
                      <p className="text-xs text-warm-400 mt-0.5">{fmtFecha(n.fecha)}</p>
                    </div>
                    {!n.leida && <span className="w-2 h-2 rounded-full bg-forest flex-shrink-0 mt-1.5" />}
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

export default function Layout({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)

  const handleLogout = () => { logout(); navigate('/login') }

  return (
    <div className="min-h-screen bg-warm-50 flex flex-col lg:flex-row">

      {/* ══════════════════════════════════════════════════════════════════════
          DESKTOP: fixed left sidebar (lg+)
          MOBILE:  hidden — drawer handles it
      ══════════════════════════════════════════════════════════════════════ */}
      <aside className="hidden lg:flex lg:flex-col lg:w-60 lg:shrink-0 bg-white border-r border-warm-200 min-h-screen">

        {/* Sidebar — logo / brand */}
        <div className="flex items-center gap-2.5 px-5 py-4 border-b border-warm-100">
          <Coffee size={18} className="text-forest shrink-0" />
          <span className="font-bold text-warm-700 text-sm leading-tight">Sistema Café</span>
        </div>

        {/* Sidebar — nav links */}
        <nav className="flex-1 overflow-y-auto py-3 px-2">
          {NAV_ADMIN.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-xl mb-0.5 text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-forest-50 text-forest-700 font-semibold'
                    : 'text-warm-600 hover:text-warm-800 hover:bg-warm-100'
                }`
              }
            >
              <Icon size={15} className="shrink-0" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        {/* Sidebar — user footer */}
        <div className="p-4 border-t border-warm-100">
          <div className="flex items-center gap-2 mb-2">
            <div className="flex-1 min-w-0">
              <p className="text-xs font-semibold text-warm-700 truncate">{user?.nombre}</p>
              <span className={`text-[11px] px-1.5 py-0.5 rounded-full font-medium ${
                user?.rol === 'admin' ? 'bg-purple-100 text-purple-700' : 'bg-forest-50 text-forest'
              }`}>{user?.rol}</span>
            </div>
            {user?.rol === 'admin' && user.tienda_id && (
              <NotifBell tiendaId={user.tienda_id} />
            )}
          </div>
          <button
            onClick={handleLogout}
            className="flex items-center gap-1.5 text-xs text-warm-400 hover:text-red-500 transition-colors w-full"
          >
            <LogOut size={13} />
            <span>Cerrar sesión</span>
          </button>
        </div>
      </aside>

      {/* ══════════════════════════════════════════════════════════════════════
          MOBILE: top header (< lg)
      ══════════════════════════════════════════════════════════════════════ */}
      <header className="lg:hidden bg-white border-b border-warm-200 px-4 pb-3 header-safe flex items-center justify-between">
        <div className="flex items-center gap-2">
          <button
            className="p-1 -ml-1 text-warm-500 hover:text-warm-700 transition-colors"
            onClick={() => setMenuOpen(true)}
            aria-label="Abrir menú"
          >
            <Menu size={20} />
          </button>
          <Coffee size={18} className="text-forest" />
          <span className="font-bold text-warm-700">Sistema Café</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-warm-500 hidden sm:inline">{user?.nombre}</span>
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
            user?.rol === 'admin' ? 'bg-purple-100 text-purple-700' : 'bg-forest-50 text-forest'
          }`}>{user?.rol}</span>
          {user?.rol === 'admin' && user.tienda_id && (
            <NotifBell tiendaId={user.tienda_id} />
          )}
          <button
            onClick={handleLogout}
            className="flex items-center gap-1 text-xs text-warm-400 hover:text-red-500 transition-colors"
          >
            <LogOut size={13} />
            <span className="hidden sm:inline">Salir</span>
          </button>
        </div>
      </header>

      {/* ══════════════════════════════════════════════════════════════════════
          MOBILE: drawer (< lg)
      ══════════════════════════════════════════════════════════════════════ */}
      {menuOpen && (
        <div className="lg:hidden fixed inset-0 z-50 flex">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/40"
            onClick={() => setMenuOpen(false)}
          />
          {/* Drawer panel */}
          <div className="relative bg-white w-64 h-full flex flex-col shadow-2xl pt-safe">
            {/* Drawer header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-warm-100">
              <div className="flex items-center gap-2">
                <Coffee size={16} className="text-forest" />
                <span className="font-bold text-warm-700 text-sm">Sistema Café</span>
              </div>
              <button
                onClick={() => setMenuOpen(false)}
                className="text-warm-400 hover:text-warm-600 transition-colors"
                aria-label="Cerrar menú"
              >
                <X size={18} />
              </button>
            </div>

            {/* Nav links */}
            <div className="flex-1 overflow-y-auto py-2 px-2">
              {NAV_ADMIN.map(({ to, label, icon: Icon }) => (
                <NavLink key={to} to={to}
                  onClick={() => setMenuOpen(false)}
                  className={({ isActive }) =>
                    `flex items-center gap-3 px-4 py-3 rounded-xl mb-0.5 text-sm font-medium transition-colors ${
                      isActive
                        ? 'bg-forest-50 text-forest-700 font-semibold'
                        : 'text-warm-600 hover:text-warm-800 hover:bg-warm-100'
                    }`
                  }
                >
                  <Icon size={16} /> {label}
                </NavLink>
              ))}
            </div>

            {/* User footer */}
            <div className="p-4 border-t border-warm-100">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-semibold text-warm-700">{user?.nombre}</p>
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                    user?.rol === 'admin' ? 'bg-purple-100 text-purple-700' : 'bg-forest-50 text-forest'
                  }`}>{user?.rol}</span>
                </div>
                <button
                  onClick={handleLogout}
                  className="flex items-center gap-1.5 text-xs text-warm-400 hover:text-red-500 transition-colors px-2 py-1"
                >
                  <LogOut size={14} />
                  <span>Salir</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ══════════════════════════════════════════════════════════════════════
          Page content
          Desktop: fills the remaining width beside the sidebar
          Mobile:  full width below the header
      ══════════════════════════════════════════════════════════════════════ */}
      <div className="flex flex-col flex-1 min-w-0">
        {/* Desktop top-bar: just user controls (sidebar already has logo/nav) */}
        <header className="hidden lg:flex items-center justify-end gap-3 bg-white border-b border-warm-200 px-8 py-3">
          <span className="text-sm text-warm-500">{user?.nombre}</span>
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
            user?.rol === 'admin' ? 'bg-purple-100 text-purple-700' : 'bg-forest-50 text-forest'
          }`}>{user?.rol}</span>
          {user?.rol === 'admin' && user.tienda_id && (
            <NotifBell tiendaId={user.tienda_id} />
          )}
          <button
            onClick={handleLogout}
            className="flex items-center gap-1.5 text-xs text-warm-400 hover:text-red-500 transition-colors"
          >
            <LogOut size={13} />
            <span>Cerrar sesión</span>
          </button>
        </header>

        <main className="flex-1 px-4 py-3 lg:px-8 lg:py-6 max-w-screen-2xl w-full mx-auto">
          {children}
        </main>
      </div>

    </div>
  )
}
