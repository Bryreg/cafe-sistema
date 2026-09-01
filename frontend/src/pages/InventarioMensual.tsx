import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { Boxes, Check, Save, AlertTriangle, Lock, X } from 'lucide-react'
import BaristaLayout from '../components/BaristaLayout'
import NivelEnvase from '../components/NivelEnvase'
import { abreBloque, ordenarPorRecorrido } from '../utils/ordenConteo'

interface Item {
  id: number; producto_id: number; producto_nombre: string
  categoria: string; unidad_medida: string
  fraccionable?: boolean; envase?: 'bolsa' | 'botella' | null
  /** Posición en el recorrido físico del local (ver utils/ordenConteo). */
  orden_conteo?: number | null
  cantidad_sistema: number; cantidad_real: number | null
  // false = el número lo puso el cierre, no una persona (ver services/inventario_mensual)
  fue_contado?: boolean
  diferencia: number; valor_unitario: number; valor_diferencia: number
}
interface Inv {
  id: number; anio: number; mes: number; estado: string
  valor_diferencia_total: number; items: Item[]
  // Cobertura real del conteo, calculada en el servidor. Después de cerrar no se
  // puede derivar del físico: el cierre rellena todo lo no contado con el sistema.
  contados: number; total_items: number
  // Renglones que el servidor NO guardó y por qué. Ahora los dice en vez de
  // descartarlos en silencio; viene solo en la respuesta de guardar.
  no_guardados?: { id: number | null; producto: string; motivo: string }[]
}

/** Lo tecleado → número. Acepta la coma como decimal y SUMAS: «12+8» son 20.
 *
 *  Las dos cosas salieron del piso, no de una idea de diseño:
 *
 *  · La coma. El campo era `type="number"` y ahí el navegador tira lo que no
 *    entiende sin decir nada: tecleando «1,5» entregaba «15». En un conteo eso
 *    no es un renglón que no guarda, es uno que guarda DIEZ VECES de más, y no
 *    se descubre hasta que la conciliación muestra una fuga que no existió.
 *
 *  · La suma. Así se cuenta de verdad: hay seis en la vitrina y ocho en la
 *    bodega, y la barista escribe «6+8». Con `type="number"` el navegador
 *    MOSTRABA «6+8» y entregaba vacío, así que el renglón viajaba sin valor:
 *    la pantalla decía una cosa y se guardaba otra. Ese era el «el botón no
 *    guarda lo que queda escrito».
 *
 *  Se evalúa con una gramática de sumas y restas, no con `eval`: una suma de
 *  términos decimales y nada más. Cualquier otra cosa devuelve `null`, se pinta
 *  en rojo y NO se manda — inventar un número es peor que no guardar.
 *
 *  Y UN TOTAL NEGATIVO TAMPOCO ES UN CONTEO. Es la contracara de haber
 *  enseñado a sumar: quien escribe «6+8» también escribe «8-10», y ese −2
 *  entraba como existencia física. Al cerrar el mes se volvía una diferencia
 *  contra el sistema —los −2 más todo el stock teórico— o sea un faltante en
 *  pesos que nunca pasó. En el estante no hay cantidades negativas: si la
 *  cuenta da abajo de cero, está mal tecleada. */
export const aNumero = (v: string): number | null => {
  const t = (v ?? '').replace(/\s+/g, '').replace(/,/g, '.')
  if (t === '') return null
  const partes = t.match(/[+-]?\d*\.?\d+/g)
  if (!partes || partes.join('') !== t) return null
  const total = partes.reduce((a, x) => a + Number(x), 0)
  return Number.isFinite(total) && total >= 0 ? total : null
}

/** Por qué la casilla está en rojo, cuando hay algo corto y útil que decir.
 *
 *  «8-10» no es un dedazo evidente como «1..2»: la resta es válida y el error
 *  es de signo, así que el borde rojo solo se lee como «no me deja escribir».
 *  Que diga qué pasa, o quien cuenta va a pelearse con la casilla en vez de
 *  corregir la cuenta. */
const motivoInvalido = (v: string): string | null => {
  const t = (v ?? '').replace(/\s+/g, '').replace(/,/g, '.')
  const partes = t.match(/[+-]?\d*\.?\d+/g)
  if (partes && partes.join('') === t) {
    const total = partes.reduce((a, x) => a + Number(x), 0)
    if (Number.isFinite(total) && total < 0) return `da ${total}: no se puede contar en negativo`
  }
  return null
}

/** Está a medio escribir («12+»): no es un error todavía, así que no se pinta
 *  en rojo mientras el dedo sigue sobre el teclado. */
const aMedias = (v: string) => /[+\-.,]$/.test((v ?? '').trim())

const MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

export default function InventarioMensual() {
  const { user } = useAuth()
  const now = new Date()
  const [inv, setInv] = useState<Inv | null>(null)
  const [loading, setLoading] = useState(true)
  const [valores, setValores] = useState<Record<number, string>>({})  // itemId → física (string)
  const [guardando, setGuardando] = useState(false)
  const [cerrando, setCerrando] = useState(false)
  const [msg, setMsg] = useState('')
  const [borradorInfo, setBorradorInfo] = useState<string | null>(null)
  // Un guardado que falló NO puede avisarse con un renglón gris que se borra
  // solo a los 1,5 segundos: en un conteo de 123 productos, quien mira el
  // estante y no la pantalla se entera cuando ya cerró el mes.
  const [falloGuardar, setFalloGuardar] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)
  const draftTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Último estado confirmado por el servidor (para poder descartar el borrador)
  const serverVals = useRef<Record<number, string>>({})
  // Contador de ediciones: si tipean mientras el PATCH está en vuelo, no hay que
  // desarmar el borrador al volver (ese tipeo no viajó en el request).
  const editGen = useRef(0)

  // ── Borrador persistente: sobrevive si salen a revisar otra pantalla ────────
  const draftKey = `invmensual_borrador_${user?.tienda_id ?? 0}_${now.getFullYear()}_${now.getMonth() + 1}`

  // Se precarga SOLO lo que contó una persona (`fue_contado`), nunca todo lo que
  // tenga `cantidad_real`. Sobre un mes reabierto la distinción es crítica: el
  // cierre anterior rellenó cantidad_real en TODOS los renglones con el valor del
  // sistema, así que precargar por cantidad_real mostraba el conteo como
  // completo Y —peor— `guardar()` reenviaba esos 180 valores al servidor, que los
  // marca como contados. El conteo parcial se convertía en "180 de 180" con solo
  // abrir la pantalla y tocar guardar.
  //
  // Costo asumido: en un conteo anterior a la bandera los renglones ya cargados
  // aparecen vacíos y hay que recontarlos. Es la dirección correcta del error —
  // pedir un conteo de más nunca miente; darlo por hecho sí.
  const valoresDesde = (items: Item[]) => {
    const v: Record<number, string> = {}
    items.forEach(it => {
      if (it.fue_contado && it.cantidad_real != null) v[it.id] = String(it.cantidad_real)
    })
    return v
  }

  useEffect(() => {
    if (!user?.tienda_id) { setLoading(false); setMsg('No se pudo determinar la sede'); return }
    api.post<Inv>('/inventario-mensual/iniciar', null, { params: { tienda_id: user.tienda_id, anio: now.getFullYear(), mes: now.getMonth() + 1 } })
      .then(r => {
        setInv(r.data)
        const v = valoresDesde(r.data.items)
        serverVals.current = v
        // Restaurar lo tipeado sin "Guardar avance" (borradores de menos de 20h)
        let merged = v
        try {
          const raw = r.data.estado !== 'cerrado' ? localStorage.getItem(draftKey) : null
          if (raw) {
            const d = JSON.parse(raw)
            if (d.ts && Date.now() - d.ts <= 20 * 3600 * 1000 && d.valores && Object.keys(d.valores).length) {
              // EL BORRADOR NO PUEDE BORRAR LO QUE EL SERVIDOR YA TIENE. Era
              // `{ ...v, ...d.valores }`, y ahí una casilla vacía del borrador
              // —quedó vacía porque alguien borró el número para retipearlo, y
              // el autoguardado pasó justo en ese instante— tapaba el valor
              // confirmado. En un conteo que cruza dos días eso se ve como
              // «ayer contamos 51 y hoy la pantalla los muestra en blanco»,
              // con los 51 sanos en la base. Ahora el borrador sólo aporta
              // donde ESCRIBE algo, o donde el servidor no tiene nada.
              merged = { ...v }
              for (const [id, val] of Object.entries(d.valores as Record<string, string>)) {
                if (val !== '' || merged[Number(id)] === undefined) merged[Number(id)] = val
              }
              setDirty(true)
              setBorradorInfo(new Date(d.ts).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' }))
            } else {
              localStorage.removeItem(draftKey)
            }
          }
        } catch { /* borrador corrupto: ignorar */ }
        setValores(merged)
      })
      .catch(() => setMsg('No se pudo iniciar el conteo'))
      .finally(() => setLoading(false))
  }, [user?.tienda_id])  // eslint-disable-line

  // Autoguardado silencioso del borrador (respaldo del boton "Guardar avance")
  useEffect(() => {
    if (!dirty) return
    if (draftTimer.current) clearTimeout(draftTimer.current)
    draftTimer.current = setTimeout(() => {
      try { localStorage.setItem(draftKey, JSON.stringify({ valores, ts: Date.now() })) } catch { /* almacenamiento lleno: no bloquear el conteo */ }
    }, 800)
    return () => { if (draftTimer.current) clearTimeout(draftTimer.current) }
  }, [valores, dirty])  // eslint-disable-line

  const setValor = (id: number, v: string) => {
    setValores(p => ({ ...p, [id]: v }))
    editGen.current += 1
    setDirty(true)
  }

  // Limpieza síncrona: cancela el timer pendiente ANTES de borrar la clave, para
  // que un autoguardado en vuelo no resucite el borrador recién eliminado.
  const limpiarBorrador = () => {
    if (draftTimer.current) { clearTimeout(draftTimer.current); draftTimer.current = null }
    localStorage.removeItem(draftKey)
  }

  const descartarBorrador = () => {
    limpiarBorrador()
    setValores({ ...serverVals.current })
    setDirty(false); setBorradorInfo(null)
  }

  const cerrado = inv?.estado === 'cerrado'
  // El conteo de fin de mes es EL MISMO recorrido físico que el de apertura y
  // cierre, así que va en el mismo orden. Antes agrupaba por categoría y
  // alfabético adentro: eso obligaba a caminar el local tres veces, porque las
  // zonas del recorrido mezclan categorías (el bloque de la vitrina tiene café
  // y pastelería juntos). El corte entre zonas lo dibuja el salto de bloque.
  const ordenados = useMemo(
    () => ordenarPorRecorrido(inv?.items ?? [], it => it.producto_nombre),
    [inv],
  )

  const contados = useMemo(() => Object.values(valores).filter(v => aNumero(v) !== null).length, [valores])

  /** Renglones que el SERVIDOR tiene contados y que en pantalla están en blanco.
   *
   *  Nunca deberían existir —el borrador ya no puede pisar lo guardado— pero se
   *  dicen igual, porque el modo en que fallaba era invisible desde el piso: la
   *  barista ve una casilla vacía y no tiene forma de saber si nadie lo contó o
   *  si lo contó ella ayer y la pantalla no se lo está mostrando. Las dos cosas
   *  se ven idénticas y llevan a decisiones opuestas: recontar todo, o cerrar el
   *  mes creyendo que faltaba. */
  const perdidos = useMemo(
    () => (inv?.items ?? []).filter(
      it => it.fue_contado && it.cantidad_real != null && (valores[it.id] ?? '') === ''),
    [inv, valores],
  )
  const recuperarContado = () => {
    setValores(p => {
      const n = { ...p }
      perdidos.forEach(it => { n[it.id] = String(it.cantidad_real) })
      return n
    })
    setDirty(true)
  }

  const dif = (it: Item) => {
    const n = aNumero(valores[it.id] ?? '')
    if (n === null) return null
    return n - it.cantidad_sistema
  }

  /** Renglones con algo escrito que NO es un número: no viajan, así que la
   *  pantalla tiene que nombrarlos antes de decir «Guardado». Una casilla en
   *  «8-10» y el resto vacías mandaba una lista vacía, el servidor contestaba
   *  200 y la pantalla decía «Guardado» sin haber guardado nada — la misma
   *  mentira que veníamos sacando, ahora por el lado del filtro. */
  const invalidos = useMemo(
    () => (inv?.items ?? []).filter(
      it => (valores[it.id] ?? '') !== '' && aNumero(valores[it.id]) === null),
    [inv, valores],
  )

  /** Guarda y CONFIRMA contra lo que volvió. Devuelve si quedó todo guardado.
   *
   *  No alcanza con el 200: el servidor ignoraba en silencio un renglón cuya
   *  cantidad no le sirve —probado contra producción, contestaba 200 y no
   *  guardaba nada— así que se compara renglón por renglón contra la respuesta.
   *  Hoy el servidor además los NOMBRA en `no_guardados`, pero la comparación se
   *  queda: es lo que atrapa un backend viejo, y no cuesta nada. Si algo no
   *  quedó, se dice y no se toca el borrador: lo contado sigue en pantalla. */
  const guardar = async (): Promise<boolean> => {
    if (!inv) return false
    setGuardando(true); setMsg(''); setFalloGuardar(null)
    try {
      const genAlEnviar = editGen.current
      const items = Object.entries(valores)
        .map(([id, v]) => ({ id: Number(id), cantidad_real: aNumero(v) }))
        .filter((x): x is { id: number; cantidad_real: number } => x.cantidad_real !== null)
      const { data } = await api.patch<Inv>(`/inventario-mensual/${inv.id}/guardar`, items)
      setInv(data)
      const porId = new Map(data.items.map(it => [it.id, it]))
      const noLlegaron = items.filter(x => {
        const it = porId.get(x.id)
        return !it || !it.fue_contado || it.cantidad_real == null
          || Math.abs(Number(it.cantidad_real) - x.cantidad_real) > 0.001
      })
      if (noLlegaron.length) {
        // El servidor ahora dice cuáles rechazó y por qué; si lo dice, se
        // muestra su motivo — «LECHE es negativo» se corrige, «2 de 65 no
        // quedaron» solo asusta.
        const detalle = (data.no_guardados ?? [])
          .slice(0, 3).map(x => `${x.producto || `#${x.id}`}: ${x.motivo}`).join(' · ')
        setFalloGuardar(`El servidor respondió, pero ${noLlegaron.length} de ${items.length} `
          + 'renglones no quedaron guardados. Lo que contaste sigue en la pantalla.'
          + (detalle ? ` (${detalle})` : ''))
        return false
      }
      if (invalidos.length) {
        // Lo bueno YA quedó guardado arriba: un renglón mal tecleado no puede
        // costar los otros 64. Pero el envío no fue completo, así que devuelve
        // false y CERRAR no pasa por encima.
        setFalloGuardar(`Se guardó lo contado, pero ${invalidos.length} renglón(es) no viajaron `
          + 'porque lo escrito no es una cantidad: '
          + `${invalidos.slice(0, 3).map(it => it.producto_nombre).join(', ')}`
          + `${invalidos.length > 3 ? '…' : ''}. Corregilos y volvé a guardar.`)
        return false
      }
      setMsg('Guardado')
      serverVals.current = valoresDesde(data.items)
      if (editGen.current === genAlEnviar) {
        // Nada se tipeó durante el request: lo guardado ya vive en el servidor
        limpiarBorrador()
        setDirty(false); setBorradorInfo(null)
      }
      setTimeout(() => setMsg(''), 1500)
      return true
    } catch {
      setFalloGuardar('No se pudo guardar: el envío no llegó al servidor. Lo que contaste sigue '
        + 'en la pantalla y no se perdió — revisá la señal y tocá «Reintentar».')
      return false
    } finally { setGuardando(false) }
  }

  const cerrar = async () => {
    if (!inv) return
    // Se dice cuántos quedan sin contar ANTES de cerrar: al cerrar, esos productos
    // se igualan al sistema y su diferencia queda en 0 para siempre.
    const faltan = inv.items.length - contados
    const aviso = faltan > 0
      ? `¿Cerrar el conteo del mes con ${faltan} de ${inv.items.length} productos SIN contar?\n\n`
        + 'A los que falten se les va a poner el valor del sistema, o sea que van a quedar '
        + 'sin diferencia — no porque hayan cuadrado, sino porque nadie los contó.\n\n'
        + 'No se podrá editar después.'
      : '¿Cerrar el conteo del mes? No se podrá editar después.'
    if (!window.confirm(aviso)) return
    setCerrando(true); setMsg('')
    try {
      // Si el guardado no quedó, NO se cierra: cerrar congela el mes y a lo no
      // contado le pone el valor del sistema. Cerrar encima de un guardado
      // fallido es perder el conteo del día sin traza.
      if (!(await guardar())) { setCerrando(false); return }
      const { data } = await api.post<Inv>(`/inventario-mensual/${inv.id}/cerrar`)
      setInv(data)
      limpiarBorrador()   // conteo cerrado: el borrador ya cumplió
      setDirty(false); setBorradorInfo(null)
    } catch { setMsg('Error al cerrar') } finally { setCerrando(false) }
  }

  return (
    <BaristaLayout title="Inventario mensual">
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <Boxes size={20} className="text-forest" />
          <div>
            <h1 className="text-lg font-bold text-gray-800">Inventario mensual</h1>
            <p className="text-xs text-gray-400">{inv ? `${MESES[inv.mes - 1]} ${inv.anio}` : ''}</p>
          </div>
        </div>

        {loading && <p className="text-sm text-gray-400 text-center py-8 animate-pulse">Preparando el conteo...</p>}

        {!loading && inv && (
          <>
            {/* Estado / progreso */}
            <div className={`rounded-xl px-4 py-3 flex items-center gap-2 text-sm ${cerrado ? 'bg-green-50 border border-green-200 text-green-700' : 'bg-amber-50 border border-amber-200 text-amber-700'}`}>
              {cerrado ? <Lock size={15} /> : <AlertTriangle size={15} />}
              {cerrado
                // La cobertura se sigue mostrando DESPUÉS de cerrar: la diferencia
                // neta de un mes contado a medias no significa lo mismo que la de
                // uno completo, y el cierre deja los dos casos con el mismo aspecto.
                ? <span>Conteo <b>cerrado</b> con <b>{inv.contados}</b> de {inv.total_items} productos
                    contados. Diferencia neta: <b>${Math.round(inv.valor_diferencia_total).toLocaleString('es-CO')}</b></span>
                : <span><b>{contados}</b> de {inv.items.length} productos contados</span>}
            </div>

            {/* Un cierre parcial no es un error, pero tiene que verse: lo no contado
                quedó igualado al sistema, o sea con diferencia 0 por construcción. */}
            {cerrado && inv.contados < inv.total_items && (
              <div className="rounded-xl px-4 py-2.5 flex items-start gap-2 text-sm bg-amber-50 border border-amber-200 text-amber-700">
                <AlertTriangle size={15} className="mt-0.5 shrink-0" />
                <span>Quedaron <b>{inv.total_items - inv.contados}</b> productos sin contar. El cierre
                  les puso el valor del sistema, así que aparecen sin diferencia — pero nadie los
                  verificó: la diferencia neta de arriba solo habla de lo que sí se contó.</span>
              </div>
            )}

            {/* Borrador restaurado */}
            {!cerrado && borradorInfo && (
              <div className="rounded-xl px-4 py-2.5 flex items-center gap-2 text-sm bg-amber-50 border border-amber-200 text-amber-700">
                <Save size={14} className="shrink-0" />
                <span className="flex-1">Se restauró lo que llevabas escrito a las {borradorInfo} — seguí donde ibas.</span>
                <button onClick={descartarBorrador} className="p-1 rounded-lg" aria-label="Descartar borrador">
                  <X size={14} />
                </button>
              </div>
            )}

            {falloGuardar && (
              <div className="rounded-xl px-4 py-3 flex items-start gap-2 text-sm bg-red-50 border-2 border-red-300 text-red-800">
                <AlertTriangle size={16} className="shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <p className="font-bold">No quedó guardado</p>
                  <p className="mt-0.5">{falloGuardar}</p>
                  <button onClick={guardar} disabled={guardando}
                    className="mt-2 bg-red-600 text-white font-bold px-4 py-2 rounded-xl text-sm disabled:opacity-40">
                    {guardando ? 'Guardando…' : 'Reintentar'}
                  </button>
                </div>
              </div>
            )}

            {!cerrado && perdidos.length > 0 && (
              <div className="rounded-xl px-4 py-3 flex items-start gap-2 text-sm bg-amber-50 border border-amber-200 text-amber-800">
                <AlertTriangle size={15} className="shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <p><b>{perdidos.length}</b> producto{perdidos.length !== 1 ? 's' : ''} que ya
                    se habían contado {perdidos.length !== 1 ? 'aparecen' : 'aparece'} en blanco.
                    Lo contado está guardado — no se perdió.</p>
                  <button onClick={recuperarContado}
                    className="mt-1.5 font-bold underline underline-offset-2">
                    Volver a ponerlo{perdidos.length !== 1 ? 's' : ''}
                  </button>
                </div>
              </div>
            )}

            {/* El recorrido del local, en el mismo orden que apertura y cierre */}
            <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
                <div className="divide-y divide-gray-50">
                  {ordenados.map((it, idx) => {
                    const d = cerrado ? it.diferencia : dif(it)
                    // Corte entre zonas del local: una línea, sin encabezado nuevo.
                    const corte = idx > 0 && abreBloque(it.orden_conteo, ordenados[idx - 1].orden_conteo)
                    return (
                      <Fragment key={it.id}>
                      {corte && <div className="h-3 bg-gray-50 border-y border-gray-100" aria-hidden="true" />}
                      <div className="flex items-center gap-3 px-4 py-2.5">
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-gray-800 truncate">{it.producto_nombre}</p>
                          <p className="text-xs text-gray-400">Sistema: {Math.round(it.cantidad_sistema)} {it.unidad_medida}</p>
                          {/* Lo guardado, cuando la casilla está vacía: desde el
                              piso «nadie lo contó» y «lo contaste y no se ve»
                              son el mismo cuadrito en blanco. */}
                          {!cerrado && it.fue_contado && it.cantidad_real != null
                            && (valores[it.id] ?? '') === '' && (
                            <button onClick={() => setValor(it.id, String(it.cantidad_real))}
                              className="text-xs font-bold text-amber-600 underline underline-offset-2">
                              contaron {Math.round((it.cantidad_real ?? 0) * 100) / 100} — poner
                            </button>
                          )}
                        </div>
                        {cerrado ? (
                          <div className="text-right">
                            {/* Lo que nadie contó NO se muestra como un físico: ese
                                número lo puso el cierre copiando el sistema, y
                                pintarlo igual que un conteo real es justo lo que
                                escondía la fuga. */}
                            {it.fue_contado ? (
                              <p className="text-sm font-bold text-gray-800 font-mono">{Math.round((it.cantidad_real ?? 0) * 100) / 100}</p>
                            ) : (
                              <p className="text-xs font-bold text-amber-600">sin contar</p>
                            )}
                          </div>
                        ) : it.fraccionable ? (
                          <NivelEnvase
                            envase={it.envase === 'botella' ? 'botella' : 'bolsa'}
                            unidad={it.unidad_medida}
                            selladas={Math.floor(Number(valores[it.id] ?? 0))}
                            nivel={Number(valores[it.id] ?? 0) - Math.floor(Number(valores[it.id] ?? 0))}
                            onChange={(s, n) => setValor(it.id, String(s + n))}
                          />
                        ) : (
                          <div className="flex flex-col items-end gap-0.5">
                            <input type="text" inputMode="decimal" value={valores[it.id] ?? ''}
                              onChange={e => setValor(it.id, e.target.value.replace(/[^\d.,+\-\s]/g, ''))}
                              placeholder="—"
                              className={`w-28 border-2 rounded-xl px-2 py-1.5 text-center font-mono font-bold text-[15px] focus:outline-none focus:border-forest ${
                                (valores[it.id] ?? '') !== '' && !aMedias(valores[it.id])
                                  && aNumero(valores[it.id]) === null
                                  ? 'border-red-400 bg-red-50' : 'border-gray-200'}`} />
                            {/* Cuando escribió una suma se muestra el total: si la
                                pantalla va a guardar 20, tiene que decir 20. */}
                            {/[+-]/.test((valores[it.id] ?? '').slice(1)) && aNumero(valores[it.id]) !== null && (
                              <span className="text-[11px] font-bold text-forest font-mono">
                                = {aNumero(valores[it.id])}
                              </span>
                            )}
                            {!aMedias(valores[it.id]) && motivoInvalido(valores[it.id]) && (
                              <span className="text-[11px] font-bold text-red-600 font-mono">
                                {motivoInvalido(valores[it.id])}
                              </span>
                            )}
                          </div>
                        )}
                        <div className="w-14 text-right">
                          {d != null && d !== 0 && (
                            <span className={`text-xs font-bold font-mono ${d > 0 ? 'text-blue-600' : 'text-red-600'}`}>
                              {d > 0 ? '+' : ''}{Math.round(d)}
                            </span>
                          )}
                          {d === 0 && <Check size={14} className="text-green-500 inline" />}
                        </div>
                      </div>
                      </Fragment>
                    )
                  })}
                </div>
            </div>

            {msg && <p className="text-sm text-center text-gray-500">{msg}</p>}

            {/* CTA */}
            {!cerrado && (
              <div className="flex gap-2 sticky bottom-2">
                <button onClick={guardar} disabled={guardando}
                  className="flex-1 flex items-center justify-center gap-2 bg-white border-2 border-gray-200 text-gray-600 font-bold py-3 rounded-xl text-sm disabled:opacity-40">
                  <Save size={16} /> {guardando ? 'Guardando...' : 'Guardar avance'}
                </button>
                <button onClick={cerrar} disabled={cerrando}
                  className="flex-1 flex items-center justify-center gap-2 bg-forest hover:bg-forest-700 text-white font-bold py-3 rounded-xl text-sm disabled:opacity-40">
                  <Check size={16} /> {cerrando ? 'Cerrando...' : 'Cerrar conteo'}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </BaristaLayout>
  )
}
