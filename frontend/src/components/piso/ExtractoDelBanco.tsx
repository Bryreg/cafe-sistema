import { useEffect, useRef, useState } from 'react'
import { Landmark } from 'lucide-react'
import api from '../../api/client'
import { conMiles, soloDigitos } from '../../utils/plata'
import { Dato } from '../../api/dato'
import { SegunDato, NoSeSabe } from '../ui'
import { LibroMes, detalleDeError, diasEntre, fechaCorta, plata } from '../plata/banco'
import { filaConSaldoDe } from '../plata/useLibro'
import { Campo, CLS_INPUT, CLS_INPUT_PLATA, CLS_BOTON_GUARDAR, ErrorCampo, teclas } from '../plata/campos'

// ─── El extracto del banco, siempre a la vista ───────────────────────────────
//
// ═════════════════════════════════════════════════════════════════════════════
// POR QUÉ ESTO SUBIÓ HASTA ACÁ, Y POR QUÉ YA NO ESTÁ DETRÁS DE UN BOTÓN
// ═════════════════════════════════════════════════════════════════════════════
// Es lo que el dueño hace TODOS LOS DÍAS: abre la app del banco y copia el
// saldo. En la página vieja vivía a cuatro mil píxeles de scroll y detrás de un
// click. Un gesto diario escondido detrás de dos gestos es un gesto que se
// deja de hacer, y el saldo viejo envenena las dos proyecciones de la página:
// el piso de caja arranca de este número y el punto de quiebre también.
//
// Por eso los campos están MONTADOS, no plegados. No hay «abrir el editor»:
// hay un campo con el saldo de hoy y un botón.
//
// ── EL FORMULARIO NO SE ESCONDE CUANDO EL LIBRO NO VOLVIÓ (regla 5) ───────
// El saldo del extracto lo tiene el dueño en la mano: no depende de este fetch.
// Con el libro caído los campos abren en blanco, el aviso lo dice arriba, y lo
// que se teclee se guarda igual.
//
// ── LA FECHA VIAJA CON SU MONTO ───────────────────────────────────────────
// Precargar el saldo viejo con la fecha de HOY arma un par que nunca fue
// verdad: guardarlo sin tocar nada re-ancla hoy con el número del extracto
// viejo, deja fuera de la cadena todos los movimientos tecleados en el medio y
// SUBE la plata. Medido en su momento en este repo: 2.000.000 pasaban a
// 5.000.000 y una salida de 3.000.000 desaparecía. El default sale del ancla
// leída, entera, o queda en blanco.

export default function ExtractoDelBanco({
  libro, hoy, pedidoFoco, onGuardado, onRecargarLibro, sedeNombre,
}: {
  /** El libro del MES DE HOY: de ahí sale el ancla y la fila de hoy. */
  libro: Dato<LibroMes>
  hoy: string
  /** Contador que sube cuando otra parte de la página manda el foco acá. */
  pedidoFoco: number
  /** Guardó el ancla: hay que repedir el libro, el flujo y el piso (los tres lo leen). */
  onGuardado: () => void
  onRecargarLibro: () => void
  /** El nombre de la sede que se está mirando (para el título). Ausente = «Ambas». */
  sedeNombre?: string
}) {
  /**
   * El ancla LEÍDA, o `null` mientras no esté en la mano.
   *
   * `null` acá NO significa «no hay ancla»: significa que no se sabe. Solo
   * alimenta el default imperativo del efecto de abajo; lo que se AFIRMA en
   * pantalla se decide adentro de cada rama de `SegunDato`.
   */
  const ancla = libro.estado === 'listo' ? libro.valor.ancla : null
  // La sede del libro que se está mirando: el ancla se guarda para ESA sede
  // (null = la global/histórica). Así cada sede carga el saldo de su extracto.
  const sedeDelLibro = libro.estado === 'listo' ? (libro.valor.tienda_id ?? null) : null

  const [saldo, setSaldo] = useState('')
  const [fecha, setFecha] = useState(hoy)
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)
  const [tocado, setTocado] = useState(false)
  const refSaldo = useRef<HTMLInputElement>(null)

  /**
   * El default se sincroniza CUANDO LLEGA EL LIBRO, no en el primer render.
   *
   * El `useState` corre antes de que el fetch vuelva —vive en la página— y sin
   * esto los campos quedarían vacíos para siempre porque el componente no
   * remonta. Es un bug ya cazado en los formularios vecinos de este módulo.
   *
   * Y NO PISA LO QUE EL DUEÑO ESTÁ TECLEANDO: `tocado` lo bloquea en cuanto
   * escribe la primera tecla. Que el libro se repida por un guardado de otro
   * banner no puede borrarle el número que tiene a medio copiar del celular.
   */
  useEffect(() => {
    if (tocado || !ancla) return
    setSaldo(ancla.fecha ? String(Math.round(ancla.saldo)) : '')
    setFecha(ancla.fecha ?? hoy)
  }, [ancla?.saldo, ancla?.fecha, hoy, tocado]) // eslint-disable-line react-hooks/exhaustive-deps

  // Otra parte de la página mandó el foco acá («Copiar el saldo del extracto»).
  // Se ignora el montaje (`pedidoFoco` arranca en 0).
  useEffect(() => {
    if (pedidoFoco > 0) refSaldo.current?.focus()
  }, [pedidoFoco])

  const listo = !!fecha && !!saldo
  const guardar = async () => {
    // GUARDA DE REENTRADA: Enter y el botón llaman a lo mismo, y entre el toque
    // y la respuesta hay una ida y vuelta. Dos toques ahí adentro escriben dos
    // veces, y en una tablet con la señal del local eso pasa.
    if (guardando || !listo) return
    setGuardando(true); setError('')
    try {
      // `saldo` es lo TECLEADO, no algo derivado de un `Dato`, y `listo` ya
      // exige que no esté vacío. El `|| 0` que había acá no se podía disparar
      // nunca, y dejarlo escrito es dejar el idioma prohibido a mano para que
      // alguien lo copie a un lugar donde sí miente.
      await api.put('/banco/ancla', { saldo: Number(saldo), fecha, tienda_id: sedeDelLibro })
      setTocado(false)
      onGuardado()
    } catch (e) {
      setError(detalleDeError(e, 'No se pudo guardar el saldo. Reintentá.'))
    } finally { setGuardando(false) }
  }

  return (
    <div className="px-4 py-3 space-y-2.5" onKeyDown={teclas({ listo, guardar })}>
      <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500 flex items-center gap-1">
        <Landmark size={11} /> El extracto del banco{sedeNombre ? ` · ${sedeNombre}` : ''}
      </p>

      {/* En «Ambas» con el modelo por sede activo, el saldo combinado se arma con
          el de cada sede: acá se cargaría el global, que ya no manda. Se dice y se
          manda al dueño a cargar el de cada sede. */}
      {libro.estado === 'listo' && libro.valor.por_sede
        && (libro.valor.tienda_id ?? null) === null && (
        <p className="text-[12px] text-gold-800 bg-gold-50 border border-gold-200 rounded-xl px-3 py-2 leading-snug">
          El saldo de <b>«Ambas»</b> se arma sumando el de cada sede. Elegí <b>Vida</b> o
          <b> Palmetto</b> arriba y cargá el extracto de cada una por separado.
        </p>
      )}

      {/* Lo que el libro dice hoy: el saldo encadenado, que es el que usan las
          proyecciones. Va ARRIBA del campo para que se vea contra qué se compara
          el número que se está por copiar. */}
      <SegunDato
        dato={libro}
        cargando={<p className="text-xl font-bold font-mono tabular-nums text-warm-400">…</p>}
        falla={m => (<>
          <p className="text-xl font-bold font-mono tabular-nums text-warm-400">—</p>
          <NoSeSabe onReintentar={onRecargarLibro}
            mensaje={`${m} — no se pudo leer el saldo que ya estaba cargado, así que los campos `
              + 'abren en blanco. Lo que teclees acá se guarda igual.'} />
        </>)}
        listo={l => {
          // LA CADENA SE DECIDE POR LA FILA DE HOY, no por `cadena_completa`:
          // con el ancla a mitad de mes —el caso normal— esa bandera es false y
          // el saldo de hoy es exacto igual.
          const filaHoy = filaConSaldoDe(l, hoy)
          return (<>
            <p className={`text-xl font-bold font-mono tabular-nums leading-tight ${
              filaHoy === null ? 'text-warm-400' : filaHoy.final < 0 ? 'text-danger-700' : 'text-warm-700'}`}>
              {filaHoy === null ? '—' : plata(filaHoy.final)}
            </p>
            <p className="text-[11px] text-warm-500 leading-snug">
              {filaHoy === null
                ? (!l.ancla.fecha
                  ? 'Saldo del banco hoy — falta el extracto para saberlo.'
                  : `Saldo del banco hoy — el extracto es del ${fechaCorta(l.ancla.fecha)} y la `
                    + 'cadena todavía no llega hasta hoy.')
                : <>Saldo del banco hoy, según el libro.
                    {l.ancla.fecha && <> Último extracto: {fechaCorta(l.ancla.fecha)}
                      {diasEntre(l.ancla.fecha, hoy) > 0
                        && ` · hace ${diasEntre(l.ancla.fecha, hoy)} `
                          + `día${diasEntre(l.ancla.fecha, hoy) === 1 ? '' : 's'}`}.</>}
                  </>}
            </p>
          </>)
        }} />

      <div className="grid grid-cols-2 gap-2">
        <Campo label="Saldo del extracto">
          <input type="text" inputMode="numeric" value={conMiles(saldo)} ref={refSaldo}
            onChange={e => { setTocado(true); setSaldo(soloDigitos(e.target.value)) }}
            aria-label="Saldo del extracto" className={CLS_INPUT_PLATA} />
        </Campo>
        <Campo label="¿De qué día es?">
          <input type="date" value={fecha} max={hoy}
            onChange={e => { setTocado(true); setFecha(e.target.value) }}
            className={CLS_INPUT} />
        </Campo>
      </div>

      <ErrorCampo msg={error} />

      <button onClick={guardar} disabled={guardando || !listo}
        className={`${CLS_BOTON_GUARDAR} w-full`}>
        {guardando ? 'Guardando…' : 'Guardar el saldo'}
      </button>

      <p className="text-[11px] text-warm-400 leading-snug">
        Es el saldo con el que <b>arranca</b> ese día: de ahí para adelante el libro suma lo que
        entra y resta lo que sale. El sistema nunca ve la cuenta — este número lo ponés vos.
      </p>
    </div>
  )
}
