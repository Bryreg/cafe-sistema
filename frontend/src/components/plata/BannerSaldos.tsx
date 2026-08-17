import { useEffect, useState } from 'react'
import { Landmark, Pencil, Store } from 'lucide-react'
import api from '../../api/client'
import { conMiles, soloDigitos } from '../../utils/plata'
import { CuentaBanco, DiaConSaldo, LibroMes, detalleDeError, diasEntre, fechaCorta, plata } from './banco'
import { CajaHoy, ORIGEN_CAJA } from './tipos'
import { Campo, CLS_INPUT, CLS_INPUT_PLATA, CLS_BOTON_GUARDAR, CLS_BOTON_SUAVE, ComoSeCalcula, ErrorCampo, teclas } from './campos'

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
 * que acababa de cargar. Quien decide es `filaHoy.cadena`.
 */
export default function BannerSaldos({
  libro, filaHoy, hoy, caja, cuentas, pedidoApertura, onAnclaGuardada,
}: {
  /** El libro del MES DE HOY (no el que se esté mirando: el saldo de hoy no
   *  puede depender de dónde navegó el ojo). */
  libro: LibroMes | null
  /** La fila de hoy, ya validada por quien la trae: con cadena o null. */
  filaHoy: DiaConSaldo | null
  hoy: string
  caja: CajaHoy | null
  cuentas: CuentaBanco[]
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
}) {
  const ancla = libro?.ancla ?? null
  const diasDesdeAncla = ancla?.fecha ? diasEntre(ancla.fecha, hoy) : null

  const [abierto, setAbierto] = useState(false)
  const [saldo, setSaldo] = useState('')
  const [fecha, setFecha] = useState(hoy)
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)

  const abrir = () => {
    // ABRE EN BLANCO SI NO HAY FECHA. Sin fecha no hay saldo cargado: el 0 que
    // devuelve el backend en ese caso es el default de la fila vacía, no una
    // plata que alguien haya declarado, y precargarlo lo haría guardable de un
    // toque.
    //
    // Y LA FECHA VA CON SU MONTO. Precargar el saldo viejo con la fecha de HOY
    // arma un par que nunca fue verdad: guardarlo sin tocar nada re-ancla hoy
    // con el número del extracto viejo, deja fuera de la cadena todos los
    // movimientos tecleados en el medio y SUBE la plata. Medido en su momento:
    // 2.000.000 pasaban a 5.000.000 y una salida de 3.000.000 desaparecía.
    setSaldo(ancla?.fecha ? String(Math.round(ancla.saldo)) : '')
    setFecha(ancla?.fecha ?? hoy)
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

  const enRegistradora = caja?.efectivo_registradora ?? null
  // El total sale del backend (`caja_hoy.total`), no de sumar acá: con filtro de
  // sede el banco NO entra, y esa decisión ya está tomada allá.
  const total = caja?.total ?? null

  return (
    <section className="bg-white rounded-2xl border border-warm-200 overflow-hidden">
      <div className="grid grid-cols-2 divide-x divide-warm-100 border-b border-warm-100">
        {/* ── En el banco (el libro manda) ─────────────────────────────────── */}
        <div className="px-4 py-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500 flex items-center gap-1">
            <Landmark size={11} /> En el banco hoy
          </p>
          {filaHoy ? (<>
            <p className={`text-xl font-bold font-mono tabular-nums leading-tight mt-0.5 ${
              filaHoy.final < 0 ? 'text-danger-700' : 'text-warm-700'}`}>
              {plata(filaHoy.final)}
            </p>
            <p className="text-[11px] text-warm-500 leading-snug">
              Arrancó en {plata(filaHoy.inicial)}
              {filaHoy.total_entradas > 0 && <> · entró {plata(filaHoy.total_entradas)}</>}
              {filaHoy.total_salidas > 0 && <> · salió {plata(filaHoy.total_salidas)}</>}
            </p>
          </>) : (<>
            <p className="text-xl font-bold font-mono text-warm-400 leading-tight mt-0.5">—</p>
            {/* El motivo se elige por el DATO que falta, no por una bandera del
                mes. Con el ancla cargada esto NO puede decir «falta el saldo del
                extracto»: el backend solo deja hoy sin cadena si el ancla no
                existe (su fecha nunca puede ser futura, la rechaza el router) o
                si el libro directamente no cargó. */}
            <p className="text-[11px] text-warm-500 leading-snug">
              {!libro
                ? 'Todavía no se pudo leer el libro de este mes.'
                : !libro.ancla.fecha
                  ? 'Falta el saldo del extracto para saberlo.'
                  : `El saldo del extracto es del ${fechaCorta(libro.ancla.fecha)}: `
                    + 'la cadena todavía no llega hasta hoy.'}
            </p>
          </>)}
        </div>

        {/* ── El extracto, y su editor en la misma tarjeta ─────────────────── */}
        <button onClick={abrir} className="px-4 py-3 text-left hover:bg-warm-50 transition-colors">
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">
            Saldo del extracto
          </p>
          <p className="text-xl font-bold font-mono tabular-nums text-warm-700 leading-tight mt-0.5">
            {ancla?.fecha ? plata(ancla.saldo) : '—'}
          </p>
          <p className="text-[11px] text-warm-500 leading-snug flex items-center gap-1">
            {ancla?.fecha
              ? <>Del {fechaCorta(ancla.fecha)}
                  {diasDesdeAncla != null && diasDesdeAncla > 0
                    && ` · hace ${diasDesdeAncla} día${diasDesdeAncla === 1 ? '' : 's'}`}</>
              : 'Sin cargar — cargalo acá'}
            <Pencil size={10} className="shrink-0" />
          </p>
        </button>
      </div>

      {/* El editor abre EN LA MISMA TARJETA: es un dato que solo el dueño tiene
          (el sistema registra consignaciones, nunca un saldo bancario) y cada
          click de distancia es un día más de saldo viejo. */}
      {abierto && (
        <div className="border-b border-warm-200 bg-warm-50 px-4 py-3 space-y-2"
          onKeyDown={teclas({ listo, guardar, cancelar: () => setAbierto(false) })}>
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

      {/* ── El efectivo físico y el total ────────────────────────────────────
          Es el ÚNICO lugar del módulo donde aparece la plata de las
          registradoras, y cada sede dice DE DÓNDE sale su cifra: un turno
          abierto es un conteo vivo, un «último cuadre» puede ser de anteayer. */}
      <div className="grid grid-cols-2 divide-x divide-warm-100">
        <div className="px-4 py-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500 flex items-center gap-1">
            <Store size={11} /> En la registradora
          </p>
          <p className="text-xl font-bold font-mono tabular-nums text-warm-700 leading-tight mt-0.5">
            {enRegistradora != null ? plata(enRegistradora) : '—'}
          </p>
          <div className="space-y-0.5 mt-0.5">
            {(caja?.por_tienda ?? []).map(t => (
              <div key={t.tienda_id} className="flex items-center justify-between gap-2 text-[11px]">
                <span className="text-warm-500 truncate">{t.tienda_nombre}</span>
                <span className="font-mono tabular-nums text-warm-600 shrink-0">
                  {plata(t.efectivo)}{' '}
                  <span className="text-warm-400">· {ORIGEN_CAJA[t.origen] ?? t.origen}</span>
                </span>
              </div>
            ))}
          </div>
        </div>
        <div className="px-4 py-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">
            Con todo, hay
          </p>
          <p className="text-xl font-bold font-mono tabular-nums text-warm-700 leading-tight mt-0.5">
            {total != null ? plata(total) : '—'}
          </p>
          {/* El rótulo cuenta las sedes que el backend devolvió, no dice «las
              dos»: el día que se abra una tercera, la frase seguiría afirmando
              un número que ya no es. */}
          <p className="text-[11px] text-warm-500 leading-snug">
            {caja == null ? 'Todavía no se pudo leer la caja.'
              : caja.saldo_banco_incluido
                ? `Banco + ${caja.por_tienda.length === 1 ? 'la registradora'
                    : `las ${caja.por_tienda.length} registradoras`} — con esto arranca la proyección`
                : 'Solo la caja de esta sede: la cuenta del banco es de la empresa, no de la sede'}
          </p>
        </div>
      </div>

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
        {caja?.saldo_banco_fecha && caja.saldo_banco_origen !== 'libro' && (
          <p className="text-gold-700">
            Ahora mismo la proyección <b>no está usando el libro</b> sino el extracto del{' '}
            {fechaCorta(caja.saldo_banco_fecha)} a secas: la cadena no encadena (falta el ancla o
            la fila de configuración quedó inconsistente), así que los movimientos que tecleaste
            después no se le están sumando.
          </p>
        )}
        <p>
          «En la registradora» es efectivo físico y sale de cada sede por separado: un turno
          abierto es el conteo vivo, «conteo del cierre» es el de la última vez que cerraron y
          «último cuadre» es el respaldo cuando cerraron sin contar.
          {cuentas.length > 0 && (
            <> Los movimientos se cargan contra {cuentas.length === 1 ? 'la cuenta'
              : `las ${cuentas.length} cuentas`}: {cuentas.map(c => c.nombre).join(', ')}.</>
          )}
        </p>
      </ComoSeCalcula>
    </section>
  )
}
