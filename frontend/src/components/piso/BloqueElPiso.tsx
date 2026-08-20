import { ReactNode, useMemo } from 'react'
import { AlertTriangle } from 'lucide-react'
import { Dato, ambos, mapDato } from '../../api/dato'
import type { Fuente } from '../../api/useDato'
import { SegunDato, NoSeSabe } from '../ui'
import { MESES, plata } from '../plata/banco'
import { fmtTasa } from '../rentabilidad/helpers'
import type { PulsoData, RentabilidadData } from '../rentabilidad/helpers'
import type { Piso, SesgoPiso } from './tipos'
import { detalleNum, diasContraElPiso, sesgosActivos } from './calculo'

// ═════════════════════════════════════════════════════════════════════════════
// 1 · EL PISO — el primer bloque, sin scrollear
// ═════════════════════════════════════════════════════════════════════════════
// Es el mismo hecho que el margen, convertido en una DECISIÓN. «Margen 53%» es
// un número para interpretar; «hoy hay que vender $2.340.000» es algo que se
// puede hacer antes de abrir el local.
//
// ── ESTA PANTALLA NO CALCULA EL PISO ───────────────────────────────────────
// `piso_mes`, `piso_hoy`, `falta`, el margen y el piso de caja llegan hechos de
// `GET /costos/piso`. Acá no hay una sola división de plata: dividir de nuevo
// sería tener dos matemáticas para el mismo número, con la optimista adelante.
//
// ── LAS PUERTAS LAS DECIDE EL BACKEND ──────────────────────────────────────
// `puerta` viene en la respuesta y este archivo DIBUJA una rama por cada valor,
// sin inventar un portón nuevo ni deducir el estado de un `null`. El `switch`
// de `cuerpoDe` no tiene `default` a propósito: el día que aparezca una sexta
// puerta, el build se rompe acá y no en la tablet del dueño.
//
// ── Y NUNCA DESAPARECE ─────────────────────────────────────────────────────
// Cuando el piso de resultado no se puede decir, en su lugar va un hueco DEL
// MISMO TAMAÑO con su nombre y el botón que lo destraba. Un bloque que se
// evapora se lee como «no hay nada que vender hoy», que es la conclusión más
// cara posible a las siete de la mañana.

/** Plata «de cada $100», con dos decimales: el impoconsumo es $7,41, no $7. */
const porCien = (frac: number) => {
  const v = frac * 100
  const dec = Math.abs(v) < 10 ? 2 : 0
  return '$' + v.toLocaleString('es-CO', { minimumFractionDigits: dec, maximumFractionDigits: dec })
}

const nombreMes = (m: number) => MESES[m - 1] ?? `mes ${m}`

/** El número grande. `apagado` = no hay cifra: gris, para que no se lea como dato. */
function Titular({ rotulo, valor, apagado = false, pie }: {
  rotulo: ReactNode; valor: ReactNode; apagado?: boolean; pie?: ReactNode
}) {
  return (
    <div>
      <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500 leading-snug">
        {rotulo}
      </p>
      <p className={`text-4xl sm:text-5xl font-bold font-mono tabular-nums leading-none mt-1.5 ${
        apagado ? 'text-warm-400' : 'text-warm-700'}`}>
        {valor}
      </p>
      {pie && <div className="mt-1.5">{pie}</div>}
    </div>
  )
}

/**
 * La barra de «van X de Y».
 *
 * Solo se dibuja con los DOS números en la mano. Con la venta de hoy caída, una
 * barra vacía diría «no vendiste nada» y una barra llena diría lo contrario:
 * las dos son afirmaciones sobre un dato que no volvió, así que no hay barra.
 */
function Progreso({ hecho, meta }: { hecho: number; meta: number }) {
  // `meta <= 0` pasa de verdad: cuando el piso del mes ya está cubierto, lo que
  // falta por día es cero o negativo. Ahí la barra va LLENA, porque `hecho` ya
  // superó la meta — y no en cero, que es lo que daba un `?? 0` sobre la
  // división imposible y dibujaba una barra vacía debajo del texto «ya pasaste
  // el piso de hoy». Dos afirmaciones opuestas en el mismo renglón.
  const pct = meta > 0
    ? Math.max(0, Math.min(100, Math.round((hecho / meta) * 100)))
    : 100
  return (
    <div className="mt-3">
      <p className="text-sm text-warm-600">
        Van <b className="font-mono tabular-nums">{plata(hecho)}</b>
        {hecho < meta
          ? <> · faltan <b className="font-mono tabular-nums text-warm-700">{plata(meta - hecho)}</b></>
          : <> · <b className="text-success-700">ya pasaste el piso de hoy</b></>}
      </p>
      <div className="mt-1.5 h-2.5 rounded-full bg-warm-100 overflow-hidden">
        <div
          className={`h-full rounded-full ${hecho >= meta ? 'bg-success-500' : 'bg-clay'}`}
          style={{ width: `${pct}%` }} />
      </div>
      <p className="text-[11px] text-warm-500 mt-1 font-mono tabular-nums">{pct}%</p>
    </div>
  )
}

/**
 * LA BANDA QUE NOMBRA LOS SESGOS. Es lo que le da sentido al rótulo «al menos».
 *
 * Los sesgos del backend empujan TODOS para el mismo lado: inflan lo que queda
 * de cada peso, o sea BAJAN el piso. Decir «al menos» sin decir POR QUÉ deja al
 * dueño con un número que no sabe si creer; decir para qué lado está corto lo
 * convierte en un piso usable.
 *
 * CUÁNTOS SON LO DECIDE EL BACKEND, no esta banda: el de los desechables se
 * apaga cuando toda la venta medida tiene su empaque cargado, y la frase se arma
 * con los que llegaron activos. Por eso no hay ningún «cuatro» quemado acá.
 *
 * Si no hay ninguno activo la banda no se dibuja — y eso NO es un verde: el
 * rótulo «al menos» del titular sigue estando, porque lo manda el backend.
 */
function BandaAlMenos({ sesgos, onVerProductos }: {
  sesgos: SesgoPiso[]; onVerProductos: () => void
}) {
  if (sesgos.length === 0) return null

  const sinCosto = sesgos.find(s => s.clave === 'productos_sin_costo')
  const ventaSinCostear = sinCosto ? detalleNum(sinCosto.detalle, 'venta_sin_costear') : null

  return (
    <div className="mt-3 flex items-start gap-2 rounded-xl border border-gold-200 bg-gold-50 px-3 py-2.5">
      <AlertTriangle size={15} className="shrink-0 mt-0.5 text-gold-700" />
      <div className="flex-1 min-w-0">
        <p className="text-xs text-gold-700 leading-relaxed">
          Dice <b>AL MENOS</b> porque este piso está corto siempre para el mismo lado:{' '}
          {sesgos.map((s, i) => (
            <span key={s.clave}>
              {i > 0 && (i === sesgos.length - 1 ? ' y ' : ', ')}
              {s.texto}
            </span>
          ))}.{' '}
          {sesgos.length === 1 ? 'Eso infla' : 'Los ' + sesgos.length + ' inflan'} lo que queda de
          cada peso, o sea <b>BAJAN este número</b>.
        </p>
        {ventaSinCostear !== null && ventaSinCostear > 0 && (
          <p className="text-[11px] text-gold-700/90 leading-snug mt-1">
            Son <b className="font-mono tabular-nums">{plata(ventaSinCostear)}</b> de venta que
            entra al cálculo con costo $0.{' '}
            <button onClick={onVerProductos}
              className="font-bold underline decoration-dotted">
              Ver cuáles
            </button>
          </p>
        )}
      </div>
    </div>
  )
}

/** El desglose: de dónde sale el número, plegado. */
function Desglose({ p }: { p: Piso }) {
  const cf = p.costos_fijos
  const r = p.razones
  return (
    <details className="mt-3 group">
      <summary className="cursor-pointer select-none list-none text-xs font-bold text-forest hover:underline">
        <span className="group-open:hidden">▸ </span>
        <span className="hidden group-open:inline">▾ </span>
        De dónde sale este número
      </summary>
      <div className="mt-2 rounded-xl border border-warm-200 bg-warm-50 px-3 py-3 space-y-3">
        {/* ── El numerador ─────────────────────────────────────────────────── */}
        <div>
          <div className="flex items-baseline justify-between gap-2">
            <p className="text-xs font-bold text-warm-700">
              Lo que hay que pagar venda lo que venda
            </p>
            <p className="text-xs font-bold font-mono tabular-nums text-warm-700 shrink-0">
              {plata(cf.total)}/mes
            </p>
          </div>
          {cf.por_categoria.length === 0 ? (
            <p className="text-[11px] text-warm-500 mt-1">
              No hay ninguna categoría cargada en {nombreMes(p.mes)}.
            </p>
          ) : (
            <div className="mt-1 space-y-0.5">
              {cf.por_categoria.map(c => (
                <div key={c.clave} className="flex items-baseline justify-between gap-2 text-[11px]">
                  <span className="text-warm-500 truncate">{c.nombre}</span>
                  <span className="font-mono tabular-nums text-warm-600 shrink-0">
                    {plata(c.monto)}
                  </span>
                </div>
              ))}
            </div>
          )}
          {/* La ventana es del MES COMPLETO y no «del 1 a hoy». Se dice, porque
              es lo que hace que el piso del día 2 no salga ridículamente bajo. */}
          <p className="text-[10px] text-warm-400 mt-1 leading-snug">
            Del {cf.desde} al {cf.hasta}: el mes entero, no lo que va corrido. El arriendo y la
            nómina se deben completos aunque estemos a día {Number(p.hoy.slice(8, 10))}.
          </p>
        </div>

        {/* ── El denominador ───────────────────────────────────────────────── */}
        {r === null ? (
          <p className="text-[11px] text-warm-500 leading-relaxed border-t border-warm-200 pt-2">
            No hay venta medida con la que calcular cuánto queda de cada $100.
          </p>
        ) : (<>
          <div className="border-t border-warm-200 pt-2">
            <div className="flex items-baseline justify-between gap-2">
              <p className="text-xs font-bold text-warm-700">De cada $100 cobrados quedan</p>
              <p className="text-xs font-bold font-mono tabular-nums text-warm-700 shrink-0">
                {p.margen_contribucion === null ? '—' : porCien(p.margen_contribucion)}
              </p>
            </div>
            <div className="mt-1 space-y-0.5">
              <Renglon label="impoconsumo" valor={`−${porCien(r.impoconsumo)}`} />
              <Renglon label="mercadería" valor={`−${porCien(r.cogs)}`} />
              <Renglon label="comisión del datáfono" valor={`−${porCien(r.comision)}`} />
            </div>
            <p className="text-[10px] text-warm-400 mt-1 leading-snug">
              Medido sobre {plata(r.ventas_medidas)} vendidos entre el {r.desde} y el {r.hasta}
              {r.de === 'mes_anterior' && <> — <b>del mes pasado</b>, porque este mes todavía no
                tiene venta con la que medir</>}.
            </p>
          </div>

          {/* ── La división ────────────────────────────────────────────────── */}
          <div className="border-t border-warm-200 pt-2 space-y-1">
            {p.piso_mes === null ? (
              <p className="text-[11px] text-warm-500 leading-relaxed">
                Con estas razones no se puede dividir: el resultado no sería un piso.
              </p>
            ) : (<>
              <p className="text-[11px] text-warm-600 leading-relaxed">
                {plata(cf.total)} ÷ {p.margen_contribucion === null ? '—' : fmtTasa(p.margen_contribucion)}
                {' = hay que vender '}
                <b className="font-mono tabular-nums">{plata(p.piso_mes)}</b> en {nombreMes(p.mes)}.
              </p>
              <p className="text-[11px] text-warm-600 leading-relaxed">
                Se llevan vendidos <b className="font-mono tabular-nums">{plata(p.ventas_mes)}</b>
                {r.de === 'mes_anterior' && ' este mes'}.
              </p>
              {p.falta !== null && (
                <p className="text-[11px] text-warm-600 leading-relaxed">
                  {p.falta > 0
                    ? <>Faltan <b className="font-mono tabular-nums">{plata(p.falta)}</b> en
                        los {p.dias.quedan} día{p.dias.quedan === 1 ? '' : 's'} que quedan abiertos.</>
                    : <>Ya se pasó el piso del mes
                        por <b className="font-mono tabular-nums">{plata(-p.falta)}</b>.</>}
                </p>
              )}
              <div className="flex items-baseline justify-between gap-2 border-t border-warm-200 pt-1.5 mt-1.5">
                <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500">
                  Piso de hoy
                </p>
                <p className="text-sm font-bold font-mono tabular-nums text-warm-700 shrink-0">
                  {p.piso_hoy === null ? '—' : plata(p.piso_hoy)}
                </p>
              </div>
            </>)}
          </div>
        </>)}
      </div>
    </details>
  )
}

const Renglon = ({ label, valor }: { label: string; valor: string }) => (
  <div className="flex items-baseline justify-between gap-2 text-[11px]">
    <span className="text-warm-500 truncate">{label}</span>
    <span className="font-mono tabular-nums text-warm-600 shrink-0">{valor}</span>
  </div>
)

/**
 * EL HUECO. Del mismo tamaño que el piso, con su nombre y el botón que lo abre.
 *
 * Nunca se pone verde y nunca desaparece: es la regla 4 de la casa aplicada al
 * bloque más importante de la página. Y trae el piso de CAJA cuando se puede,
 * porque ese no necesita costos de producto — sale de lo que hay en caja contra
 * lo que hay que pagar, y es lo único accionable mientras el otro está trabado.
 */
function HuecoDelPiso({ titulo, porque, p, accion }: {
  titulo: string; porque: ReactNode; p: Piso; accion?: ReactNode
}) {
  return (
    <div className="rounded-xl border-2 border-dashed border-warm-300 bg-warm-50 px-4 py-5">
      <p className="text-sm font-bold uppercase tracking-wide text-warm-600 leading-snug">
        {titulo}
      </p>
      <p className="text-xs text-warm-600 leading-relaxed mt-1.5">{porque}</p>

      {/* El piso de caja vive o no vive por su cuenta: sale de la agenda y de la
          caja, no de las razones ni de los costos fijos. */}
      {p.piso_caja.por_dia === null ? (
        <p className="text-xs text-warm-500 leading-relaxed mt-3 border-t border-warm-200 pt-3">
          Tampoco se puede decir el <b>piso de caja</b>: hacen falta los días que quedan
          por abrir en el mes.
        </p>
      ) : (
        <div className="mt-3 border-t border-warm-200 pt-3">
          <p className="text-xs text-warm-600 leading-relaxed">
            Mientras tanto, <b>EL PISO DE CAJA</b>: para no quedarse sin plata antes de fin de
            mes hay que vender{' '}
            <b className="font-mono tabular-nums text-warm-700">{plata(p.piso_caja.por_dia)}</b> por día.
          </p>
          <p className="text-[11px] text-warm-500 leading-relaxed mt-1">
            Este no necesita costos de producto: sale de lo que hay en caja
            ({plata(p.piso_caja.caja_hoy)}) contra lo que hay que pagar
            ({plata(p.piso_caja.salidas_agendadas)}).
          </p>
        </div>
      )}

      {accion && <div className="mt-3">{accion}</div>}
    </div>
  )
}

const BotonDestrabar = ({ children, onClick }: { children: ReactNode; onClick: () => void }) => (
  <button onClick={onClick}
    className="min-h-[44px] px-4 rounded-xl bg-forest hover:bg-forest-700 text-white text-sm font-bold">
    {children}
  </button>
)

export default function BloqueElPiso({
  piso, ventasHoy, pulso, onCargarCosto, onVerProductosSinCosto,
}: {
  piso: Fuente<Piso>
  /** `/rentabilidad/` con desde = hasta = hoy. Es la fracción del titular. */
  ventasHoy: Fuente<RentabilidadData>
  /** Solo por `ventas_diarias`: los días del mes que pasaron el piso parejo. */
  pulso: Fuente<PulsoData>
  /** Baja hasta el bloque 6 y abre el alta de un costo fijo. */
  onCargarCosto: () => void
  /** Al detalle del mes, donde está la lista de productos sin costo. */
  onVerProductosSinCosto: () => void
}) {
  /**
   * El piso Y la venta de hoy, juntos: la fracción «van X de Y» necesita los
   * dos. Con `ambos`, la falla de cualquiera de los dos gana sobre el cargando
   * del otro, y no hay forma de dibujar media barra.
   */
  const conVenta = useMemo(
    () => ambos(piso.dato, ventasHoy.dato), [piso.dato, ventasHoy.dato])

  /** Los días que pasaron el piso parejo. `sinBase` cuando falta con qué contar. */
  const racha = useMemo<Dato<ReturnType<typeof diasContraElPiso>>>(
    () => mapDato(ambos(piso.dato, pulso.dato),
      ([p, pu]) => diasContraElPiso(p, pu.ventas_diarias)),
    [piso.dato, pulso.dato])

  return (
    <section className="rounded-2xl border-2 border-warm-300 bg-white overflow-hidden shadow-sm">
      <div className="px-4 py-4 sm:px-5 sm:py-5">
        <SegunDato
          dato={piso.dato}
          cargando={<Titular rotulo="Para no perder, hoy hay que vender al menos" valor="…" apagado />}
          falla={m => (<>
            <Titular rotulo="Para no perder, hoy hay que vender al menos" valor="—" apagado />
            <div className="mt-3">
              <NoSeSabe bloque onReintentar={piso.recargar}
                mensaje={`${m} — no se sabe cuánto hay que vender hoy para no perder. `
                  + 'Que no haya número no quiere decir que el piso sea bajo.'} />
            </div>
          </>)}
          listo={p => (
            <Cuerpo p={p} conVenta={conVenta} racha={racha}
              ventasHoy={ventasHoy} pulso={pulso}
              onCargarCosto={onCargarCosto}
              onVerProductosSinCosto={onVerProductosSinCosto} />
          )}
        />
      </div>
    </section>
  )
}

/**
 * Una rama por puerta. `switch` sin `default`: el día que el backend agregue una
 * sexta, el build se rompe acá.
 */
function Cuerpo({
  p, conVenta, racha, ventasHoy, pulso, onCargarCosto, onVerProductosSinCosto,
}: {
  p: Piso
  conVenta: Dato<[Piso, RentabilidadData]>
  racha: Dato<ReturnType<typeof diasContraElPiso>>
  ventasHoy: Fuente<RentabilidadData>
  pulso: Fuente<PulsoData>
  onCargarCosto: () => void
  onVerProductosSinCosto: () => void
}) {
  switch (p.puerta) {
    case 'sin_costos_fijos':
      return (
        <HuecoDelPiso
          titulo="Todavía no se puede decir cuánto hay que vender"
          porque={<>
            No hay ningún costo fijo cargado en {nombreMes(p.mes)}. Sin el arriendo y la nómina,
            cualquier número sería <b>más bajo que el real</b>.
          </>}
          p={p}
          accion={<BotonDestrabar onClick={onCargarCosto}>Cargar el arriendo →</BotonDestrabar>} />
      )

    case 'sin_razones':
      return (
        <HuecoDelPiso
          titulo="Todavía no se puede decir cuánto hay que vender"
          porque={<>
            No hay venta medida ni en {nombreMes(p.mes)} ni en el mes anterior, así que no se
            sabe cuánto queda de cada $100 cobrados. Sin eso, el costo fijo no se puede
            convertir en una meta de venta.
          </>}
          p={p} />
      )

    case 'margen_no_positivo':
      return (
        <div className="rounded-xl border-2 border-danger-300 bg-danger-50 px-4 py-5">
          <p className="text-sm font-bold uppercase tracking-wide text-danger-700 leading-snug">
            Con estos costos, cada venta pierde plata
          </p>
          <p className="text-xs text-danger-700/90 leading-relaxed mt-1.5">
            No hay piso que alcanzar: vender más haría perder más. Hay que bajar un costo o
            subir un precio.
          </p>
          {p.margen_contribucion !== null && p.razones && (
            <p className="text-[11px] text-danger-700/80 leading-relaxed mt-2 border-t border-danger-200 pt-2">
              De cada $100 cobrados quedan <b>{porCien(p.margen_contribucion)}</b>: se van{' '}
              {porCien(p.razones.impoconsumo)} de impoconsumo, {porCien(p.razones.cogs)} de
              mercadería y {porCien(p.razones.comision)} de comisión del datáfono. Medido sobre{' '}
              {plata(p.razones.ventas_medidas)} entre el {p.razones.desde} y el {p.razones.hasta}.
            </p>
          )}
          <p className="text-[11px] text-danger-700/80 leading-relaxed mt-2">
            El piso de caja sigue vivo y está más abajo: aunque cada venta pierda, la plata que
            hay que pagar este mes no se mueve.
          </p>
        </div>
      )

    case 'ok':
    case 'razones_del_mes_anterior':
      return (
        <PisoPublicado p={p} conVenta={conVenta} racha={racha}
          ventasHoy={ventasHoy} pulso={pulso}
          onVerProductosSinCosto={onVerProductosSinCosto} />
      )
  }
}

/** El piso de verdad: el número, la fracción del día, el mes y la banda. */
function PisoPublicado({
  p, conVenta, racha, ventasHoy, pulso, onVerProductosSinCosto,
}: {
  p: Piso
  conVenta: Dato<[Piso, RentabilidadData]>
  racha: Dato<ReturnType<typeof diasContraElPiso>>
  ventasHoy: Fuente<RentabilidadData>
  pulso: Fuente<PulsoData>
  onVerProductosSinCosto: () => void
}) {
  /**
   * EL TITULAR ES EL QUE MANDA, y quién manda lo dice el backend.
   *
   * `manda` es el más ALTO de los dos pisos por día. Poner arriba el de
   * resultado cuando el de caja es más exigente sería cubrir el más chico y
   * creer que alcanza — la familia de error de siempre, con pintura nueva.
   */
  const mandaCaja = p.manda === 'caja'
  const delDia = mandaCaja ? p.piso_caja.por_dia : p.piso_hoy
  const otro = mandaCaja ? p.piso_hoy : p.piso_caja.por_dia

  const activos = sesgosActivos(p)

  return (<>
    <Titular
      rotulo={<>Para no perder, hoy hay que vender al menos</>}
      valor={delDia === null ? '—' : plata(delDia)}
      apagado={delDia === null}
      pie={delDia === null ? (
        <p className="text-xs text-warm-500 leading-relaxed">
          {p.dias.quedan === 0
            ? 'No queda ningún día abierto en el mes: el piso del mes ya no se puede repartir.'
            : 'No se pudo repartir el piso del mes en los días que quedan.'}
        </p>
      ) : null} />

    {/* ── La fracción del día ─────────────────────────────────────────────
        `$890.000` solo no significa nada; contra un piso de `$2.340.000` es un
        38% y eso sí se acciona. Por eso la venta de hoy dejó de ser un banner
        propio y vive acá adentro. */}
    {delDia !== null && (
      <SegunDato
        dato={conVenta}
        cargando={<p className="mt-3 text-sm text-warm-400">Leyendo lo vendido hoy…</p>}
        falla={m => (
          <div className="mt-3">
            <NoSeSabe onReintentar={ventasHoy.recargar}
              mensaje={`${m} — no se sabe cuánto va vendido hoy, así que no se puede decir `
                + 'cuánto falta. No quiere decir que no se haya vendido nada.'} />
          </div>
        )}
        listo={([, v]) => <Progreso hecho={v.resumen.ventas} meta={delDia} />} />
    )}

    {/* ── Cuántos días de este mes pasaron la vara pareja ─────────────────
        Vara PAREJA, no el piso de hoy: mirar hacia atrás con un piso que sube
        cuando el mes va mal daría un porcentaje que mejora solo por atrasarse. */}
    <SegunDato
      dato={racha}
      cargando={null}
      falla={() => (
        <p className="mt-2.5 text-[11px] text-warm-500 leading-relaxed">
          No se pudo leer la venta día por día, así que no se sabe cuántos días de{' '}
          {nombreMes(p.mes)} pasaron el piso.{' '}
          <button onClick={pulso.recargar} className="font-bold text-forest underline decoration-dotted">
            Reintentar
          </button>
        </p>
      )}
      listo={r => r === null ? null : (
        <p className="mt-2.5 text-sm text-warm-600">
          En {nombreMes(p.mes)} se pasó el piso <b>{r.pasados} de {r.corridos}</b>{' '}
          día{r.corridos === 1 ? '' : 's'}.
          <span className="block text-[11px] text-warm-400 leading-snug mt-0.5">
            Contra la vara pareja del mes ({plata(r.piso_parejo)} por día), que es distinta del
            piso de hoy: hoy sube porque hay que recuperar lo que no se vendió.
          </span>
        </p>
      )} />

    {/* ── El mes ─────────────────────────────────────────────────────────── */}
    <div className="mt-3 border-t border-warm-100 pt-3 space-y-1">
      {p.falta === null ? (
        <p className="text-sm text-warm-500">
          No se pudo calcular cuánto falta de venta en {nombreMes(p.mes)}.
        </p>
      ) : p.falta > 0 ? (<>
        <p className="text-sm text-warm-600">
          Para no perder en {nombreMes(p.mes)} faltan{' '}
          <b className="font-mono tabular-nums text-warm-700">{plata(p.falta)}</b> de venta.
        </p>
        <p className="text-sm text-warm-600">
          Quedan <b>{p.dias.quedan}</b> día{p.dias.quedan === 1 ? '' : 's'} abierto
          {p.dias.quedan === 1 ? '' : 's'}
          {p.piso_hoy !== null && <>:{' '}
            <b className="font-mono tabular-nums text-warm-700">{plata(p.piso_hoy)}</b> por día,
            todos los días</>}.
        </p>
      </>) : (
        <p className="text-sm text-success-700 font-semibold">
          El piso del mes ya está cubierto: se vendió {plata(-p.falta)} por encima.
        </p>
      )}

      {/* Las razones prestadas se declaran SIEMPRE que se usan. Un piso calculado
          con el margen de julio y presentado como el de agosto es exactamente un
          dato «cerca del correcto». */}
      {p.puerta === 'razones_del_mes_anterior' && (
        <p className="text-[11px] text-gold-700 leading-relaxed">
          Ojo: {nombreMes(p.mes)} todavía no tiene venta con la que medir, así que lo que queda
          de cada $100 salió del <b>mes anterior</b>. La venta de {nombreMes(p.mes)} no se le
          resta a este piso.
        </p>
      )}

      {/* Por qué el piso de hoy no es el del mes dividido en partes iguales. */}
      {p.falta !== null && p.falta > 0 && p.piso_hoy !== null && (
        <p className="text-[11px] text-warm-400 leading-relaxed">
          El piso de hoy sube si se viene atrasado: no es el piso del mes dividido en partes
          iguales, es lo que falta repartido en los días que quedan.
        </p>
      )}

      {!p.dias.derivados && (
        <p className="text-[11px] text-gold-700 leading-relaxed">
          No hay historia de ventas suficiente para saber qué días abre el negocio, así que se
          contaron los días de calendario. Si cierra algún día de la semana, el piso por día es
          más alto que este.
        </p>
      )}
    </div>

    <BandaAlMenos sesgos={activos} onVerProductos={onVerProductosSinCosto} />

    <Desglose p={p} />

    {/* ── Quién manda, y cuánto es el otro ────────────────────────────────
        Los dos números se muestran juntos: el que manda arriba y el otro acá,
        nombrado. Mostrar solo el que manda escondería que existe un segundo
        piso; mostrarlos sin decir cuál gobierna dejaría al dueño eligiendo el
        más cómodo. */}
    {p.manda !== null && (
      <p className="mt-3 text-xs text-warm-500 leading-relaxed border-t border-warm-100 pt-3">
        Manda el <b>piso de {mandaCaja ? 'caja' : 'resultado'}</b>, que es el más exigente
        de los dos.
        {' '}
        {otro === null
          ? <>El piso de {mandaCaja ? 'resultado' : 'caja'} no se pudo calcular.</>
          : <>El piso de {mandaCaja ? 'resultado' : 'caja'} hoy es{' '}
              <b className="font-mono tabular-nums">{plata(otro)}</b>.</>}
      </p>
    )}
  </>)
}
