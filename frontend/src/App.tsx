import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { TurnoProvider } from './contexts/TurnoContext'
import Layout from './components/Layout'

// Device setup
import KioskSetup from './pages/KioskSetup'

// Barista / kiosco pages
import GestionTurno from './pages/GestionTurno'
import CuadreLlegada from './pages/CuadreLlegada'
import Apertura from './pages/Apertura'
import ConteoApertura from './pages/ConteoApertura'
import Hub from './pages/Hub'
import VentasDia from './pages/VentasDia'
import ConteoCierre from './pages/ConteoCierre'
import Cierre from './pages/Cierre'
import Entrega from './pages/Entrega'
import VentasHoy from './pages/VentasHoy'
import Inventario from './pages/Inventario'
import Mermas from './pages/Mermas'
import Pasteleria from './pages/Pasteleria'
import Consignaciones from './pages/Consignaciones'
import ConsignacionesAdmin from './pages/ConsignacionesAdmin'
import SolicitudPedido from './pages/SolicitudPedido'
import SolicitudSencilla from './pages/SolicitudSencilla'
import ConteoFisico from './pages/ConteoFisico'
import Limpieza from './pages/Limpieza'
import Ingresos from './pages/Ingresos'
import ConteoCompras from './pages/ConteoCompras'
import POS from './pages/POS'

// Admin pages
import Login from './pages/Login'
import Analytics from './pages/Analytics'
import ControlInventario from './pages/ControlInventario'
import AdminHub from './pages/AdminHub'
import Bandeja from './pages/Bandeja'
import Informes from './pages/Informes'
import ComprasAdmin from './pages/ComprasAdmin'
import Comunicados from './pages/Comunicados'
import Usuarios from './pages/Usuarios'
import PedidosAdmin from './pages/PedidosAdmin'
import MantenimientosAdmin from './pages/MantenimientosAdmin'
import AuditoriasAdmin from './pages/AuditoriasAdmin'
import AuditLog from './pages/AuditLog'
import Catalogo from './pages/Catalogo'

// ─── Guards ───────────────────────────────────────────────────────────────────

function RequireAdmin({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  if (!user) return <Navigate to="/admin-login" replace />
  if (user.rol !== 'admin') return <Navigate to="/pos" replace />
  return <>{children}</>
}

function AppRoutes() {
  const { user, tiendaId } = useAuth()

  // Sin sesión activa (ni kiosco ni usuario) → KioskSetup
  const hasSession = !!user
  const isAdmin = user?.rol === 'admin'

  return (
    <Routes>
      {/* ── Login admin ── */}
      <Route path="/admin-login" element={
        isAdmin ? <Navigate to="/dashboard" replace /> : <Login />
      } />

      {/* ── Landing: POS o setup ── */}
      <Route path="/" element={
        isAdmin
          ? <Navigate to="/dashboard" replace />
          : hasSession
            ? <Navigate to="/pos" replace />
            : <KioskSetup />
      } />

      {/* ── POS (siempre accesible si hay sesión) ── */}
      <Route path="/pos" element={hasSession ? <POS /> : <KioskSetup />} />

      {/* ── Gestión de turno ── */}
      <Route path="/gestion-turno" element={hasSession ? <GestionTurno /> : <KioskSetup />} />

      {/* ── Flujo de turno (accesibles con cualquier sesión) ── */}
      <Route path="/apertura"        element={hasSession ? <Apertura />       : <KioskSetup />} />
      <Route path="/conteo-apertura" element={hasSession ? <ConteoApertura /> : <KioskSetup />} />
      <Route path="/cuadre-llegada"  element={hasSession ? <CuadreLlegada />  : <KioskSetup />} />
      <Route path="/conteo-cierre"   element={hasSession ? <ConteoCierre />   : <KioskSetup />} />
      <Route path="/cierre"          element={hasSession ? <Cierre />         : <KioskSetup />} />
      <Route path="/entrega"         element={hasSession ? <Entrega />        : <KioskSetup />} />
      <Route path="/hub"             element={hasSession ? <Hub />            : <KioskSetup />} />

      {/* ── Herramientas barista ── */}
      <Route path="/mermas"         element={hasSession ? <Mermas />         : <KioskSetup />} />
      <Route path="/pasteleria"     element={hasSession ? <Pasteleria />     : <KioskSetup />} />
      <Route path="/pedido"         element={hasSession ? <SolicitudPedido />: <KioskSetup />} />
      <Route path="/sencilla"       element={hasSession ? <SolicitudSencilla /> : <KioskSetup />} />
      <Route path="/conteos"        element={hasSession ? <ConteoFisico />   : <KioskSetup />} />
      <Route path="/ingresos"       element={hasSession ? <Ingresos />       : <KioskSetup />} />
      <Route path="/conteo-compras" element={hasSession ? <ConteoCompras />  : <KioskSetup />} />
      <Route path="/ventas-hoy"     element={hasSession ? <VentasHoy />      : <KioskSetup />} />
      <Route path="/limpieza"       element={
        hasSession
          ? isAdmin ? <Layout><Limpieza /></Layout> : <Limpieza />
          : <KioskSetup />
      } />
      <Route path="/inventario"     element={
        hasSession
          ? isAdmin ? <Layout><Inventario /></Layout> : <Inventario />
          : <KioskSetup />
      } />
      <Route path="/consignaciones" element={
        hasSession
          ? isAdmin ? <Layout><ConsignacionesAdmin /></Layout> : <Consignaciones />
          : <KioskSetup />
      } />

      {/* /ventas: registro manual de emergencia — solo admin */}
      <Route path="/ventas" element={<RequireAdmin><VentasDia /></RequireAdmin>} />

      {/* ── Admin ── */}
      <Route path="/dashboard"        element={<RequireAdmin><AdminHub /></RequireAdmin>} />
      <Route path="/analytics"        element={<RequireAdmin><Layout><Analytics /></Layout></RequireAdmin>} />
      <Route path="/bandeja"          element={<RequireAdmin><Layout><Bandeja /></Layout></RequireAdmin>} />
      <Route path="/informes"         element={<RequireAdmin><Layout><Informes /></Layout></RequireAdmin>} />
      <Route path="/compras"          element={<RequireAdmin><Layout><ComprasAdmin /></Layout></RequireAdmin>} />
      <Route path="/comunicados"      element={<RequireAdmin><Layout><Comunicados /></Layout></RequireAdmin>} />
      <Route path="/usuarios"         element={<RequireAdmin><Layout><Usuarios /></Layout></RequireAdmin>} />
      <Route path="/control-inventario" element={<RequireAdmin><Layout><ControlInventario /></Layout></RequireAdmin>} />
      <Route path="/catalogo"         element={<RequireAdmin><Layout><Catalogo /></Layout></RequireAdmin>} />
      <Route path="/pedidos-admin"    element={<RequireAdmin><Layout><PedidosAdmin /></Layout></RequireAdmin>} />
      <Route path="/mantenimientos"   element={<RequireAdmin><Layout><MantenimientosAdmin /></Layout></RequireAdmin>} />
      <Route path="/auditorias"       element={<RequireAdmin><Layout><AuditoriasAdmin /></Layout></RequireAdmin>} />
      <Route path="/audit-log"        element={<RequireAdmin><Layout><AuditLog /></Layout></RequireAdmin>} />

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <TurnoProvider>
          <AppRoutes />
        </TurnoProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}
