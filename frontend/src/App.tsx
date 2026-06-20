import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { TurnoProvider, useTurno } from './contexts/TurnoContext'
import Layout from './components/Layout'
import OperativeBanner from './components/OperativeBanner'
import Drawer from './components/Drawer'

// Device setup
import KioskSetup from './pages/KioskSetup'

// Barista / kiosco pages
import GestionTurno from './pages/GestionTurno'
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
import NotaCredito from './pages/NotaCredito'

// ─── Guards ───────────────────────────────────────────────────────────────────

function RequireAdmin({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  if (!user) return <Navigate to="/admin-login" replace />
  if (user.rol !== 'admin') return <Navigate to="/pos" replace />
  return <>{children}</>
}

function FullLoader() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-bark-900">
      <p className="text-sm text-warm-500 animate-pulse">Cargando…</p>
    </div>
  )
}

// Landing: decide a dónde entrar según el estado del turno.
// Admin → dashboard · sin sesión → setup · turno operativo → POS · si no → flujo gateado.
function Landing() {
  const { user } = useAuth()
  const { turno, loading } = useTurno()
  if (user?.rol === 'admin') return <Navigate to="/dashboard" replace />
  if (!user) return <KioskSetup />
  if (loading) return <FullLoader />
  return <Navigate to={turno?.es_operativo ? '/pos' : '/gestion-turno'} replace />
}

// Gate duro del POS: solo se entra si el turno está operativo (cuadre + conteo hechos).
function RequireOperativo({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  const { turno, loading } = useTurno()
  if (!user) return <KioskSetup />
  if (loading) return <FullLoader />
  if (!turno?.es_operativo) return <Navigate to="/gestion-turno" replace />
  return <>{children}</>
}

function AppRoutes() {
  const { user } = useAuth()
  const location = useLocation()

  // Sin sesión activa (ni kiosco ni usuario) → KioskSetup
  const hasSession = !!user
  const isAdmin = user?.rol === 'admin'

  // Route-as-overlay: si la navegación trae `background`, el <Routes> base pinta
  // esa pantalla (el POS, con su carrito) y la herramienta se abre en un cajón
  // encima (ver Drawer + OperativeBanner.goDrawer). Sin background → ruta normal.
  const background = (location.state as { background?: typeof location })?.background

  return (
    <>
    <OperativeBanner />
    <Routes location={background || location}>
      {/* ── Login admin ── */}
      <Route path="/admin-login" element={
        isAdmin ? <Navigate to="/dashboard" replace /> : <Login />
      } />

      {/* ── Landing: resolver que rutea POS vs flujo gateado ── */}
      <Route path="/" element={<Landing />} />

      {/* ── POS: solo si el turno está operativo (gate duro) ── */}
      <Route path="/pos" element={<RequireOperativo><POS /></RequireOperativo>} />

      {/* ── Gestión de turno ── */}
      <Route path="/gestion-turno" element={hasSession ? <GestionTurno /> : <KioskSetup />} />

      {/* ── Flujo de turno (accesibles con cualquier sesión) ── */}
      <Route path="/conteo-apertura" element={hasSession ? <ConteoApertura /> : <KioskSetup />} />
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
      <Route path="/notas-credito"    element={<RequireAdmin><Layout><NotaCredito /></Layout></RequireAdmin>} />
      <Route path="/pedidos-admin"    element={<RequireAdmin><Layout><PedidosAdmin /></Layout></RequireAdmin>} />
      <Route path="/mantenimientos"   element={<RequireAdmin><Layout><MantenimientosAdmin /></Layout></RequireAdmin>} />
      <Route path="/auditorias"       element={<RequireAdmin><Layout><AuditoriasAdmin /></Layout></RequireAdmin>} />
      <Route path="/audit-log"        element={<RequireAdmin><Layout><AuditLog /></Layout></RequireAdmin>} />

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>

    {/* ── Cajones sobre el POS (route-as-overlay) ──
        Herramientas de alta frecuencia: se abren encima de la pantalla de
        fondo sin desmontarla. Solo se montan si la navegación trae background
        (lo setea OperativeBanner.goDrawer); el deep-link directo cae en la
        ruta full-page de arriba. */}
    {background && hasSession && (
      <Routes>
        <Route path="/ingresos"   element={<Drawer><Ingresos /></Drawer>} />
        <Route path="/mermas"     element={<Drawer><Mermas /></Drawer>} />
        <Route path="/inventario" element={<Drawer><Inventario /></Drawer>} />
        <Route path="/pedido"     element={<Drawer><SolicitudPedido /></Drawer>} />
        <Route path="/sencilla"   element={<Drawer><SolicitudSencilla /></Drawer>} />
      </Routes>
    )}
    </>
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
