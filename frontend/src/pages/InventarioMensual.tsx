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
}

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
              merged = { ...v, ...d.valores }
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

  const contados = useMemo(() => Object.values(valores).filter(v => v !== '').length, [valores])

  const dif = (it: Item) => {
    const v = valores[it.id]
    if (v === undefined || v === '') return null
    return Number(v) - it.cantidad_sistema
  }

  const guardar = async () => {
    if (!inv) return
    setGuardando(true); setMsg('')
    try {
      const genAlEnviar = editGen.current
      const items = Object.entries(valores)
        .filter(([, v]) => v !== '')
        .map(([id, v]) => ({ id: Number(id), cantidad_real: Number(v) }))
      const { data } = await api.patch<Inv>(`/inventario-mensual/${inv.id}/guardar`, items)
      setInv(data); setMsg('Guardado')
      serverVals.current = valoresDesde(data.items)
      if (editGen.current === genAlEnviar) {
        // Nada se tipeó durante el request: lo guardado ya vive en el servidor
        limpiarBorrador()
        setDirty(false); setBorradorInfo(null)
      }
      setTimeout(() => setMsg(''), 1500)
    } catch { setMsg('Error al guardar') } finally { setGuardando(false) }
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
      await guardar()
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
                          <input type="number" inputMode="numeric" value={valores[it.id] ?? ''}
                            onChange={e => setValor(it.id, e.target.value)}
                            placeholder="—"
                            className="w-20 border-2 border-gray-200 rounded-xl px-2 py-1.5 text-center font-mono font-bold focus:outline-none focus:border-forest" />
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
