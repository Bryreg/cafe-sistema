import { useCallback, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'
import { useDato } from '../api/useDato'
import { FranjaDeConfianza } from '../components/ui'
import { hoyBogota } from '../utils/fechaLocal'
import { MESES } from '../components/plata/banco'
import { CuentaBanco } from '../components/plata/banco'
import { Agenda, Bandeja, Categoria, Flujo, Listado, Tienda } from '../components/plata/tipos'
import type { PorProductoData, PulsoData, RentabilidadData } from '../components/rentabilidad/helpers'
import { useLibro } from '../components/plata/useLibro'
import BannerLibro from '../components/plata/BannerLibro'
import BannerProveedores from '../components/plata/BannerProveedores'
import BannerObligaciones from '../components/plata/BannerObligaciones'
import type { Piso } from '../components/piso/tipos'
import { armarRevisiones } from '../components/piso/pendientes'
import BloqueElPiso from '../components/piso/BloqueElPiso'
import BloqueHoy from '../components/piso/BloqueHoy'
import BloqueCuantaPlata from '../components/piso/BloqueCuantaPlata'
import BloqueLoQueHayQuePagar from '../components/piso/BloqueLoQueHayQuePagar'
import BloqueFinDeMes from '../components/piso/BloqueFinDeMes'
import BloqueSubeElPiso from '../components/piso/BloqueSubeElPiso'
import BloqueBajaElMargen from '../components/piso/BloqueBajaElMargen'
import BloqueElAnio from '../components/piso/BloqueElAnio'
import UnaVezAlMes from '../components/piso/UnaVezAlMes'

// ═════════════════════════════════════════════════════════════════════════════
// EL PISO — una página, ocho bloques, un solo scroll
// ═════════════════════════════════════════════════════════════════════════════
// El dueño abre esto temprano, antes de abrir el local, en una tablet. Tiene que
// saber en treinta segundos si llega a fin de mes. Los ocho bloques contestan
// sus tres preguntas en orden y sin que tenga que buscar nada:
//
//   TENER     1 · el piso        2 · hoy          3 · cuánta plata hay
//   PROYECTAR 4 · qué hay que pagar               5 · ¿llega a fin de mes?
//   MANEJAR   6 · lo que sube el piso  7 · lo que lo baja  8 · el año
//
// ── LAS DOS PESTAÑAS SE MURIERON ──────────────────────────────────────────
// «Resultado» pasó a ser un link al pie (`/plata/mes`). El margen y el piso son
// el MISMO hecho: uno es un número para interpretar, el otro es el mismo número
// convertido en algo que se hace antes de abrir. Teniendo el segundo, el primero
// no se gana la pantalla de todos los días. Dos piezas de allá sí se la ganaron
// y subieron: el desglose de costos (bloque 6) y los proveedores (bloque 7).
//
// ── LO QUE SE FUE, Y ADÓNDE ───────────────────────────────────────────────
//   · «Vendido hoy» ................ adentro del bloque 1, como fracción del piso
//   · las 4 celdas del flujo ....... adentro del bloque 4, que además dice CUÁNDO
//   · el pulso de comportamiento ... a `/plata/mes` (es para entender, no decidir)
//   · el editor del extracto ....... al bloque 2, arriba y sin botón de por medio
//   · el libro del banco ........... plegado adentro del bloque 2
//
// ── LO QUE SE HACE TODOS LOS DÍAS CUESTA CERO ─────────────────────────────
// Las dos lecturas caras —la nómina persona por persona y el año contra el
// piso— NO salen con la página: se piden la primera vez que alguien las abre.
// Todo lo demás sale una vez, en paralelo, igual que antes.

const nombreMes = (m: number) => MESES[m - 1] ?? `mes ${m}`

/** El último día del mes, en ISO. Aritmética, no una afirmación. */
const finDeMesDe = (anio: number, mes: number) =>
  new Date(anio, mes, 0).toLocaleDateString('en-CA')

export default function Plata() {
  const navigate = useNavigate()
  const hoy = hoyBogota()
  const anio = Number(hoy.slice(0, 4))
  const mes = Number(hoy.slice(5, 7))
  const dia = Number(hoy.slice(8, 10))
  const finDeMes = finDeMesDe(anio, mes)

  const siguiente = useMemo(() => {
    const d = new Date(anio, mes, 1)
    return { anio: d.getFullYear(), mes: d.getMonth() + 1 }
  }, [anio, mes])

  /** Sube con cada mutación de plata: es la dependencia de lo que cambia. */
  const [refresco, setRefresco] = useState(0)
  const refrescarTodo = useCallback(() => setRefresco(n => n + 1), [])

  // ═══════════════════════════════════════════════════════════════════════════
  // LOS DATOS DE LA PÁGINA
  // ═══════════════════════════════════════════════════════════════════════════
  // Cada uno es una `Fuente<T>`, no un `T | null`: el molde viejo
  // (`.catch(() => setX(null))`) hacía que un mismo `null` significara «no
  // llegó», «llegó vacío» y «no volvió», y río abajo cada `?? 0` convertía «no
  // se pudo preguntar» en «la respuesta es cero». El detalle está en
  // `src/api/dato.ts`.
  //
  // El segundo argumento es el nombre EN CASTELLANO que ve el dueño en la
  // franja de arriba cuando ese fetch falla; el tercero, el mensaje para cuando
  // no hubo respuesta (si el backend contestó con `detail`, gana el detail).

  /** EL NÚMERO DE LA PÁGINA. Llega calculado: acá no se divide plata. */
  const piso = useDato<Piso>(
    () => api.get('/costos/piso', { params: { anio, mes } }), 'el piso de venta',
    'No se pudo calcular el piso de venta.', [refresco, anio, mes])

  /**
   * SIN `dias`: el horizonte llega hasta FIN DE MES y no a 30 días que se
   * corren. El colchón que sale de esta serie tiene que mirar la misma ventana
   * que el piso, o son dos respuestas a dos preguntas distintas puestas una al
   * lado de la otra. Y sin `tienda_id`: la cuenta del banco es de la empresa y
   * el arriendo y la nómina no son de ninguna sede.
   */
  const flujo = useDato<Flujo>(
    () => api.get('/costos/flujo'), 'la proyección hasta fin de mes',
    'No se pudo leer la proyección.', [refresco])

  const agenda = useDato<Agenda>(
    () => api.get('/costos/agenda'), 'la agenda de pagos',
    'No se pudo leer la agenda de pagos.', [refresco])

  /**
   * Las obligaciones del mes del piso Y del que viene, en UNA lectura.
   *
   * Contesta dos preguntas con un solo viaje: cuánto del costo de este mes se
   * repite (bloque 6) y qué cuentas de la serie mensual todavía no tienen copia
   * del mes que viene (la tarea de «armar el mes» y el pliegue del pie). Pedir
   * los dos meses por separado serían dos idas y vueltas para la misma tabla.
   */
  const obligaciones = useDato<Listado>(
    () => api.get('/costos/obligaciones', {
      params: {
        desde: `${anio}-${String(mes).padStart(2, '0')}-01`,
        hasta: finDeMesDe(siguiente.anio, siguiente.mes),
        campo_fecha: 'devengo',
      },
    }),
    'los costos fijos', 'No se pudieron leer los costos fijos.',
    [refresco, anio, mes])

  const egresos = useDato<Bandeja>(
    () => api.get('/costos/egresos-sin-adoptar'), 'los egresos sin categorizar',
    'No se pudieron leer los egresos sin categorizar.', [refresco])

  /**
   * LA VENTA DEL DÍA, con el rango de HOY.
   *
   * No se deriva de `/rentabilidad/pulso`: ese endpoint es del MES a la fecha, y
   * rotular sus KPIs como «hoy» sería decidir con un dato que está CERCA del
   * correcto — la familia de error que este módulo viene arrastrando.
   */
  const ventasHoy = useDato<RentabilidadData>(
    () => api.get('/rentabilidad/', { params: { desde: hoy, hasta: hoy } }),
    'la venta de hoy', 'No se pudo leer la venta de hoy.')

  /** Solo por `ventas_diarias`: la venta día por día del mes en curso. */
  const pulso = useDato<PulsoData>(
    () => api.get('/rentabilidad/pulso'), 'la venta día por día',
    'No se pudo leer la venta día por día.')

  const productos = useDato<PorProductoData>(
    () => api.get('/rentabilidad/por-producto'), 'los productos',
    'No se pudieron leer los productos.', [refresco])

  // Los tres catálogos. Antes caían a `[]`, que en un `<select>` se dibuja igual
  // que «no hay ninguna cuenta cargada» — y ahí el dueño concluía que tenía que
  // ir a crear una cuenta que ya existe. No llevan `[refresco]`: no cambian al
  // pagar una obligación.
  const categorias = useDato<Categoria[]>(
    () => api.get('/costos/categorias'), 'las categorías de gasto',
    'No se pudieron leer las categorías.', [refresco])

  const tiendas = useDato<Tienda[]>(
    () => api.get('/auth/tiendas'), 'las sedes', 'No se pudieron leer las sedes.')

  const cuentas = useDato<CuentaBanco[]>(
    () => api.get('/banco/cuentas'), 'las cuentas del banco',
    'No se pudieron leer las cuentas del banco.')

  // El libro tiene su propia llave: teclear un movimiento no puede repedir la
  // página entera y hacer parpadear ocho bloques que nadie tocó.
  const [llaveLibro, setLlaveLibro] = useState(0)
  const libro = useLibro(llaveLibro)

  /** Cambió plata: se repide la página Y el libro. */
  const refrescarPlata = useCallback(() => {
    setLlaveLibro(n => n + 1)
    refrescarTodo()
  }, [refrescarTodo])

  /** Lo que mira la franja de confianza: si algo de esto falló, el dueño lo sabe. */
  const fuentes = useMemo(
    () => [piso, flujo, agenda, obligaciones, egresos, ventasHoy, pulso, productos,
      categorias, tiendas, cuentas],
    [piso, flujo, agenda, obligaciones, egresos, ventasHoy, pulso, productos,
      categorias, tiendas, cuentas])

  // ── Los anclajes: la página no navega, se mueve sola ──────────────────────
  const refHoy = useRef<HTMLDivElement>(null)
  const refPagar = useRef<HTMLDivElement>(null)
  const refFinDeMes = useRef<HTMLDivElement>(null)
  const refSubeElPiso = useRef<HTMLDivElement>(null)
  const refMensual = useRef<HTMLDivElement>(null)

  const [pedidoFocoExtracto, setPedidoFocoExtracto] = useState(0)
  const [facturaObjetivo, setFacturaObjetivo] = useState<number | null>(null)

  const irA = useCallback((r: React.RefObject<HTMLDivElement>) => {
    r.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [])

  /**
   * Al extracto: baja Y le pone el foco al campo.
   *
   * Es un CONTADOR y no un booleano porque el gesto se puede repetir: con un
   * booleano el segundo toque no dispara nada porque el estado ya estaba en
   * `true`. El campo está siempre montado — esto solo le lleva el foco.
   */
  const irAlExtracto = useCallback(() => {
    irA(refHoy)
    setPedidoFocoExtracto(n => n + 1)
  }, [irA])

  const irAPagar = useCallback(() => irA(refPagar), [irA])
  const irASinFecha = useCallback(() => irA(refPagar), [irA])
  const irAFinDeMes = useCallback(() => irA(refFinDeMes), [irA])
  const irASubeElPiso = useCallback(() => irA(refSubeElPiso), [irA])
  const irAlMensual = useCallback(() => irA(refMensual), [irA])
  const irAlDetalleDelMes = useCallback(() => navigate('/plata/mes'), [navigate])

  /** La nómina abierta vive adentro del bloque 6, en un desplegable con id. */
  const irANominaAbierta = useCallback(() => {
    const el = document.getElementById('la-nomina')
    if (el instanceof HTMLDetailsElement) el.open = true
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [])

  // Estable a propósito: el banner de proveedores lo tiene como dependencia de
  // un efecto, y una función nueva en cada render lo haría correr de más.
  const objetivoAtendido = useCallback(() => setFacturaObjetivo(null), [])

  const revisiones = useMemo(
    () => armarRevisiones({
      agenda, flujo, obligaciones, egresos, productos,
      hoy, anioSiguiente: siguiente.anio, mesSiguiente: siguiente.mes,
      irAlExtracto, irAPagar, irASinFecha, irAlDetalleDelMes,
      irAEgresos: irAlDetalleDelMes,
      irANomina: irAlMensual,
      irAArmarElMes: irAlMensual,
    }),
    [agenda, flujo, obligaciones, egresos, productos, hoy, siguiente,
      irAlExtracto, irAPagar, irASinFecha, irAlDetalleDelMes, irAlMensual])

  /**
   * EL DÍA 1 LA PÁGINA CAMBIA DE FORMA.
   *
   * Es el único día del mes en que el pliegue de abajo sube al tope: son las
   * cosas que hay que dejar listas para que el piso y la proyección de todo el
   * mes signifiquen algo. Se mide contra el día del mes en Colombia, no contra
   * el reloj del aparato.
   */
  const esArranqueDeMes = dia <= 2

  const elPliegue = (
    <div ref={refMensual}>
      <UnaVezAlMes
        piso={piso} flujo={flujo} agenda={agenda}
        obligaciones={obligaciones} categorias={categorias}
        anio={anio} mes={mes}
        anioSiguiente={siguiente.anio} mesSiguiente={siguiente.mes}
        arriba={esArranqueDeMes}
        onCambio={refrescarPlata}
        onVerElMesEnDetalle={irAlDetalleDelMes} />
    </div>
  )

  return (
    <div className="space-y-3 pb-8">
      {/* ── La cabecera ────────────────────────────────────────────────────── */}
      <div className="flex items-baseline justify-between gap-2 flex-wrap">
        <h1 className="text-lg font-bold text-warm-700">
          El piso · <span className="uppercase">{nombreMes(mes)} {anio}</span>
        </h1>
        <p className="text-xs text-warm-500">
          {new Date(hoy + 'T00:00:00').toLocaleDateString('es-CO',
            { weekday: 'long', day: 'numeric', month: 'long' })}
        </p>
      </div>

      {/* ── 0 · La franja de confianza ─────────────────────────────────────
             «¿Le puedo creer a esta pantalla?» en un renglón. En el día normal
             NO OCUPA UN PÍXEL: solo aparece si algo se rompió. */}
      <FranjaDeConfianza fuentes={fuentes} />

      {/* EL DÍA 1, y solo el día 1, esto va arriba de todo. */}
      {esArranqueDeMes && elPliegue}

      {/* ── 1 · El piso ────────────────────────────────────────────────────── */}
      <BloqueElPiso
        piso={piso} ventasHoy={ventasHoy} pulso={pulso}
        onCargarCosto={irASubeElPiso}
        onVerProductosSinCosto={irAlDetalleDelMes} />

      {/* ── 2 · Hoy ────────────────────────────────────────────────────────── */}
      <div ref={refHoy}>
        <BloqueHoy
          libro={libro.libroConHoy} hoy={hoy} cuentas={cuentas} agenda={agenda}
          revisiones={revisiones}
          pedidoFocoExtracto={pedidoFocoExtracto}
          onAnclaGuardada={refrescarPlata}
          onMovimientoGuardado={m => { libro.irALaFechaDe(m.fecha); refrescarPlata() }}
          onRecargarLibro={libro.recargar}
          elLibro={
            <BannerLibro
              libro={libro.libro} serie={libro.serie} anio={libro.anio} mes={libro.mes}
              hoy={libro.hoy} viendoElMesDeHoy={libro.viendoElMesDeHoy}
              cuentas={cuentas} agenda={agenda}
              itemPagando={null}
              onIrAlMes={libro.irAlMes} onIrAHoy={libro.irAHoy} onVerMes={libro.setMes}
              onCambiarAnio={d => libro.setAnio(a => a + d)}
              onGuardado={m => { libro.irALaFechaDe(m.fecha); refrescarPlata() }}
              onBorrado={refrescarPlata}
              onRecargarLibro={libro.recargar}
              onIrAlAncla={irAlExtracto}
              /* Los vencimientos se pagan en el bloque 4, que es la ÚNICA lista:
                 dos formularios de pago abiertos con el mismo saldo son la forma
                 más fácil de pagar dos veces, y `registrar_pago` del backend no
                 valida contra el saldo. Desde acá se baja hasta la fila. */
              onPagar={irAPagar}
              renderPago={() => null} />
          } />
      </div>

      {/* ── 3 · Cuánta plata hay ───────────────────────────────────────────── */}
      <BloqueCuantaPlata
        flujo={flujo} agenda={agenda} tiendas={tiendas} hoy={hoy}
        onVerDondeEsta={irAlExtracto}
        onVerLaLista={irAPagar} />

      {/* ── 4 · Lo que hay que pagar ───────────────────────────────────────── */}
      <div ref={refPagar}>
        <BloqueLoQueHayQuePagar
          agenda={agenda} cuentas={cuentas} hoy={hoy} finDeMes={finDeMes}
          onCambio={refrescarPlata}
          onPagarFactura={setFacturaObjetivo}
          onVerNomina={irANominaAbierta} />
      </div>

      {/* ── 5 · ¿Llega a fin de mes? ───────────────────────────────────────── */}
      <div ref={refFinDeMes}>
        <BloqueFinDeMes
          flujo={flujo} agenda={agenda} piso={piso} pulso={pulso}
          onCambiarReserva={irAlMensual}
          onANomina={irAlMensual}
          onASinFecha={irAPagar} />
      </div>

      {/* ── 6 · Lo que sube el piso ────────────────────────────────────────── */}
      <div ref={refSubeElPiso}>
        <BloqueSubeElPiso
          piso={piso} obligaciones={obligaciones} egresos={egresos}
          anio={anio} mes={mes}
          onClasificar={irAlDetalleDelMes}
          /* El gestor de costos fijos entero, plegado adentro del bloque. Es el
             único lugar donde se puede cargar un costo, corregirlo, anularlo,
             anular un pago mal registrado y ver las anuladas. Se monta acá y no
             como banner propio porque es exactamente «lo que sube el piso»
             visto de cerca. */
          elGestor={
            <BannerObligaciones
              categorias={categorias} tiendas={tiendas} cuentas={cuentas}
              onCambio={refrescarPlata} refreshKey={refresco} />
          } />
      </div>

      {/* ── 7 · Lo que baja el margen ──────────────────────────────────────
             El bloque de proveedores va ADENTRO: a quién se le compra es la
             misma pregunta que qué está bajando el margen, y era el ÚNICO
             camino real para pagarle a un proveedor (`PATCH /facturas/{id}/pago`
             — `POST /costos/pagos` con `factura_id` guarda el pago pero no mueve
             el saldo de la factura). Se mueve entero, no se reescribe. */}
      <BloqueBajaElMargen
        piso={piso} productos={productos}
        onCargarComision={irAlMensual}>
        <div className="border-t border-warm-100">
          <BannerProveedores
            tiendas={tiendas}
            facturaObjetivo={facturaObjetivo}
            onObjetivoAtendido={objetivoAtendido}
            onCambio={refrescarPlata} />
        </div>
      </BloqueBajaElMargen>

      {/* ── 8 · El año, contra el piso ─────────────────────────────────────
             Plegado y con su propia lectura: son dos pedidos por mes y eso no
             puede salir con la página. */}
      <BloqueElAnio anio={anio} hastaMes={mes} />

      {/* ── El pliegue del pie, salvo el día 1 (que ya lo dibujó arriba) ──── */}
      {!esArranqueDeMes && elPliegue}

      {/* La página no navega a ninguna parte, salvo acá. */}
      <button onClick={irAlDetalleDelMes}
        className="w-full min-h-[46px] text-xs font-bold text-forest hover:underline text-left px-1">
        → El mes en detalle: margen por producto, sede contra sede
      </button>

      <p className="text-[11px] text-warm-400 px-1 leading-relaxed">
        El piso es del <b>negocio entero</b>. Nunca hay un piso por sede: el arriendo y la nómina
        no son de ninguna sede, y partirlos daría un piso más chico que el real en las dos sedes a
        la vez.
      </p>
    </div>
  )
}
