import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { TurnoProvider, useTurno } from './contexts/TurnoContext'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'

// Barista flow pages
import Login from './pages/Login'
import SeleccionarTurno from './pages/SeleccionarTurno'
import CuadreLlegada from './pages/CuadreLlegada'
import Apertura from './pages/Apertura'
import ConteoApertura from './pages/ConteoApertura'
import Hub from './pages/Hub'
import VentasDia from './pages/VentasDia'
import ConteoCierre from './pages/ConteoCierre'
import Cierre from './pages/Cierre'
import Entrega from './pages/Entrega'

// Barista tool pages
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

// Admin pages
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
import SiigoMapeo from './pages/SiigoMapeo'

// ─── Smart redirect basado en estado del turno ───────────────────────────────
function SmartRedirect() {
  const { user, tipo_turno, cuadre_llegada_turno_id } = useAuth()
  const { turno, loading } = useTurno()

  if (!user) return <Navigate to="/login" replace />
  if (user.rol === 'admin') return <Navigate to="/dashboard" replace />

  // Barista debe elegir tipo de turno primero
  if (!tipo_turno) return <Navigate to="/seleccionar-turno" replace />

  if (loading) return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <p className="text-sm text-gray-400 animate-pulse">Consultando turno...</p>
    </div>
  )

  if (tipo_turno === 'apertura') {
    if (!turno) return <Navigate to="/apertura" replace />
    return <Navigate to="/hub" replace />
  }

  // intermedio o cierre: debe haber turno activo y haber hecho cuadre de llegada
  if (!turno) return <Navigate to="/seleccionar-turno" replace />
  if (cuadre_llegada_turno_id !== turno.id) return <Navigate to="/cuadre-llegada" replace />
  return <Navigate to="/hub" replace />
}

// ─── Rutas internas ──────────────────────────────────────────────────────────
function AppRoutes() {
  const { user } = useAuth()

  return (
    <Routes>
      {/* Login */}
      <Route path="/login" element={!user ? <Login /> : <Navigate to="/" replace />} />

      {/* Smart redirect */}
      <Route path="/" element={
        <ProtectedRoute><SmartRedirect /></ProtectedRoute>
      } />

      {/* ── Selección de tipo de turno ── */}
      <Route path="/seleccionar-turno" element={
        <ProtectedRoute role="barista"><SeleccionarTurno /></ProtectedRoute>
      } />
      <Route path="/cuadre-llegada" element={
        <ProtectedRoute role="barista"><CuadreLlegada /></ProtectedRoute>
      } />

      {/* ── Flujo de turno barista (sin nav lateral) ── */}
      <Route path="/apertura" element={
        <ProtectedRoute role="barista"><Apertura /></ProtectedRoute>
      } />
      <Route path="/conteo-apertura" element={
        <ProtectedRoute role="barista"><ConteoApertura /></ProtectedRoute>
      } />
      <Route path="/hub" element={
        <ProtectedRoute role="barista"><Hub /></ProtectedRoute>
      } />
      <Route path="/ventas" element={
        <ProtectedRoute role="admin"><VentasDia /></ProtectedRoute>
      } />
      <Route path="/conteo-cierre" element={
        <ProtectedRoute role="barista"><ConteoCierre /></ProtectedRoute>
      } />
      <Route path="/cierre" element={
        <ProtectedRoute role="barista"><Cierre /></ProtectedRoute>
      } />
      <Route path="/entrega" element={
        <ProtectedRoute role="barista"><Entrega /></ProtectedRoute>
      } />

      {/* ── Herramientas barista (con BaristaLayout interno) ── */}
      <Route path="/mermas" element={
        <ProtectedRoute role="barista"><Mermas /></ProtectedRoute>
      } />
      <Route path="/pasteleria" element={
        <ProtectedRoute role="barista"><Pasteleria /></ProtectedRoute>
      } />
      <Route path="/pedido" element={
        <ProtectedRoute role="barista"><SolicitudPedido /></ProtectedRoute>
      } />
      <Route path="/sencilla" element={
        <ProtectedRoute role="barista"><SolicitudSencilla /></ProtectedRoute>
      } />
      <Route path="/conteos" element={
        <ProtectedRoute role="barista"><ConteoFisico /></ProtectedRoute>
      } />
      <Route path="/ingresos" element={
        <ProtectedRoute role="barista"><Ingresos /></ProtectedRoute>
      } />
      <Route path="/conteo-compras" element={
        <ProtectedRoute role="barista"><ConteoCompras /></ProtectedRoute>
      } />
      <Route path="/limpieza" element={
        <ProtectedRoute>
          {user?.rol === 'admin'
            ? <Layout><Limpieza /></Layout>
            : <Limpieza />
          }
        </ProtectedRoute>
      } />

      {/* ── Rutas compartidas barista + admin ── */}
      <Route path="/inventario" element={
        <ProtectedRoute>
          {user?.rol === 'admin'
            ? <Layout><Inventario /></Layout>
            : <Inventario />
          }
        </ProtectedRoute>
      } />
      <Route path="/consignaciones" element={
        <ProtectedRoute>
          {user?.rol === 'admin'
            ? <Layout><ConsignacionesAdmin /></Layout>
            : <Consignaciones />
          }
        </ProtectedRoute>
      } />

      {/* ── Admin ── */}
      <Route path="/dashboard" element={
        <ProtectedRoute role="admin"><AdminHub /></ProtectedRoute>
      } />
      <Route path="/bandeja" element={
        <ProtectedRoute role="admin"><Layout><Bandeja /></Layout></ProtectedRoute>
      } />
      <Route path="/informes" element={
        <ProtectedRoute role="admin"><Layout><Informes /></Layout></ProtectedRoute>
      } />
      <Route path="/compras" element={
        <ProtectedRoute role="admin"><Layout><ComprasAdmin /></Layout></ProtectedRoute>
      } />
      <Route path="/comunicados" element={
        <ProtectedRoute role="admin"><Layout><Comunicados /></Layout></ProtectedRoute>
      } />
      <Route path="/usuarios" element={
        <ProtectedRoute role="admin"><Layout><Usuarios /></Layout></ProtectedRoute>
      } />
      <Route path="/control-inventario" element={
        <ProtectedRoute role="admin"><Layout><ControlInventario /></Layout></ProtectedRoute>
      } />
      <Route path="/pedidos-admin" element={
        <ProtectedRoute role="admin"><Layout><PedidosAdmin /></Layout></ProtectedRoute>
      } />
      <Route path="/mantenimientos" element={
        <ProtectedRoute role="admin"><Layout><MantenimientosAdmin /></Layout></ProtectedRoute>
      } />
      <Route path="/auditorias" element={
        <ProtectedRoute role="admin"><Layout><AuditoriasAdmin /></Layout></ProtectedRoute>
      } />
      <Route path="/audit-log" element={
        <ProtectedRoute role="admin"><Layout><AuditLog /></Layout></ProtectedRoute>
      } />
      <Route path="/siigo-mapeo" element={
        <ProtectedRoute role="admin"><Layout><SiigoMapeo /></Layout></ProtectedRoute>
      } />

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
