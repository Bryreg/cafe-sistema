import { useCallback, useMemo, useRef, useState } from 'react'
import { AlertCircle } from 'lucide-react'
import { mapDato } from '../../api/dato'
import type { Fuente } from '../../api/useDato'
import { SegunDato, NoSeSabe } from '../ui'
import { CuentaBanco, plata } from './banco'
import { Agenda, AgendaItem, Categoria, Flujo, Tienda } from './tipos'
import { PulsoData, RentabilidadData } from '../rentabilidad/helpers'
import { useLibro } from './useLibro'
import BannerVentasHoy from './BannerVentasHoy'
import BannerSaldos from './BannerSaldos'
import BannerFlujo from './BannerFlujo'
import BannerObligaciones from './BannerObligaciones'
import BannerProveedores from './BannerProveedores'
import BannerLibro from './BannerLibro'
import FilaVencimiento from './FilaVencimiento'
import FormPagoObligacion from './FormPagoObligacion'

/**
 * ═════════════════════════════════════════════════════════════════════════════
 * «LA PLATA» — ¿ME ALCANZA?
 * ═════════════════════════════════════════════════════════════════════════════
 * UNA página, siete banners, cero cajones. El orden no es estético: va de lo
 * urgente a lo que se consulta.
 *
 *   1. Vendido hoy ......... la plata que entra mañana
 *   2. ¿Cuánta plata hay? .. banco + registradoras, con el extracto editable acá
 *   3. Vencido ............. lo que se debe AHORA, con el botón de pagar al lado
 *   4. ¿Me alcanza? ........ la proyección y el día del quiebre
 *   5. Obligaciones ........ el arriendo y la nómina, con la carga a la vista
 *   6. Proveedores ......... plata que vence, sin esconder (pedido textual)
 *   7. El libro del banco .. lo que ya se movió, con la carga a la vista
 *
 * ── LO QUE SE FUE, Y ADÓNDE ────────────────────────────────────────────────
 * Los cuatro cajones (Obligaciones, Pagos a proveedores, Flujo, Egresos sin
 * categorizar) y los ocho modales dejaron de existir como MECANISMO. Su
 * contenido está entero: tres subieron a banner acá y el de egresos bajó al
 * banner de costos de «Resultado», que es donde se hace la pregunta.
 *
 * ── LA COSTURA ENTRE BANNERS ───────────────────────────────────────────────
 * Cuando algo se toca en un banner, el resto de la página tiene que enterarse:
 * pagar una obligación cambia la agenda, el punto de quiebre Y el resultado del
 * mes. Por eso las mutaciones llaman a `onCambio`, que repide lo de la página, y
 * el libro se recarga con su propia llave. Sin eso quedaban dos números para la
 * misma pregunta, con el optimista adelante.
 *
 * ── CADA BANNER RECIBE LA `Fuente` ENTERA ──────────────────────────────────
 * No un `T | null`: el sobre completo, con su estado, su nombre en castellano y
 * su `recargar`. Así cada banner tiene su propio «Reintentar» sin cablear un
 * callback por recurso desde acá, y el dueño no pierde lo que estaba tecleando
 * para volver a pedir lo único que falló. El detalle está en `src/api/dato.ts`.
 */
export default function LaPlataView({
  agenda, flujo, pulso, ventasHoy, categorias, tiendas, cuentas, onCambio,
}: {
  agenda: Fuente<Agenda>
  flujo: Fuente<Flujo>
  pulso: Fuente<PulsoData>
  ventasHoy: Fuente<RentabilidadData>
  categorias: Fuente<Categoria[]>
  tiendas: Fuente<Tienda[]>
  cuentas: Fuente<CuentaBanco[]>
  /** Repide agenda, flujo y lo que cuelga de ellos. */
  onCambio: () => void
}) {
  // El libro se recarga con su propia llave para no repedir toda la página cada
  // vez que se teclea un movimiento.
  const [llaveLibro, setLlaveLibro] = useState(0)
  const libro = useLibro(llaveLibro)

  const [pagando, setPagando] = useState<AgendaItem | null>(null)
  const [facturaObjetivo, setFacturaObjetivo] = useState<number | null>(null)
  const [pedidoAncla, setPedidoAncla] = useState(0)
  /** Aviso que sube desde el formulario de pago: ahí abajo muere al cerrarse. */
  const [avisoPago, setAvisoPago] = useState('')
  const refSaldos = useRef<HTMLDivElement>(null)

  /** Cambió plata: se repide la página Y el libro. */
  const refrescarTodo = useCallback(() => {
    setLlaveLibro(n => n + 1)
    onCambio()
  }, [onCambio])

  /**
   * Pagar desde cualquier banner.
   *
   * La factura NO se paga con el formulario de obligaciones: `POST /costos/pagos`
   * con `factura_id` guarda el pago pero NO mueve `FacturaCompra.valor_pagado`,
   * así que el saldo quedaría igual. Se baja hasta su fila en el banner de
   * proveedores, que usa `PATCH /facturas/{id}/pago` — el único camino real.
   */
  const pedirPago = useCallback((i: AgendaItem) => {
    if (i.tipo === 'factura') { setPagando(null); setFacturaObjetivo(i.id); return }
    setPagando(p => (p && p.id === i.id && p.tipo === i.tipo ? null : i))
  }, [])

  const irAlAncla = useCallback(() => {
    setPedidoAncla(n => n + 1)
    refSaldos.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [])

  // Estable a propósito: el banner de proveedores lo tiene como dependencia de
  // un efecto, y una función nueva en cada render lo haría correr de más.
  const objetivoAtendido = useCallback(() => setFacturaObjetivo(null), [])

  /**
   * Lo vencido, ordenado por fecha: lo más viejo arriba, con su total.
   *
   * Va junto porque el rótulo («N pagos con la fecha pasada») y la cifra de la
   * derecha son la misma afirmación dicha dos veces: si una se puede escribir,
   * la otra también, y si no, ninguna.
   */
  const loVencido = useMemo(() => mapDato(agenda.dato, a => ({
    items: a.items.filter(i => i.vencida).sort((x, y) => x.fecha.localeCompare(y.fecha)),
    total: a.totales.vencido,
  })), [agenda.dato])

  const clavePagando = pagando ? `${pagando.tipo}-${pagando.id}` : null

  /** El formulario de pago, montado justo debajo de la fila que lo pidió. */
  const formularioPago = (i: AgendaItem) => (
    clavePagando === `${i.tipo}-${i.id}` && i.tipo === 'obligacion' ? (
      <FormPagoObligacion key={`pg-${i.id}`}
        obligacionId={i.id}
        concepto={i.concepto}
        detalle={[i.categoria_nombre || 'Costo fijo', i.tienda_nombre || 'Corporativo',
          i.beneficiario || ''].filter(Boolean).join(' · ')}
        saldo={i.monto}
        cuentas={cuentas}
        onCancelar={() => setPagando(null)}
        onPagado={av => {
          setPagando(null); refrescarTodo()
          // El pago quedó pero la salida del banco falló. El mensaje viene de
          // abajo porque el formulario se desmonta en este mismo render.
          setAvisoPago(av || '')
        }} />
    ) : null
  )

  return (
    <div className="space-y-3">
      {/* El pago se guardó pero el libro no se movió: es el único caso donde el
          dueño tiene que hacer algo a mano, así que va arriba de todo y no se
          va solo — lo cierra él cuando lo leyó. */}
      {avisoPago && (
        <div className="flex items-start gap-2 rounded-2xl border border-gold-200 bg-gold-50 px-3 py-2.5">
          <p className="flex-1 text-xs text-gold-700 leading-relaxed">{avisoPago}</p>
          <button onClick={() => setAvisoPago('')}
            className="shrink-0 text-[11px] font-bold text-gold-700 underline decoration-dotted">
            Entendido
          </button>
        </div>
      )}

      {/* 1 · La venta del día */}
      <BannerVentasHoy ventasHoy={ventasHoy} pulso={pulso} />

      {/* 2 · Cuánta plata hay, y el extracto editable en la misma tarjeta */}
      <div ref={refSaldos}>
        <BannerSaldos libro={libro.libroConHoy} hoy={libro.hoy}
          flujo={flujo} cuentas={cuentas}
          pedidoApertura={pedidoAncla}
          onAnclaGuardada={refrescarTodo}
          onRecargarLibro={libro.recargar} />
      </div>

      {/* 3 · Vencido: arriba, aparte y primero. No es «el pasado»: es lo que se
             debe HOY, y no depende del mes que se esté mirando en el libro.

             EL HUECO OCUPA LUGAR A PROPÓSITO. La sección estaba condicionada a
             `vencidos.length > 0` con `vencidos` saliendo de `agenda?.items ?? []`:
             con la agenda caída el banner rojo NO APARECÍA, y una pantalla sin
             banner rojo dice «no hay nada atrasado» tan claro como si lo
             escribiera. Es la mentira más cara de la página, así que en su lugar
             va una caja del mismo peso visual. */}
      <SegunDato
        dato={loVencido}
        cargando={null}
        falla={m => (
          <NoSeSabe bloque onReintentar={agenda.recargar}
            mensaje={`${m} — no se sabe si hay pagos atrasados. Que no aparezca el bloque rojo `
              + 'de siempre no quiere decir que estés al día.'} />
        )}
        listo={v => v.items.length === 0 ? null : (
          <section className="rounded-2xl border border-danger-200 bg-danger-50 overflow-hidden">
            <div className="flex items-center gap-2 px-4 py-2.5 border-b border-danger-200/60">
              <AlertCircle size={16} className="text-danger-600 shrink-0" />
              <div className="min-w-0 flex-1">
                <h2 className="text-sm font-bold text-danger-700">Vencido — pagalo ya</h2>
                <p className="text-[11px] text-danger-700/90">
                  {v.items.length} {v.items.length === 1 ? 'pago' : 'pagos'} con la fecha pasada
                </p>
              </div>
              <span className="font-mono font-bold text-sm text-danger-700 tabular-nums shrink-0">
                {plata(v.total)}
              </span>
            </div>
            <div className="divide-y divide-danger-200/40 bg-white/60">
              {v.items.map(i => (
                <div key={`v-${i.tipo}-${i.id}`}>
                  <FilaVencimiento item={i} onPagar={pedirPago}
                    activo={clavePagando === `${i.tipo}-${i.id}`} />
                  {formularioPago(i)}
                </div>
              ))}
            </div>
          </section>
        )}
      />

      {/* 4 · La proyección */}
      <BannerFlujo agenda={agenda} flujo={flujo} onActualizarExtracto={irAlAncla} />

      {/* 5 · Obligaciones, con la carga a la vista */}
      {/* `llaveLibro` viaja TAMBIÉN acá. Los banners conviven en una sola
          página, así que pagar una obligación desde «Vencido» o desde un día
          del libro tiene que actualizar esta lista: sin la señal, seguía
          mostrando el saldo viejo y ofreciendo «Registrar pago» precargado con
          el monto entero. Y `registrar_pago` del backend no valida contra el
          saldo, así que ese segundo pago se guardaba y la obligación quedaba
          sobrepagada. La dirección inversa ya funcionaba —pagar desde la lista
          llama a `onCambio`—, que es lo que delataba que faltaba este lado. */}
      <BannerObligaciones categorias={categorias} tiendas={tiendas} cuentas={cuentas}
        agenda={agenda} onCambio={refrescarTodo} refreshKey={llaveLibro} />

      {/* 6 · Proveedores: plata que vence, sin esconder */}
      <BannerProveedores tiendas={tiendas} facturaObjetivo={facturaObjetivo}
        onObjetivoAtendido={objetivoAtendido} onCambio={refrescarTodo} />

      {/* 7 · El libro, con la carga a la vista */}
      <BannerLibro
        libro={libro.libro} serie={libro.serie} anio={libro.anio} mes={libro.mes}
        hoy={libro.hoy} viendoElMesDeHoy={libro.viendoElMesDeHoy}
        cuentas={cuentas} agenda={agenda}
        itemPagando={clavePagando}
        onIrAlMes={libro.irAlMes} onIrAHoy={libro.irAHoy} onVerMes={libro.setMes}
        onCambiarAnio={d => libro.setAnio(a => a + d)}
        onGuardado={m => { libro.irALaFechaDe(m.fecha); refrescarTodo() }}
        onBorrado={refrescarTodo}
        onRecargarLibro={libro.recargar}
        onIrAlAncla={irAlAncla}
        onPagar={pedirPago}
        renderPago={formularioPago} />

      {/* Con la agenda vacía la pantalla explicaría poco: se dice qué la llena.
          VIVE ADENTRO DE `listo` porque es una AFIRMACIÓN sobre la base de datos
          («no hay nada agendado»), no una descripción de la pantalla. Antes salía
          con `!cargandoPagos && items.length === 0`, y ese `items` era
          `agenda?.items ?? []`: con la agenda caída el párrafo aparecía y le
          explicaba al dueño cómo llenar una agenda que quizás estaba llena. */}
      <SegunDato
        dato={agenda.dato}
        cargando={null}
        falla={() => null}
        listo={a => a.items.length > 0 || a.sin_fecha.length > 0 ? null : (
          <p className="text-[11px] text-warm-500 px-1 leading-relaxed">
            No hay nada agendado todavía. El arriendo, la nómina y los servicios se cargan en el
            banner de <b>Obligaciones</b>; las facturas de proveedor traen su plazo desde el banner
            de <b>proveedores</b>. Sin nada agendado, la proyección solo sabe de la plata que entra.
          </p>
        )}
      />
    </div>
  )
}
