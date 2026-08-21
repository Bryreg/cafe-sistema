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
import type { Impoconsumo, PalancasData, Piso } from '../components/piso/tipos'
import { armarRevisiones } from '../components/piso/pendientes'
import BloqueEquilibrio from '../components/piso/BloqueEquilibrio'
import BloqueCajaYResultado from '../components/piso/BloqueCajaYResultado'
import BloqueHoy from '../components/piso/BloqueHoy'
import BloqueCuantaPlata from '../components/piso/BloqueCuantaPlata'
import BloqueLoQueHayQuePagar from '../components/piso/BloqueLoQueHayQuePagar'
import BloqueFinDeMes from '../components/piso/BloqueFinDeMes'
import BloqueSubeElPiso from '../components/piso/BloqueSubeElPiso'
import BloqueBajaElMargen from '../components/piso/BloqueBajaElMargen'
import BloqueElAnio from '../components/piso/BloqueElAnio'
import UnaVezAlMes from '../components/piso/UnaVezAlMes'

// ═════════════════════════════════════════════════════════════════════════════
// LA PLATA — una página que se va llenando día a día, un solo scroll
// ═════════════════════════════════════════════════════════════════════════════
// El dueño abre esto temprano, antes de abrir el local, en una tablet. Tiene que
// saber en treinta segundos si llega a fin de mes. El protagonista es EL LIBRO
// —la hoja de su Excel, día por día: arranca + entra − sale = queda— y alrededor
// los bloques contestan sus tres preguntas en orden:
//
//   REGISTRAR 1 · hoy y el libro     2 · cuánta plata hay
//   PROYECTAR 3 · qué hay que pagar  4 · ¿llega a fin de mes?  5 · dos números
//   ENTENDER  6 · el equilibrio  7 · lo que lo sube  8 · lo que baja el margen
//             9 · el año
//
// ── EL PISO SE RETIRÓ, EL EQUILIBRIO QUEDÓ (decisión del dueño) ───────────
// «No quiero manejar más el piso; solo quiero saber el punto de equilibrio para
// cada sede, pero que no me amarre las ventas a un número». El cálculo es el
// mismo; lo que se fue es el VEREDICTO diario («hoy tenés que vender $X»). El
// bloque 6 lo cuenta entero.
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

  // «La venta de hoy» (rango desde=hasta=hoy) se fue con el veredicto del piso:
  // era el numerador de «vendido hoy contra el piso de hoy», y sin sentencia
  // diaria no queda quién la mire. El pulso del mes sigue abajo.

  /** Solo por `ventas_diarias`: la venta día por día del mes en curso. */
  const pulso = useDato<PulsoData>(
    () => api.get('/rentabilidad/pulso'), 'la venta día por día',
    'No se pudo leer la venta día por día.')

  const productos = useDato<PorProductoData>(
    () => api.get('/rentabilidad/por-producto'), 'los productos',
    'No se pudieron leer los productos.', [refresco])

  /**
   * LAS PALANCAS: qué subió, QUIÉN lo subió y cuánto le sube el piso por día.
   *
   * Va aparte de `/costos/piso` porque el bloque del año pide ese endpoint DOCE
   * veces y el reparto del costo por insumo no tiene por qué correr doce veces.
   * Adentro mide contra el MISMO piso de este mes: no es una segunda cuenta del
   * número, es una diferencia contra el que ya se publicó.
   */
  const palancas = useDato<PalancasData>(
    () => api.get('/costos/palancas', { params: { anio, mes } }),
    'las subas de precio', 'No se pudieron leer las subas de precio.',
    [refresco, anio, mes])

  /**
   * LA DECLARACIÓN DEL IMPOCONSUMO DEL BIMESTRE CERRADO.
   *
   * 7,41% de cada peso facturado es de la DIAN. El sistema ya lo descontaba en
   * todos lados —la venta neta, el margen, el piso— pero como PLATA A PAGAR EN
   * UNA FECHA no aparecía en ninguna pantalla: se veía como menos venta todos los
   * días y después aparecía de golpe cada dos meses.
   *
   * SIN parámetros: el bimestre a declarar es siempre el último CERRADO y lo
   * decide el backend. Mandarle un año/mes desde acá abriría la puerta a que la
   * pantalla y el server discrepen sobre cuál es. Y no cuesta un P&L cuando no
   * hay nada que declarar: el backend corta antes.
   */
  const impoconsumo = useDato<Impoconsumo>(
    () => api.get('/costos/impoconsumo'), 'la declaración del impoconsumo',
    'No se pudo leer la declaración del impoconsumo.', [refresco])

  // Los tres catálogos. Antes caían a `[]`, que en un `<select>` se dibuja igual
  // que «no hay ninguna cuenta cargada» — y ahí el dueño concluía que tenía que
  // ir a crear una cuenta que ya existe. No llevan `[refresco]`: no cambian al
  // pagar una obligación.
  const categorias = useDato<Categoria[]>(
    () => api.get('/costos/categorias'), 'las categorías de gasto',
    'No se pudieron leer las categorías.', [refresco])

  /**
   * El catálogo COMPLETO para el libro: café + personales + banco. Es otra
   * lectura y no un filtro de la de arriba a propósito: la de arriba alimenta
   * los formularios de OBLIGACIONES, donde una categoría personal o del banco
   * no puede aparecer nunca — servir las dos preguntas con una lista y filtrar
   * en el cliente es exactamente cómo se cuela la que no va. Un servidor viejo
   * ignora `ambito` y devuelve solo café: el select del libro ofrece menos
   * opciones un rato, sin mentir.
   */
  const categoriasLibro = useDato<Categoria[]>(
    () => api.get('/costos/categorias', { params: { ambito: 'todas' } }),
    'las categorías del libro',
    'No se pudieron leer las categorías del libro.', [refresco])

  /**
   * EL RESULTADO del mes en curso (del 1 a hoy), para el bloque de los dos
   * números: la caja sale del libro, esto es la otra mitad — si el café va
   * ganando o perdiendo. Ventana explícita: `/rentabilidad/` sin parámetros ya
   * es el mes actual, pero escribirla acá deja el par caja/resultado midiendo
   * A OJOS VISTA la misma ventana.
   */
  const rentMes = useDato<RentabilidadData>(
    () => api.get('/rentabilidad/', {
      params: { desde: `${anio}-${String(mes).padStart(2, '0')}-01`, hasta: hoy },
    }),
    'el resultado del mes', 'No se pudo leer el resultado del mes.',
    [refresco, anio, mes])

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
    () => [piso, flujo, agenda, obligaciones, egresos, pulso, productos,
      palancas, impoconsumo, categorias, categoriasLibro, rentMes, tiendas, cuentas],
    [piso, flujo, agenda, obligaciones, egresos, pulso, productos,
      palancas, impoconsumo, categorias, categoriasLibro, rentMes, tiendas, cuentas])

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
      agenda, flujo, obligaciones, egresos, productos, impoconsumo,
      hoy, anioSiguiente: siguiente.anio, mesSiguiente: siguiente.mes,
      irAlExtracto, irAPagar, irASinFecha, irAlDetalleDelMes,
      irAEgresos: irAlDetalleDelMes,
      irANomina: irAlMensual,
      irAArmarElMes: irAlMensual,
      // El impoconsumo manda al pliegue y no dispara nada solo, porque allá hay
      // DOS botones que hacen cosas distintas: «ya la declaré» apaga el
      // recordatorio del TRÁMITE y «meterla en lo que hay que pagar» reserva la
      // PLATA. Se puede declarar sin haber pagado, así que el primero no puede
      // hacer el trabajo del segundo.
      //
      // Acá decía que agendarla «contaría la misma plata dos veces» y eso dejó
      // de ser cierto: la declaración SÍ se agenda, en una categoría dedicada
      // que el P&L excluye POR CLAVE, y está medido que no mueve el piso ni el
      // margen (delta $0,00 exacto) mientras la agenda y la proyección de caja
      // sí la ven. Lo que contaba dos veces era cargarla como costo de
      // 'impuestos', que es grupo fijo y entra al numerador del piso; eso sigue
      // prohibido y ahora lo rechaza el server. El mismo párrafo, ya corregido,
      // está en `pendientes.ts` — dos comentarios sobre la misma decisión no
      // pueden decir cosas opuestas.
      irAlImpoconsumo: irAlMensual,
    }),
    [agenda, flujo, obligaciones, egresos, productos, impoconsumo, hoy, siguiente,
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
        impoconsumo={impoconsumo}
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
          La plata · <span className="uppercase">{nombreMes(mes)} {anio}</span>
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

      {/* ── 1 · Hoy y el libro — la hoja que se va llenando ────────────────── */}
      <div ref={refHoy}>
        <BloqueHoy
          libro={libro.libroConHoy} hoy={hoy} cuentas={cuentas} agenda={agenda}
          categorias={categoriasLibro} onCategoriaCreada={refrescarTodo}
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
              categorias={categoriasLibro} onCategoriaCreada={refrescarTodo}
              itemPagando={null}
              onIrAlMes={libro.irAlMes} onIrAHoy={libro.irAHoy} onVerMes={libro.setMes}
              onCambiarAnio={d => libro.setAnio(a => a + d)}
              onGuardado={m => { libro.irALaFechaDe(m.fecha); refrescarPlata() }}
              onBorrado={refrescarPlata}
              onRecargarLibro={libro.recargar}
              onIrAlAncla={irAlExtracto}
              /* Los vencimientos se pagan en el bloque 3, que es la ÚNICA lista:
                 dos formularios de pago abiertos con el mismo saldo son la forma
                 más fácil de pagar dos veces, y `registrar_pago` del backend no
                 valida contra el saldo. Desde acá se baja hasta la fila. */
              onPagar={irAPagar}
              renderPago={() => null} />
          } />
      </div>

      {/* ── 2 · Cuánta plata hay ───────────────────────────────────────────── */}
      <BloqueCuantaPlata
        flujo={flujo} agenda={agenda} tiendas={tiendas} hoy={hoy}
        onVerDondeEsta={irAlExtracto}
        onVerLaLista={irAPagar} />

      {/* ── 3 · Lo que hay que pagar ───────────────────────────────────────── */}
      <div ref={refPagar}>
        <BloqueLoQueHayQuePagar
          agenda={agenda} cuentas={cuentas} hoy={hoy} finDeMes={finDeMes}
          onCambio={refrescarPlata}
          onPagarFactura={setFacturaObjetivo}
          onVerNomina={irANominaAbierta} />
      </div>

      {/* ── 4 · ¿Llega a fin de mes? ───────────────────────────────────────── */}
      <div ref={refFinDeMes}>
        <BloqueFinDeMes
          flujo={flujo} agenda={agenda} piso={piso} pulso={pulso}
          onCambiarReserva={irAlMensual}
          onAlMensual={irAlMensual}
          onASinFecha={irAPagar} />
      </div>

      {/* ── 5 · El mes en dos números: la caja y el resultado ──────────────── */}
      <BloqueCajaYResultado
        libro={libro.libroConHoy} rentMes={rentMes}
        onRecargarLibro={libro.recargar} />

      {/* ── 6 · El punto de equilibrio ─────────────────────────────────────── */}
      <BloqueEquilibrio piso={piso} onCargarCosto={irASubeElPiso} />

      {/* ── 7 · Lo que sube el equilibrio ──────────────────────────────────── */}
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

      {/* ── 8 · Lo que baja el margen ──────────────────────────────────────
             El bloque de proveedores va ADENTRO: a quién se le compra es la
             misma pregunta que qué está bajando el margen, y es el ÚNICO
             camino real para pagarle a un proveedor (`PATCH /facturas/{id}/pago`
             — `POST /costos/pagos` con `factura_id` ahora contesta 400 con el
             motivo). Se mueve entero, no se reescribe. */}
      <BloqueBajaElMargen
        piso={piso} palancas={palancas}
        onCargarComision={irAlMensual}>
        <div className="border-t border-warm-100">
          <BannerProveedores
            tiendas={tiendas}
            facturaObjetivo={facturaObjetivo}
            onObjetivoAtendido={objetivoAtendido}
            onCambio={refrescarPlata} />
        </div>
      </BloqueBajaElMargen>

      {/* ── 9 · El año, contra el equilibrio ───────────────────────────────
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
        El equilibrio se muestra en <b>tres números</b> — lo de Vida, lo de Palmetto y lo
        corporativo que las dos cubren entre las dos — y nunca se prorratea: repartir el arriendo
        de la nómina corporativa entre sedes daría un número más chico que el real en las dos a
        la vez.
      </p>
    </div>
  )
}
