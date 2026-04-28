import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { Coffee, LayoutDashboard, Package, Banknote, LogOut, Inbox, BarChart2, BookOpen, ChefHat } from 'lucide-react'

const NAV_ADMIN = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/inventario', label: 'Inventario', icon: Package },
  { to: '/catalogo', label: 'Catálogo', icon: BookOpen },
  { to: '/recetas', label: 'Recetas', icon: ChefHat },
  { to: '/consignaciones', label: 'Consignaciones', icon: Banknote },
  { to: '/bandeja', label: 'Bandeja', icon: Inbox },
  { to: '/informes', label: 'Informes', icon: BarChart2 },
]

export default function Layout({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const handleLogout = () => { logout(); navigate('/login') }

  return (
    <div className="min-h-screen bg-warm-50 flex flex-col">
      <header className="bg-white border-b border-warm-200 px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Coffee size={18} className="text-forest" />
          <span className="font-bold text-warm-700">Sistema Café</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-warm-500">{user?.nombre}</span>
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
            user?.rol === 'admin' ? 'bg-purple-100 text-purple-700' : 'bg-forest-50 text-forest'
          }`}>{user?.rol}</span>
          <button onClick={handleLogout} className="flex items-center gap-1 text-xs text-warm-400 hover:text-red-500 transition-colors">
            <LogOut size={13} /> Salir
          </button>
        </div>
      </header>
      <nav className="bg-white border-b border-warm-200 px-4">
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
      <main className="flex-1 p-4 max-w-5xl mx-auto w-full">{children}</main>
    </div>
  )
}
