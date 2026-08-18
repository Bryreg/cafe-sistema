import { ReactNode, useEffect, useMemo, useState } from 'react'
import { HandCoins, Landmark, Pencil, Store } from 'lucide-react'
import api from '../../api/client'
import { conMiles, soloDigitos } from '../../utils/plata'
import { Dato, mapDato } from '../../api/dato'
import type { Fuente } from '../../api/useDato'
import { SegunDato, NoSeSabe } from '../ui'
import { CuentaBanco, LibroMes, detalleDeError, diasEntre, fechaCorta, plata } from './banco'
import { CajaHoy, Flujo, ORIGEN_CAJA, Tienda } from './tipos'
import { filaConSaldoDe } from './useLibro'
import FormRecogida from './FormRecogida'
import { Campo, CLS_INPUT, CLS_INPUT_PLATA, CLS_BOTON_GUARDAR, CLS_BOTON_SUAVE, ComoSeCalcula, ErrorCampo, teclas } from './campos'

/** Un número grande de esta tarjeta. Gris cuando no hay cifra: un «—» del mismo
 *  peso que $2.400.000 se lee como un dato, y acá es lo contrario. */
function Cifra({ valor, apagado = false, rojo = false }: {
  valor: ReactNode; apagado?: boolean; rojo?: boolean
}) {
  return (
    <p className={`text-xl font-bold font-mono tabular-nums leading-tight mt-0.5 ${
      apagado ? 'text-warm-400' : rojo ? 'text-danger-700' : 'text-warm-700'}`}>
      {valor}
    </p>
  )
}

const Nota = ({ children }: { children: ReactNode }) => (
  <p className="text-[11px] text-warm-500 leading-snug">{children}</p>
)

/**
 * ═════════════════════════════════════════════════════════════════════════════
 * ¿CUÁNTA PLATA HAY? — el banner que contesta la mitad de «¿me alcanza?»
 * ═════════════════════════════════════════════════════════════════════════════
 * Cuatro números que antes vivían en tres pantallas distintas: el saldo del
 * banco estaba en «La plata», el efectivo de las registradoras adentro del cajón
 * del flujo, y el editor del extracto en los DOS lugares (con dos formularios
 * distintos escribiendo la misma fila de `configuracion`).
 *
 * ── EL SALDO DEL BANCO SE MUESTRA UNA SOLA VEZ ─────────────────────────────
 * `flujo.caja_hoy.saldo_banco` y el `final` de la fila de hoy del libro son, al
 * peso, EL MISMO NÚMERO: el backend calcula el primero llamando a
 * `banco.saldo_al_cierre(hoy)`, que es ancla + Σ(entradas − salidas) hasta hoy
 * (services/costos.py). Tenerlos los dos en pantalla era invitar a buscar la
 * diferencia entre dos cifras iguales. Manda el del LIBRO, que es el que trae su
 * propia explicación (arrancó / entró / salió) y el que se puede auditar fila
 * por fila abajo.
 *
 * ── SE DECIDE POR LA FILA DE HOY, NUNCA POR EL MES ─────────────────────────
 * `cadena_completa` significa «todos los días del rango tienen saldo» y con el
 * ancla a mitad de mes —el caso normal— es false aunque el saldo de hoy sea
 * exacto. Condicionar por esa bandera fue el bug que le pedía cargar el extracto
 * que acababa de cargar. Quien decide es `filaConSaldoDe(libro, hoy)`.
 *
 * ── Y NUNCA POR «EL LIBRO NO ESTÁ» ─────────────────────────────────────────
 * El motivo del «—» sale del DATO que falta, y desde que el libro es un `Dato`
 * hay cuatro motivos posibles, no dos. Con el molde viejo (`libro | null`), un
 * fetch caído entraba por la misma rama que un mes sin ancla y la pantalla
 * afirmaba «Falta el saldo del extracto para saberlo» sobre una cuenta que sí
 * tenía extracto cargado: mandaba a cargar de nuevo un dato que ya estaba.
 *
 * ── LA PLATA VIVE EN TRES LUGARES, NO EN DOS ───────────────────────────────
 * Hasta julio eran dos —el cajón y el banco— y el sistema los conocía a los dos:
 * la barista vendía en efectivo y ella misma iba a consignar, así que la plata
 * salía del cajón y entraba a la cuenta. Desde agosto el DUEÑO pasa y recoge:
 * con ese efectivo le paga a los proveedores que aceptan efectivo —plata que
 * nunca toca el banco— y consigna el resto él mismo. El tercer lugar es SU MANO,
 * y hasta ahora no existía en ninguna pantalla.
 *
 * Por eso este banner muestra TRES buckets desglosados y no dos: el dueño tiene
 * que poder ver de dónde sale cada peso del total. Y por eso el bucket de la
 * mano puede no existir (`efectivo_en_mano === null`, sin ninguna recogida
 * registrada): ahí va un «—» y la frase que lo explica, nunca un «$0». Un cero
 * afirmaría que no tiene plata encima, que es exactamente lo que no se sabe.
 */
export default function BannerSaldos({
  libro, hoy, flujo, cuentas, tiendas, pedidoApertura, onAnclaGuardada, onRecargarLibro,
}: {
  /** El libro del MES DE HOY (no el que se esté mirando: el saldo de hoy no
   *  puede depender de dónde navegó el ojo). */
  libro: Dato<LibroMes>
  hoy: string
  /** De acá sale `caja_hoy`: los tres buckets de efectivo y el total. */
  flujo: Fuente<Flujo>
  cuentas: Fuente<CuentaBanco[]>
  /** Para el select de la fila de recogida: de qué sede recogió la plata. */
  tiendas: Fuente<Tienda[]>
  /**
   * Contador que sube cuando OTRO banner pide abrir este editor.
   *
   * Es lo que reemplaza a las tres puertas que había: el modal del cajón del
   * flujo, el botón «Actualizar» del faltante y el aviso de cadena del libro
   * escribían/apuntaban a las MISMAS dos claves (`saldo_banco`,
   * `saldo_banco_fecha`) — dos de ellas con su propio formulario. Ahora todas
   * suben acá, que es el único editor del ancla que queda.
   */
  pedidoApertura: number
  /** Guardó el ancla: hay que repedir el libro Y el flujo (los dos lo leen). */
  onAnclaGuardada: () => void
  /** Repide el libro del banco sin desmontar nada de lo que se esté tecleando. */
  onRecargarLibro: () => void
}) {
  /**
   * El ancla LEÍDA. `null` acá no significa «no hay ancla»: significa que el
   * libro todavía no está en la mano (se está pidiendo, o no volvió). Solo se usa
   * para PRECARGAR el editor, que es código imperativo y no puede pasar por
   * `SegunDato`; lo que se AFIRMA en pantalla se decide adentro de cada rama.
   */
  const anclaLeida = libro.estado === 'listo' ? libro.valor.ancla : null

  const [abierto, setAbierto] = useState(false)
  const [saldo, setSaldo] = useState('')
  const [fecha, setFecha] = useState(hoy)
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)

  /**
   * Sube cuando el tile «En tu mano» invita a registrar la primera recogida.
   *
   * Es un CONTADOR y no un booleano por la misma razón que `pedidoApertura`: el
   * gesto se puede repetir, y con un booleano el segundo toque no dispara nada
   * porque el estado ya estaba en `true`. El formulario está siempre montado —
   * esto solo le lleva el foco, no lo hace aparecer.
   */
  const [pedidoRecogida, setPedidoRecogida] = useState(0)

  const abrir = () => {
    // ABRE EN BLANCO SI NO HAY FECHA. Sin fecha no hay saldo cargado: el 0 que
    // devuelve el backend en ese caso es el default de la fila vacía, no una
    // plata que alguien haya declarado, y precargarlo lo haría guardable de un
    // toque. Con el libro caído abre en blanco por la MISMA razón, y el renglón
    // de adentro dice que el saldo cargado no se pudo leer — así el campo vacío
    // no se lee como «no había nada».
    //
    // Y LA FECHA VA CON SU MONTO. Precargar el saldo viejo con la fecha de HOY
    // arma un par que nunca fue verdad: guardarlo sin tocar nada re-ancla hoy
    // con el número del extracto viejo, deja fuera de la cadena todos los
    // movimientos tecleados en el medio y SUBE la plata. Medido en su momento:
    // 2.000.000 pasaban a 5.000.000 y una salida de 3.000.000 desaparecía.
    setSaldo(anclaLeida?.fecha ? String(Math.round(anclaLeida.saldo)) : '')
    setFecha(anclaLeida?.fecha ?? hoy)
    setError('')
    setAbierto(true)
  }

  // Otro banner pidió abrirlo. Se ignora el montaje inicial (`pedidoApertura`
  // arranca en 0) para no abrir el editor sin que nadie lo haya tocado.
  useEffect(() => {
    if (pedidoApertura > 0) abrir()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pedidoApertura])

  const listo = !!fecha && !!saldo
  const guardar = async () => {
    // GUARDA DE REENTRADA. Enter y el botón llaman a lo mismo, y entre el
    // toque y la respuesta hay una ida y vuelta: dos toques ahí adentro
    // escribían DOS veces. En una tablet con conexión lenta eso duplica un
    // movimiento, un pago o una obligación, y `registrar_pago` del backend
    // ni siquiera valida contra el saldo.
    if (guardando) return
    if (!listo) return
    setGuardando(true); setError('')
    try {
      await api.put('/banco/ancla', { saldo: Number(saldo || 0), fecha })
      setAbierto(false)
      onAnclaGuardada()
    } catch (e) {
      setError(detalleDeError(e, 'No se pudo guardar el saldo. Reintentá.'))
    } finally { setGuardando(false) }
  }

  // El total sale del backend (`caja_hoy.total`), no de sumar acá: con filtro de
  // sede el banco NO entra, y esa decisión ya está tomada allá.
  const caja = useMemo<Dato<CajaHoy>>(() => mapDato(flujo.dato, f => f.caja_hoy), [flujo.dato])

  return (
    <section className="bg-white rounded-2xl border border-warm-200 overflow-hidden">
      <div className="grid grid-cols-2 divide-x divide-warm-100 border-b border-warm-100">
        {/* ── En el banco (el libro manda) ─────────────────────────────────── */}
        <div className="px-4 py-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500 flex items-center gap-1">
            <Landmark size={11} /> En el banco hoy
          </p>
          <SegunDato
            dato={libro}
            cargando={<><Cifra valor="…" apagado /><Nota>Leyendo el libro del banco…</Nota></>}
            falla={m => (<>
              <Cifra valor="—" apagado />
              <div className="mt-1">
                <NoSeSabe onReintentar={onRecargarLibro}
                  mensaje={`${m} — no se sabe cuánta plata hay en la cuenta.`} />
              </div>
            </>)}
            listo={l => {
              // LA CADENA SE DECIDE POR LA FILA. `null` acá es una respuesta del
              // backend («ese día es anterior al ancla»), no un dato ausente.
              const filaHoy = filaConSaldoDe(l, hoy)
              if (filaHoy) return (<>
                <Cifra valor={plata(filaHoy.final)} rojo={filaHoy.final < 0} />
                <Nota>
                  Arrancó en {plata(filaHoy.inicial)}
                  {filaHoy.total_entradas > 0 && <> · entró {plata(filaHoy.total_entradas)}</>}
                  {filaHoy.total_salidas > 0 && <> · salió {plata(filaHoy.total_salidas)}</>}
                </Nota>
              </>)
              // El motivo se elige por el DATO que falta, no por una bandera del
              // mes. Con el ancla cargada esto NO puede decir «falta el saldo del
              // extracto»: el backend solo deja hoy sin cadena si el ancla no
              // existe (su fecha nunca puede ser futura, la rechaza el router).
              return (<>
                <Cifra valor="—" apagado />
                <Nota>
                  {!l.ancla.fecha
                    ? 'Falta el saldo del extracto para saberlo.'
                    : `El saldo del extracto es del ${fechaCorta(l.ancla.fecha)}: `
                      + 'la cadena todavía no llega hasta hoy.'}
                </Nota>
              </>)
            }}
          />
        </div>

        {/* ── El extracto, y su editor en la misma tarjeta ───────────────────
            EL BOTÓN NO SE APAGA NUNCA. Es la única puerta al editor del ancla, y
            justo cuando el libro no volvió es cuando el dueño necesita poder
            cargar el saldo a mano. Lo que cambia por estado es lo que se AFIRMA
            adentro, no si se puede tocar. */}
        <button onClick={abrir} className="px-4 py-3 text-left hover:bg-warm-50 transition-colors">
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">
            Saldo del extracto
          </p>
          <SegunDato
            dato={libro}
            cargando={<><Cifra valor="…" apagado /><Nota>Leyendo el saldo cargado…</Nota></>}
            falla={() => (<>
              <Cifra valor="—" apagado />
              {/* «Sin cargar» sería una afirmación sobre una fila que no se pudo
                  leer, y la que manda a cargar de nuevo un extracto que ya está. */}
              <Nota>No se pudo leer el saldo cargado. Tocá acá para poner uno.</Nota>
            </>)}
            listo={l => (<>
              <Cifra valor={l.ancla.fecha ? plata(l.ancla.saldo) : '—'} apagado={!l.ancla.fecha} />
              <p className="text-[11px] text-warm-500 leading-snug flex items-center gap-1">
                {l.ancla.fecha
                  ? <>Del {fechaCorta(l.ancla.fecha)}
                      {diasEntre(l.ancla.fecha, hoy) > 0
                        && ` · hace ${diasEntre(l.ancla.fecha, hoy)} día${diasEntre(l.ancla.fecha, hoy) === 1 ? '' : 's'}`}</>
                  : 'Sin cargar — cargalo acá'}
                <Pencil size={10} className="shrink-0" />
              </p>
            </>)}
          />
        </button>
      </div>

      {/* El editor abre EN LA MISMA TARJETA: es un dato que solo el dueño tiene
          (el sistema registra consignaciones, nunca un saldo bancario) y cada
          click de distancia es un día más de saldo viejo. */}
      {abierto && (
        <div className="border-b border-warm-200 bg-warm-50 px-4 py-3 space-y-2"
          onKeyDown={teclas({ listo, guardar, cancelar: () => setAbierto(false) })}>
          {/* EL FORMULARIO NO SE ESCONDE CUANDO EL LIBRO NO VOLVIÓ: se avisa y se
              deja teclear. El saldo del extracto lo tiene el dueño en la mano —
              no depende de este fetch— y esconderlo le rompe el trabajo de las 7. */}
          <SegunDato
            dato={libro}
            cargando={null}
            falla={m => (
              <NoSeSabe onReintentar={onRecargarLibro}
                mensaje={`${m} — no se pudo leer el saldo que ya estaba cargado, así que los `
                  + 'campos abren en blanco. Lo que teclees acá se guarda igual.'} />
            )}
            listo={() => null}
          />
          <p className="text-[11px] text-warm-600 leading-relaxed">
            Abrí la app del banco y copiá el saldo. Es el saldo con el que <b>arranca</b> ese día:
            de ahí para adelante el libro suma lo que entra y resta lo que sale.
          </p>
          <div className="grid grid-cols-2 gap-2 max-w-md">
            <Campo label="Saldo">
              <input type="text" inputMode="numeric" value={conMiles(saldo)} autoFocus
                onChange={e => setSaldo(soloDigitos(e.target.value))}
                aria-label="Saldo del extracto" className={CLS_INPUT_PLATA} />
            </Campo>
            <Campo label="¿De qué día es?">
              <input type="date" value={fecha} max={hoy} onChange={e => setFecha(e.target.value)}
                className={CLS_INPUT} />
            </Campo>
          </div>
          <p className="text-[11px] text-warm-500 leading-relaxed">
            La cadena arranca en esa fecha: los días anteriores quedan sin saldo. Si tenés el
            extracto del primero del mes, poné el primero y el mes entero queda con saldo.
          </p>
          <ErrorCampo msg={error} />
          <div className="flex gap-2">
            <button onClick={() => setAbierto(false)} className={CLS_BOTON_SUAVE}>Cancelar</button>
            <button onClick={guardar} disabled={guardando || !listo}
              className={`${CLS_BOTON_GUARDAR} flex-1`}>
              {guardando ? 'Guardando…' : 'Guardar saldo'}
            </button>
          </div>
        </div>
      )}

      {/* ── El efectivo físico, la plata de la mano y el total ───────────────
          Es el ÚNICO lugar del módulo donde aparece la plata de las
          registradoras, y cada sede dice DE DÓNDE sale su cifra: un turno
          abierto es un conteo vivo, un «último cuadre» puede ser de anteayer.

          TRES COLUMNAS Y NO DOS. Desde que el dueño recoge el efectivo, el total
          se arma de tres partes y no de dos; mostrar solo la suma dejaría al
          dueño sin poder ver de dónde sale cada peso, que es justo lo que hay
          que poder ver mientras el modelo de manejo del efectivo es nuevo. En
          celular van apiladas (una columna) para que ninguna cifra se corte. */}
      <div className="grid grid-cols-1 sm:grid-cols-3 divide-y sm:divide-y-0 sm:divide-x divide-warm-100">
        <div className="px-4 py-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500 flex items-center gap-1">
            <Store size={11} /> En la registradora
          </p>
          <SegunDato
            dato={caja}
            cargando={<Cifra valor="…" apagado />}
            falla={() => (<>
              <Cifra valor="—" apagado />
              {/* El desglose por sede desaparecía entero y sin decir nada: dos
                  sedes que no se muestran se leen como dos cajones vacíos. */}
              <Nota>No se pudo leer el efectivo de las registradoras.</Nota>
            </>)}
            listo={c => (<>
              <Cifra valor={plata(c.efectivo_registradora)} />
              <div className="space-y-0.5 mt-0.5">
                {c.por_tienda.map(t => (
                  <div key={t.tienda_id} className="flex items-center justify-between gap-2 text-[11px]">
                    <span className="text-warm-500 truncate">{t.tienda_nombre}</span>
                    <span className="font-mono tabular-nums text-warm-600 shrink-0">
                      {plata(t.efectivo)}{' '}
                      <span className="text-warm-400">· {ORIGEN_CAJA[t.origen] ?? t.origen}</span>
                    </span>
                  </div>
                ))}
              </div>
            </>)}
          />
        </div>

        {/* ── En tu mano ───────────────────────────────────────────────────────
            El bucket que no existía. Lo que el dueño recogió de las sedes menos
            lo que ya pagó en efectivo y lo que consignó él: la plata que hoy
            tiene encima y que ninguna otra pantalla del sistema ve. */}
        <div className="px-4 py-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500 flex items-center gap-1">
            <HandCoins size={11} /> En tu mano
          </p>
          <SegunDato
            dato={caja}
            cargando={<><Cifra valor="…" apagado /><Nota>Leyendo lo que recogiste…</Nota></>}
            falla={() => (<>
              <Cifra valor="—" apagado />
              <Nota>No se pudo leer el efectivo que recogiste de las sedes.</Nota>
            </>)}
            listo={c => c.efectivo_en_mano === null ? (<>
              {/* EL BUCKET NO EXISTE — NO ES CERO. Nunca se registró una
                  recogida, así que no hay desde cuándo contar. Un «$0» acá
                  AFIRMARÍA que no tiene plata encima, que es justo lo que no se
                  sabe, y lo afirmaría hacia el lado tranquilizador: sería el
                  mismo error que este banner existe para no volver a cometer,
                  cambiado de lugar. Así que va el «—» y la invitación a llenarlo. */}
              <Cifra valor="—" apagado />
              <Nota>
                Todavía no registraste ninguna recogida, así que <b>no se sabe</b> cuánta plata
                tenés encima. No es cero.{' '}
                <button onClick={() => setPedidoRecogida(n => n + 1)}
                  className="font-bold text-forest underline decoration-dotted">
                  Registrá la primera
                </button>
              </Nota>
            </>) : (<>
              <Cifra valor={plata(c.efectivo_en_mano)} rojo={c.efectivo_en_mano < 0} />
              <Nota>
                {c.efectivo_en_mano < 0
                  // EN NEGATIVO NO ES UN SALDO, ES UN AVISO. Salió más plata de
                  // la mano de la que entró, y como las recogidas se cargan a
                  // mano y los pagos en efectivo se derivan solos, el que falta
                  // registrar es casi siempre el lado de acá. Decirlo evita que
                  // el dueño busque el error en el banco.
                  ? <>Salió más de lo que aparece recogido: falta registrar alguna recogida.</>
                  : c.efectivo_en_mano_desde
                    ? <>Recogido desde el {fechaCorta(c.efectivo_en_mano_desde)}, menos lo que
                        pagaste en efectivo y lo que consignaste vos.</>
                    : <>Lo que recogiste, menos lo que pagaste en efectivo y lo que
                        consignaste vos.</>}
              </Nota>
            </>)}
          />
        </div>

        <div className="px-4 py-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">
            Con todo, hay
          </p>
          <SegunDato
            dato={caja}
            cargando={<><Cifra valor="…" apagado /><Nota>Sumando la caja…</Nota></>}
            falla={m => (<>
              <Cifra valor="—" apagado />
              <div className="mt-1">
                <NoSeSabe onReintentar={flujo.recargar}
                  mensaje={`${m} — no se sabe cuánta plata hay entre el banco, las registradoras `
                    + 'y lo que recogiste.'} />
              </div>
            </>)}
            listo={c => (<>
              <Cifra valor={plata(c.total)} />
              {/* El rótulo cuenta las sedes que el backend devolvió, no dice «las
                  dos»: el día que se abra una tercera, la frase seguiría afirmando
                  un número que ya no es.

                  Y ENUMERA LOS SUMANDOS QUE DE VERDAD ENTRARON. Cuando el bucket
                  de la mano no existe, el total está incompleto por una cantidad
                  desconocida y la frase lo dice: un «Banco + registradoras» a
                  secas se leería como «esto es toda la plata», que es la mentira
                  de siempre con la pintura nueva.

                  Y QUIÉN ENTRÓ AL TOTAL LO DICE EL BACKEND, no una deducción de
                  acá. `efectivo_en_mano_incluido` es `tienda_id is None and monto
                  is not None` allá; escribir esa misma condición en esta línea
                  daría lo mismo HOY y esa es la trampa: el día que allá cambie,
                  este rótulo seguiría enumerando un sumando que ya no se suma. */}
              <Nota>
                {c.saldo_banco_incluido ? (<>
                  Banco + {c.por_tienda.length === 1 ? 'la registradora'
                    : `las ${c.por_tienda.length} registradoras`}
                  {c.efectivo_en_mano_incluido
                    ? <> + lo que tenés en la mano</>
                    : <> — <b>sin</b> lo que tengas en la mano, que todavía no se registra</>}
                  {' '}— con esto arranca la proyección
                </>) : (<>
                  Solo la caja de esta sede: la cuenta del banco y la plata de tu mano son de la
                  empresa, no de la sede
                </>)}
              </Nota>
            </>)}
          />
        </div>
      </div>

      {/* ── La fila que llena el bucket de la mano ───────────────────────────
          Va PEGADA a los tres números y no en otro banner: es la acción que los
          mueve, y cada click de distancia es un día más de cajón mintiendo.
          Siempre montada, como la fila del banco: recoger de las dos sedes son
          dos cargas seguidas, no dos aperturas.

          REFRESCA `flujo` Y NADA MÁS. Una recogida no toca el banco (esa plata
          no entró a la cuenta), no toca la agenda y no toca el resultado del mes:
          lo único que cambia es `caja_hoy` —el cajón baja, la mano sube— y la
          proyección que arranca de ahí, y las dos cosas viven adentro de este
          mismo recurso. Repedir la página entera haría parpadear cinco banners
          que nadie tocó. */}
      <FormRecogida tiendas={tiendas} hoy={hoy}
        pedidoFoco={pedidoRecogida} onGuardado={flujo.recargar} />

      <ComoSeCalcula titulo="¿De dónde sale el saldo del banco?">
        <p>
          El sistema <b>no puede saber</b> cuánta plata hay en la cuenta: registra las
          consignaciones que hacen las baristas, pero nunca ve el extracto. Por eso el saldo
          arranca de un número que ponés vos —el del extracto— y de ahí para adelante el libro
          suma lo que entra y resta lo que sale, movimiento por movimiento.
        </p>
        <p>
          La distancia entre las dos tarjetas de arriba es exactamente lo que tecleaste en el
          libro desde ese día. Y ojo: que el libro esté al día <b>no</b> es haberlo comparado
          contra el banco — lo que nunca tecleaste (un débito automático, una comisión) no está
          en ninguna parte. Por eso conviene volver a copiar el extracto cada semana.
        </p>
        {/* Este párrafo es una ADVERTENCIA sobre la proyección, así que solo puede
            escribirse con la caja en la mano: sin ella no se sabe si la cadena
            encadena, y callar es lo correcto (el hueco de arriba ya avisó). */}
        {caja.estado === 'listo' && caja.valor.saldo_banco_fecha
          && caja.valor.saldo_banco_origen !== 'libro' && (
          <p className="text-gold-700">
            Ahora mismo la proyección <b>no está usando el libro</b> sino el extracto del{' '}
            {fechaCorta(caja.valor.saldo_banco_fecha)} a secas: la cadena no encadena (falta el
            ancla o la fila de configuración quedó inconsistente), así que los movimientos que
            tecleaste después no se le están sumando.
          </p>
        )}
        <p>
          «En la registradora» es efectivo físico y sale de cada sede por separado: un turno
          abierto es el conteo vivo, «conteo del cierre» es el de la última vez que cerraron y
          «último cuadre» es el respaldo cuando cerraron sin contar.
        </p>
        {/* La explicación del bucket nuevo. Vale la pena escribirla entera: el
            modelo de manejo del efectivo cambió en agosto y la diferencia entre
            «la consignó la barista» y «la consigné yo» es la que decide de qué
            bolsillo sale cada peso. Sin esto, el dueño no tiene cómo saber por
            qué su consignación no bajó el cajón. */}
        <p>
          <b>«En tu mano»</b> es la plata que recogiste de las sedes y que todavía no salió. Cada
          recogida que cargás acá <b>baja el cajón</b> de esa sede y <b>sube tu efectivo en
          mano</b>: la plata no desaparece, cambia de lugar. De ahí se descuenta solo lo que pagás
          en efectivo y las consignaciones que hacés <b>vos</b> — las de las baristas no, porque
          esas salen del cajón y ya se descontaron ahí. Restarlas de nuevo sería restar la misma
          plata dos veces.
        </p>
        <p>
          Mientras no registres ninguna recogida, ese casillero dice <b>«—» y no «$0»</b>, a
          propósito: el sistema no tiene forma de saber cuánto llevás encima, y un cero ahí sería
          afirmar que no llevás nada. Ojo con lo que eso implica para el total: hasta la primera
          recogida, «con todo, hay» es <b>menos</b> de lo que de verdad hay.
        </p>
        {/* Los nombres de las cuentas solo se enumeran si el catálogo llegó. Con
            el molde viejo (`cuentas.length > 0`) la frase desaparecía igual con
            el fetch caído que con la lista vacía, y las dos cosas se explican
            distinto. */}
        <SegunDato
          dato={cuentas.dato}
          cargando={null}
          falla={() => (
            <p>
              No se pudo leer contra qué cuentas se cargan los movimientos, así que acá no se
              enumeran. No quiere decir que no haya ninguna.
            </p>
          )}
          listo={cs => cs.length === 0 ? (
            <p>Todavía no hay ninguna cuenta de banco cargada.</p>
          ) : (
            <p>
              Los movimientos se cargan contra {cs.length === 1 ? 'la cuenta'
                : `las ${cs.length} cuentas`}: {cs.map(c => c.nombre).join(', ')}.
            </p>
          )}
        />
      </ComoSeCalcula>
    </section>
  )
}
