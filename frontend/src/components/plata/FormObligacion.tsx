import { useEffect, useRef, useState } from 'react'
import { AlertCircle, Building2, Plus, Save } from 'lucide-react'
import api from '../../api/client'
import { conMiles, soloDigitos } from '../../utils/plata'
import { hoyBogota } from '../../utils/fechaLocal'
import type { Fuente } from '../../api/useDato'
import { SegunDato, NoSeSabe } from '../ui'
import { detalleDeError } from './banco'
import { Categoria, CORPORATIVO, Obligacion, Tienda } from './tipos'
import {
  Campo, CLS_INPUT, CLS_INPUT_PLATA, CLS_BOTON_GUARDAR, CLS_BOTON_SUAVE,
  ErrorCampo, teclas,
} from './campos'

/** El lugar del select mientras el catálogo no está: gris y mudo, sin afirmar
 *  que la lista esté vacía. Misma caja para no descuadrar la grilla. */
const CajaCatalogo = ({ texto }: { texto: string }) => (
  <p className="text-[11px] text-warm-500 bg-warm-100 rounded-xl px-3 py-3 min-h-[44px] flex items-center">
    {texto}
  </p>
)

/**
 * Cargar o corregir una obligación — LA FILA, no un modal.
 *
 * ═════════════════════════════════════════════════════════════════════════════
 * DOS COSAS PASAN ACÁ, Y LA SEGUNDA NO EXISTÍA
 * ═════════════════════════════════════════════════════════════════════════════
 * ALTA: pedido textual, «no quiero desplegar pestañas para agregar una
 * obligación». Antes eran 3 clicks (abrir el cajón, abrir el modal, llenar).
 *
 * EDICIÓN: el backend acepta los diez campos por `PATCH /costos/obligaciones/{id}`
 * (routers/costos.py + schemas/costos.py: `ObligacionUpdate` con `exclude_unset`)
 * desde siempre, y el frontend le mandaba UNO solo, `fecha_vencimiento`. O sea
 * que corregir el monto del arriendo obligaba a ANULAR y volver a cargar — y eso
 * se lleva puestos los pagos ya registrados, que quedan colgando de una
 * obligación anulada. Con el formulario a la vista, editar cuesta lo mismo que
 * cargar.
 *
 * ═════════════════════════════════════════════════════════════════════════════
 * LO QUE NO SE PUEDE PERDER
 * ═════════════════════════════════════════════════════════════════════════════
 *  - EL FORMULARIO NO SE ESCONDE CUANDO UN CATÁLOGO NO VUELVE. Con las sedes
 *    caídas el alta sigue siendo posible entera (Corporativo no necesita
 *    catálogo, y es el caso del arriendo y la nómina); con las categorías caídas
 *    no se puede guardar —el backend las exige— y eso se DICE, con su botón de
 *    reintentar, en vez de dejar un «Guardar» gris sin explicación.
 *  - EL AVISO DE «VENCE» VACÍO, EN VIVO. Sin fecha la obligación se guarda igual
 *    y cuenta en el resultado del mes, pero NO entra a la agenda ni a la
 *    proyección. Enterarse después —viendo la agenda vacía— es exactamente lo
 *    que hace pensar que el módulo no guardó nada.
 *  - DEVENGO ≠ VENCIMIENTO. El devengo es el mes al que PERTENECE el costo
 *    (manda en el P&L); el vencimiento es cuándo se paga (manda en la agenda).
 *  - CORPORATIVO NO ES «TODAS». El arriendo y la nómina no pertenecen a ninguna
 *    sede: `tienda_id` va en null y esa es una respuesta, no un dato faltante.
 *  - «HOY» SALE DEL RELOJ DE COLOMBIA. La versión vieja de este formulario usaba
 *    `new Date().toLocaleDateString('en-CA')` —el reloj del NAVEGADOR— para
 *    precargar el devengo. Con el admin viajando, o con la tablet mal
 *    configurada, el costo se devengaba en el día equivocado: la misma familia
 *    de error (una fecha que está CERCA de la correcta) que este módulo viene
 *    arrastrando.
 */
export default function FormObligacion({
  categorias, tiendas, editando, onListo, onCancelar,
}: {
  categorias: Fuente<Categoria[]>
  tiendas: Fuente<Tienda[]>
  /** null = alta. Con valor = corrección de esa obligación. */
  editando?: Obligacion | null
  /** Guardó: quien monta recarga. Recibe true si fue un alta (para el aviso). */
  onListo: (fueAlta: boolean) => void
  /** Solo en edición: cerrar sin guardar. */
  onCancelar?: () => void
}) {
  const hoy = hoyBogota()
  const e = editando ?? null

  /**
   * El catálogo LEÍDO, o `null` si todavía no está en la mano.
   *
   * `null` acá NO significa «no hay categorías»: significa que no se sabe. Se
   * usa solo para el default imperativo del efecto de abajo; lo que se AFIRMA en
   * pantalla se decide adentro de cada rama de `SegunDato`.
   */
  const cats = categorias.dato.estado === 'listo' ? categorias.dato.valor : null

  const [concepto, setConcepto] = useState(e?.concepto ?? '')
  const [categoriaId, setCategoriaId] = useState(String(e?.categoria_id ?? cats?.[0]?.id ?? ''))
  const [monto, setMonto] = useState(e ? String(Math.round(e.monto)) : '')
  const [devengo, setDevengo] = useState(e?.fecha_devengo ?? hoy)
  const [vence, setVence] = useState(e?.fecha_vencimiento ?? '')
  const [beneficiario, setBeneficiario] = useState(e?.beneficiario ?? '')
  const [sede, setSede] = useState(e ? (e.tienda_id == null ? CORPORATIVO : String(e.tienda_id)) : CORPORATIVO)
  const [nota, setNota] = useState(e?.nota ?? '')
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)
  const [ultimo, setUltimo] = useState('')

  const refConcepto = useRef<HTMLInputElement>(null)

  /**
   * `true` = la fila que se está corrigiendo vive en una categoría que el
   * desplegable NO ofrece; `null` = todavía no se sabe (el catálogo no llegó).
   *
   * El `null` no es cosmético: mientras la lista no se leyó no se puede AFIRMAR
   * que la categoría falte, y afirmarlo pintaría el aviso sobre una pregunta que
   * nunca se hizo. Es la regla 3 del README de `ui/`.
   */
  const fueraDelCatalogo = !e ? false
    : cats === null ? null
      : !cats.some(c => c.id === e.categoria_id)

  // EL DEFAULT SE SINCRONIZA CUANDO LLEGA EL CATÁLOGO. El useState corre en el
  // PRIMER render, cuando la lista todavía no llegó porque el fetch va en un
  // hook del padre. Sin esto el estado quedaba en '' para siempre —el componente
  // no remonta— y el resultado era el peor posible: el select se ve CON una
  // opción elegida (React marca la primera cuando el value controlado no matchea
  // ninguna) y el botón «Guardar» gris, sin explicación. El dueño tecleaba todo
  // y no podía guardar. No pisa lo que ya eligió: solo llena el hueco.
  //
  // Y EN EDICIÓN NO ELIGE NADIE POR EL DUEÑO. Corrigiendo una fila cuya categoría
  // no está en la lista, este efecto le ponía la PRIMERA opción: el select se veía
  // «arriendo» sobre una fila que era otra cosa, y guardar sin abrir el desplegable
  // la movía de categoría sin que nadie lo pidiera. Sobre la declaración del
  // impoconsumo eso valía $12.447.999 de piso inflado y $11.525.925,93 de margen
  // neto hundido en el mes del devengo — la misma plata contada dos veces. Ahora se
  // BORRA la elección: el select queda vacío, «Guardar» gris (el `listo` de abajo
  // exige `categoriaId`) y el aviso de al lado dice qué pasa. Un campo vacío es una
  // pregunta; un campo con la opción equivocada es una respuesta falsa.
  useEffect(() => {
    if (!cats || cats.length === 0) return
    if (categoriaId && cats.some(c => c.id === Number(categoriaId))) return
    if (e) {
      if (categoriaId) setCategoriaId('')
      return
    }
    if (!categoriaId) setCategoriaId(String(cats[0].id))
  }, [cats, categoriaId, e])

  const listo = !!concepto.trim() && Number(monto) > 0 && !!devengo && !!categoriaId

  const guardar = async () => {
    // GUARDA DE REENTRADA. Enter y el botón llaman a lo mismo, y entre el
    // toque y la respuesta hay una ida y vuelta: dos toques ahí adentro
    // escribían DOS veces. En una tablet con conexión lenta eso duplica un
    // movimiento, un pago o una obligación, y `registrar_pago` del backend
    // ni siquiera valida contra el saldo.
    if (guardando) return
    if (!listo) return
    setGuardando(true); setError('')
    const cuerpo = {
      categoria_id: Number(categoriaId),
      concepto: concepto.trim(),
      beneficiario: beneficiario.trim() || null,
      monto: Number(monto),
      fecha_devengo: devengo,
      fecha_vencimiento: vence || null,
      // Corporativo = sin sede: es el caso del arriendo y la nómina.
      tienda_id: sede === CORPORATIVO ? null : Number(sede),
      nota: nota.trim() || null,
    }
    try {
      if (e) {
        await api.patch(`/costos/obligaciones/${e.id}`, cuerpo)
        onListo(false)
      } else {
        await api.post('/costos/obligaciones', cuerpo)
        setUltimo(`${concepto.trim()} · ${conMiles(monto)}`)
        // Se limpia lo que cambia de una carga a la otra y se CONSERVA lo que
        // se repite (categoría, devengo, sede): cargar el arriendo y la luz del
        // mismo mes son dos conceptos y dos montos, no ocho campos de nuevo.
        setConcepto(''); setMonto(''); setBeneficiario(''); setNota('')
        refConcepto.current?.focus()
        onListo(true)
      }
    } catch (err) {
      setError(detalleDeError(err, 'No se pudo guardar. Reintentá.'))
    } finally { setGuardando(false) }
  }

  return (
    <div className={`px-3 py-3 space-y-2 ${e ? 'bg-forest-50 border-y border-forest-100' : 'bg-warm-50 border-b border-warm-100'}`}
      onKeyDown={teclas({ listo, guardar, cancelar: onCancelar })}>
      <div className="flex items-center gap-1.5">
        {e ? <Save size={13} className="text-forest shrink-0" />
           : <Plus size={13} className="text-forest shrink-0" />}
        <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500">
          {e ? `Corregir «${e.concepto}»` : 'Cargar una obligación'}
        </p>
      </div>

      {/* LOS AVISOS DE CATÁLOGO VAN ARRIBA DE LOS CAMPOS, y el formulario sigue
          montado. Esconderlo le rompe el trabajo de las 7 de la mañana; dejarlo
          mudo lo deja tecleando contra un «Guardar» gris que no explica nada. */}
      <SegunDato
        dato={categorias.dato}
        cargando={null}
        falla={m => (
          <NoSeSabe onReintentar={categorias.recargar}
            mensaje={`${m} — sin la categoría no se puede guardar la obligación. Lo demás se `
              + 'puede ir tecleando igual.'} />
        )}
        listo={cs => cs.length === 0 ? (
          <NoSeSabe mensaje="No hay ninguna categoría de gasto cargada, así que todavía no se puede guardar una obligación." />
        ) : null}
      />
      <SegunDato
        dato={tiendas.dato}
        cargando={null}
        falla={m => (
          <NoSeSabe onReintentar={tiendas.recargar}
            mensaje={`${m} — no se pueden elegir sedes. Se puede guardar igual como Corporativo, `
              + 'que es lo que corresponde al arriendo y a la nómina.'} />
        )}
        listo={() => null}
      />

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 items-end">
        <Campo label="Concepto" ancho="col-span-2">
          <input ref={refConcepto} value={concepto} onChange={ev => setConcepto(ev.target.value)}
            placeholder="Arriendo agosto, energía, nómina quincena…" className={CLS_INPUT} />
        </Campo>
        <Campo label="Categoría">
          <SegunDato
            dato={categorias.dato}
            cargando={<CajaCatalogo texto="Cargando las categorías…" />}
            falla={() => <CajaCatalogo texto="Sin categorías para elegir" />}
            listo={cs => cs.length === 0
              ? <CajaCatalogo texto="No hay categorías cargadas" />
              : (
                <select value={categoriaId} onChange={ev => setCategoriaId(ev.target.value)} className={CLS_INPUT}>
                  {/* LA OPCIÓN VACÍA EXISTE Y NO ES DECORACIÓN: es el único valor
                      que puede representar «la categoría de esta fila no está en
                      la lista». Sin ella el select tendría que mostrar alguna
                      opción real, que es justamente la mentira que se sacó. */}
                  {!categoriaId && <option value="">— elegí una —</option>}
                  {cs.map(c => <option key={c.id} value={c.id}>{c.nombre}</option>)}
                </select>
              )}
          />
        </Campo>
        <Campo label="Monto">
          <input type="text" inputMode="numeric" value={conMiles(monto)}
            onChange={ev => setMonto(soloDigitos(ev.target.value))} placeholder="0"
            aria-label="Monto de la obligación" className={CLS_INPUT_PLATA} />
        </Campo>

        <Campo label="Mes al que pertenece">
          <input type="date" value={devengo} onChange={ev => setDevengo(ev.target.value)}
            className={CLS_INPUT} />
        </Campo>
        <Campo label="Vence (opcional)">
          <input type="date" value={vence} onChange={ev => setVence(ev.target.value)}
            className={CLS_INPUT} />
        </Campo>
        <Campo label="Beneficiario (opcional)">
          <input value={beneficiario} onChange={ev => setBeneficiario(ev.target.value)}
            placeholder="A quién se le paga" className={CLS_INPUT} />
        </Campo>
        <Campo label="Sede">
          {/* «Corporativo» va SIEMPRE, con catálogo o sin él: no sale de la lista
              de sedes, es la ausencia de sede — y es el caso del arriendo. */}
          <select value={sede} onChange={ev => setSede(ev.target.value)} className={CLS_INPUT}>
            <option value={CORPORATIVO}>Corporativo / todas</option>
            {tiendas.dato.estado === 'listo'
              && tiendas.dato.valor.map(t => <option key={t.id} value={t.id}>{t.nombre}</option>)}
          </select>
        </Campo>

        <Campo label="Nota (opcional)" ancho="col-span-2 sm:col-span-3">
          <input value={nota} onChange={ev => setNota(ev.target.value)} className={CLS_INPUT} />
        </Campo>
        <div className="col-span-2 sm:col-span-1 flex gap-2">
          {onCancelar && (
            <button type="button" onClick={onCancelar} className={CLS_BOTON_SUAVE}>Cancelar</button>
          )}
          <button type="button" onClick={guardar} disabled={guardando || !listo}
            className={`${CLS_BOTON_GUARDAR} flex-1`}>
            {guardando ? 'Guardando…' : e ? 'Guardar cambios' : 'Guardar'}
          </button>
        </div>
      </div>

      {/* LA CATEGORÍA DE ESTA FILA NO ESTÁ EN EL DESPLEGABLE. Pasa con las
          desactivadas y con las que maneja el sistema solo. Se dice CUÁL es —el
          dueño la ve en la lista de arriba— y se dice que guardar la MUEVE, que
          es la consecuencia que el select vacío no comunica por sí solo.
          `=== true` y no truthy: `null` es «el catálogo no llegó» y ahí no se
          afirma nada. */}
      {fueraDelCatalogo === true && (
        <p className="text-[11px] text-gold-700 bg-gold-50 border border-gold-200 rounded-lg px-2.5 py-1.5 flex items-start gap-1.5">
          <AlertCircle size={12} className="mt-0.5 shrink-0" />
          <span>
            Esta cuenta está en <b>«{e?.categoria_nombre || 'una categoría que ya no se ofrece'}»</b>,
            que no está entre las que se pueden elegir. El desplegable quedó vacío a propósito:
            si elegís una y guardás, <b>la cuenta se mueve a esa categoría</b> y el resultado del
            mes cambia. Si no querías moverla, cancelá.
          </span>
        </p>
      )}

      {/* EN VIVO: sin fecha de pago el costo se guarda y cuenta en el resultado,
          pero no se agenda. Decirlo después es lo que hace pensar que no guardó. */}
      {!vence && (
        <p className="text-[11px] text-gold-700 bg-gold-50 border border-gold-200 rounded-lg px-2.5 py-1.5 flex items-start gap-1.5">
          <AlertCircle size={12} className="mt-0.5 shrink-0" />
          <span>
            Sin «Vence» se guarda igual y cuenta en el resultado del mes, pero <b>no entra a la
            agenda ni a la proyección</b>: queda en «Sin fecha de pago» hasta que le pongas una.
          </span>
        </p>
      )}

      <p className="text-[11px] text-warm-400 leading-snug flex items-start gap-1.5">
        <Building2 size={12} className="mt-0.5 shrink-0" />
        <span>
          «Mes al que pertenece» es el devengo: decide en qué mes pesa el costo en el resultado,
          aunque se pague otro día. Si el gasto no es de una sede puntual (arriendo, nómina),
          dejalo en Corporativo.
        </span>
      </p>

      <ErrorCampo msg={error} />
      {!e && !error && ultimo && (
        <p className="text-[11px] font-semibold text-success-600">Guardada: {ultimo}</p>
      )}
    </div>
  )
}
