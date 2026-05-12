import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import {
  Coffee, LayoutDashboard, Package, Banknote, LogOut, Inbox,
  BarChart2, ShoppingCart, Bell, Users, Menu, X,
} from 'lucide-react'

const NAV_ADMIN = [
  { to: '/dashboard',      label: 'Dashboard',      icon: LayoutDashboard },
  { to: '/inventario',     label: 'Inventario',      icon: Package },
  { to: '/compras',        label: 'Compras',         icon: ShoppingCart },
  { to: '/consignaciones', label: 'Consignaciones',  icon: Banknote },
  { to: '/comunicados',    label: 'Comunicados',     icon: Bell },
  { to: '/bandeja',        label: 'Bandeja',         icon: Inbox },
  { to: '/informes',       label: 'Informes',        icon: BarChart2 },
  { to: '/usuarios',       label: 'Usuarios',        icon: Users },
]

export default function Layout({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)

  const handleLogout = () => { logout(); navigate('/login') }

  return (
    <div className="min-h-screen bg-warm-50 flex flex-col">

      {/* ── Header ────────────────────────────────────────────────────────── */}
      <header className="bg-white border-b border-warm-200 px-4 pb-3 header-safe flex items-center justify-between">
        <div className="flex items-center gap-2">
          {/* Hamburger — visible only on mobile */}
          <button
            className="md:hidden p-1 -ml-1 text-warm-500 hover:text-warm-700 transition-colors"
            onClick={() => setMenuOpen(true)}
            aria-label="Abrir menú"
          >
            <Menu size={20} />
          </button>
          <Coffee size={18} className="text-forest" />
          <span className="font-bold text-warm-700">Sistema Café</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-warm-500 hidden sm:inline">{user?.nombre}</span>
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
            user?.rol === 'admin' ? 'bg-purple-100 text-purple-700' : 'bg-forest-50 text-forest'
          }`}>{user?.rol}</span>
          <button
            onClick={handleLogout}
            className="flex items-center gap-1 text-xs text-warm-400 hover:text-red-500 transition-colors"
          >
            <LogOut size={13} />
            <span className="hidden sm:inline">Salir</span>
          </button>
        </div>
      </header>

      {/* ── Desktop nav (hidden on mobile) ───────────────────────────────── */}
      <nav className="hidden md:block bg-white border-b border-warm-200 px-4">
        <div className="flex gap-1 py-2 overflow-x-auto">
          {NAV_ADMIN.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to}
              className={({ isActive }) =>
                `flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-md transition-colors whitespace-nowrap ${
                  isActive
                    ? 'bg-forest-50 text-forest font-semibold'
                    : 'text-warm-500 hover:text-warm-700 hover:bg-warm-100'
                }`
              }
            >
              <Icon size={14} /> {label}
            </NavLink>
          ))}
        </div>
      </nav>

      {/* ── Mobile drawer ────────────────────────────────────────────────── */}
      {menuOpen && (
        <div className="md:hidden fixed inset-0 z-50 flex">
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
                        ? 'bg-forest-50 text-forest font-semibold'
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

      {/* ── Page content ─────────────────────────────────────────────────── */}
      <main className="flex-1 p-3 sm:p-4 max-w-5xl mx-auto w-full">{children}</main>
    </div>
  )
}
