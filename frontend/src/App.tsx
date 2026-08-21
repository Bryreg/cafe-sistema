import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { TurnoProvider, useTurno } from './contexts/TurnoContext'
import { BaristaActivaProvider } from './contexts/BaristaActivaContext'
import Layout from './components/Layout'
import OperativeBanner from './components/OperativeBanner'
// Device setup
import KioskSetup from './pages/KioskSetup'

// Barista / kiosco pages
import GestionTurno from './pages/GestionTurno'
import ConteoApertura from './pages/ConteoApertura'
import VentasDia from './pages/VentasDia'
import ConteoCierre from './pages/ConteoCierre'
import SalidaEfectivo from './pages/SalidaEfectivo'
import Cierre from './pages/Cierre'
import Entrega from './pages/Entrega'
import VentasHoy from './pages/VentasHoy'
import VentasMes from './pages/VentasMes'
import Inventario from './pages/Inventario'
import Mermas from './pages/Mermas'
import Preparaciones from './pages/Preparaciones'
import GuiaRapida from './pages/GuiaRapida'
import Pasteleria from './pages/Pasteleria'
import Consignaciones from './pages/Consignaciones'
import ConsignacionesAdmin from './pages/ConsignacionesAdmin'
import SolicitudPedido from './pages/SolicitudPedido'
import SolicitudSencilla from './pages/SolicitudSencilla'
import Limpieza from './pages/Limpieza'
import Ingresos from './pages/Ingresos'
import ConteoDesechables from './pages/ConteoDesechables'
import CuadreInicial from './pages/CuadreInicial'
import HistorialVentas from './pages/HistorialVentas'
import MiHorario from './pages/MiHorario'
import POS from './pages/POS'

// Admin pages
import Login from './pages/Login'
import ControlInventario from './pages/ControlInventario'
import Dashboard from './pages/Dashboard'
import Bandeja from './pages/Bandeja'
import Informes from './pages/Informes'
import Comunicados from './pages/Comunicados'
import Usuarios from './pages/Usuarios'
import PedidosAdmin from './pages/PedidosAdmin'
import MantenimientosAdmin from './pages/MantenimientosAdmin'
import AuditoriasAdmin from './pages/AuditoriasAdmin'
import AuditLog from './pages/AuditLog'
import Catalogo from './pages/Catalogo'
import CombosAdmin from './pages/CombosAdmin'
import NotaCredito from './pages/NotaCredito'
import CumplimientoAdmin from './pages/CumplimientoAdmin'
import InformeContador from './pages/InformeContador'
import InventarioMensual from './pages/InventarioMensual'
import ConciliacionInventario from './pages/ConciliacionInventario'
import ConteosAdmin from './pages/ConteosAdmin'
import LotesTrazabilidad from './pages/LotesTrazabilidad'
import NotificacionesConfig from './pages/NotificacionesConfig'
import CuadreTurnos from './pages/CuadreTurnos'
import ConfigTicketPage from './pages/ConfigTicket'
import Plata from './pages/Plata'
import MesEnDetalle from './pages/MesEnDetalle'
import Carta from './pages/Carta'
import Horarios from './pages/Horarios'

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

  const hasSession = !!user
  const isAdmin = user?.rol === 'admin'

  return (
    <>
    <OperativeBanner />
    <Routes>
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
      <Route path="/salida-efectivo" element={hasSession ? <SalidaEfectivo /> : <KioskSetup />} />
      <Route path="/cierre"          element={hasSession ? <Cierre />         : <KioskSetup />} />
      <Route path="/entrega"         element={hasSession ? <Entrega />        : <KioskSetup />} />
      {/* /hub deprecado: el Landing rutea a POS o gestión-turno según el estado */}
      <Route path="/hub"             element={<Navigate to="/" replace />} />

      {/* ── Herramientas barista ── */}
      <Route path="/mermas"         element={hasSession ? <Mermas />         : <KioskSetup />} />
      <Route path="/preparaciones"  element={hasSession ? <Preparaciones />  : <KioskSetup />} />
      <Route path="/pasteleria"     element={hasSession ? <Pasteleria />     : <KioskSetup />} />
      <Route path="/pedido"         element={hasSession ? <SolicitudPedido />: <KioskSetup />} />
      <Route path="/sencilla"       element={hasSession ? <SolicitudSencilla /> : <KioskSetup />} />
      <Route path="/inventario-mensual" element={hasSession ? <InventarioMensual /> : <KioskSetup />} />
      {/* «Recibir»: el nombre que la navegación ya usaba. `/ingresos` era la
          peor colisión del sistema — la pantalla donde se cargan las FACTURAS
          (plata que SALE) llamada con la palabra de la plata que ENTRA, en el
          camino diario de la barista. La ruta vieja queda como alias porque la
          PWA cachea bundles con el link viejo. */}
      <Route path="/recibir"        element={hasSession ? <Ingresos />       : <KioskSetup />} />
      <Route path="/ingresos"       element={hasSession ? <Ingresos />       : <KioskSetup />} />
      <Route path="/historial-ventas" element={hasSession ? <HistorialVentas /> : <KioskSetup />} />
      {/* Mi horario: lo ve la barista (kiosko o celular). Un admin que entre acá
          va al armado, que es su versión de la misma pregunta. */}
      <Route path="/mi-horario" element={
        hasSession
          ? isAdmin ? <Navigate to="/horarios" replace /> : <MiHorario />
          : <KioskSetup />
      } />
      <Route path="/cuadre-turnos"   element={
        hasSession
          ? isAdmin ? <Layout><CuadreTurnos /></Layout> : <CuadreTurnos />
          : <KioskSetup />
      } />
      {/* /conteo-compras: la pantalla salió del menú el 3-jul (la reemplazó el doble
          conteo) y desde entonces no la linkeaba nadie. Se borró el componente; la
          ruta queda como redirect para que un bookmark viejo caiga en el flujo vivo. */}
      <Route path="/conteo-compras"  element={<Navigate to="/conteo-desechables" replace />} />
      <Route path="/conteo-desechables" element={hasSession ? <ConteoDesechables /> : <KioskSetup />} />
      <Route path="/cuadre-inicial" element={hasSession ? <CuadreInicial />  : <KioskSetup />} />
      <Route path="/ventas-hoy"     element={hasSession ? <VentasHoy />      : <KioskSetup />} />
      <Route path="/ventas-mes"     element={hasSession ? <VentasMes />      : <KioskSetup />} />
      <Route path="/limpieza"       element={
        hasSession
          ? isAdmin ? <Layout><Limpieza /></Layout> : <Limpieza />
          : <KioskSetup />
      } />
      {/* /inventario es la vista BARISTA (la que usa el kiosko y el panel del POS).
          La vista admin que vivía acá duplicaba /catalogo y /control-inventario y no
          la linkeaba nada; se borró. El admin que llegue por un bookmark viejo cae en
          la pantalla que sí es la buena, no en un 404. */}
      <Route path="/inventario"     element={
        hasSession
          ? isAdmin ? <Navigate to="/control-inventario" replace /> : <Inventario />
          : <KioskSetup />
      } />
      <Route path="/consignaciones" element={
        hasSession
          ? isAdmin ? <Layout><ConsignacionesAdmin /></Layout> : <Consignaciones />
          : <KioskSetup />
      } />
      <Route path="/guia" element={
        hasSession
          ? isAdmin ? <Layout><GuiaRapida /></Layout> : <GuiaRapida />
          : <KioskSetup />
      } />

      {/* /ventas: registro manual de emergencia — solo admin */}
      <Route path="/ventas" element={<RequireAdmin><VentasDia /></RequireAdmin>} />

      {/* ── Admin ── */}
      <Route path="/dashboard"           element={<RequireAdmin><Layout><Dashboard /></Layout></RequireAdmin>} />
      <Route path="/dashboard-ejecutivo" element={<Navigate to="/dashboard" replace />} />
      <Route path="/analytics"        element={<Navigate to="/informes" replace />} />
      <Route path="/bandeja"          element={<RequireAdmin><Layout><Bandeja /></Layout></RequireAdmin>} />
      <Route path="/informes"         element={<RequireAdmin><Layout><Informes /></Layout></RequireAdmin>} />
      <Route path="/informe-contador" element={<RequireAdmin><Layout><InformeContador /></Layout></RequireAdmin>} />
      {/* Pagos a proveedores se mudó adentro del módulo de la plata (fase 5, y de
          nuevo con la fusión). La ruta vieja se conserva como redirect: nadie con
          un bookmark se queda colgado. SIN hash: `#plata` dejó de anclar nada y
          un redirect a un ancla muerta aterriza en el tope igual — mejor decirlo
          con la URL limpia. */}
      <Route path="/pagos-proveedores" element={<Navigate to="/plata" replace />} />
      <Route path="/conciliacion-inventario" element={<RequireAdmin><Layout><ConciliacionInventario /></Layout></RequireAdmin>} />
      <Route path="/conteos-admin"    element={<RequireAdmin><Layout><ConteosAdmin /></Layout></RequireAdmin>} />
      <Route path="/lotes"            element={<RequireAdmin><Layout><LotesTrazabilidad /></Layout></RequireAdmin>} />
      <Route path="/comunicados"      element={<RequireAdmin><Layout><Comunicados /></Layout></RequireAdmin>} />
      <Route path="/horarios"         element={<RequireAdmin><Layout><Horarios /></Layout></RequireAdmin>} />
      <Route path="/usuarios"         element={<RequireAdmin><Layout><Usuarios /></Layout></RequireAdmin>} />
      <Route path="/control-inventario" element={<RequireAdmin><Layout><ControlInventario /></Layout></RequireAdmin>} />
      <Route path="/catalogo"         element={<RequireAdmin><Layout><Catalogo /></Layout></RequireAdmin>} />
      <Route path="/carta"           element={<RequireAdmin><Layout><Carta /></Layout></RequireAdmin>} />
      <Route path="/combos"           element={<RequireAdmin><Layout><CombosAdmin /></Layout></RequireAdmin>} />
      <Route path="/notas-credito"    element={<RequireAdmin><Layout><NotaCredito /></Layout></RequireAdmin>} />
      <Route path="/pedidos-admin"    element={<RequireAdmin><Layout><PedidosAdmin /></Layout></RequireAdmin>} />
      <Route path="/mantenimientos"   element={<RequireAdmin><Layout><MantenimientosAdmin /></Layout></RequireAdmin>} />
      <Route path="/auditorias"       element={<RequireAdmin><Layout><AuditoriasAdmin /></Layout></RequireAdmin>} />
      <Route path="/audit-log"        element={<RequireAdmin><Layout><AuditLog /></Layout></RequireAdmin>} />
      <Route path="/notificaciones-config" element={<RequireAdmin><Layout><NotificacionesConfig /></Layout></RequireAdmin>} />
      <Route path="/cumplimiento"     element={<RequireAdmin><Layout><CumplimientoAdmin /></Layout></RequireAdmin>} />
      <Route path="/config-ticket"   element={<RequireAdmin><Layout><ConfigTicketPage /></Layout></RequireAdmin>} />
      {/* «El piso» = una sola página con los ocho bloques. Las pestañas se
          murieron, así que los hashes viejos (#plata, #resultado, #hoy,
          #calendario) ya no seleccionan nada — y no hace falta que lo hagan:
          `/plata` a secas es la página entera y un hash desconocido no rompe
          nada, simplemente no ancla. Lo único que se mudó de verdad es el
          Resultado, que ahora es su propia ruta.

          `/rentabilidad` apunta ahí y NO a `/plata`: quien tenía ese bookmark
          buscaba el margen por producto y el duelo de sedes, no el piso. */}
      <Route path="/plata"           element={<RequireAdmin><Layout><Plata /></Layout></RequireAdmin>} />
      <Route path="/plata/mes"       element={<RequireAdmin><Layout><MesEnDetalle /></Layout></RequireAdmin>} />
      <Route path="/rentabilidad"    element={<Navigate to="/plata/mes" replace />} />
      <Route path="/costos"          element={<Navigate to="/plata" replace />} />

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
    </>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <TurnoProvider>
          <BaristaActivaProvider>
            <AppRoutes />
          </BaristaActivaProvider>
        </TurnoProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}
