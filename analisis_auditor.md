# ESCENARIO DEL AUDITOR

Flujo diferido (base_real=None en abrir_caja):

1. Barista abre caja:
   - POST /caja/abrir { base_real: null, barista_ids: [...], tipo_turno, caja_fuerte }
   - abrir_caja() crea turno con:
     - base_real = 0.0 (línea 159)
     - tiene_cuadre_llegada = False (línea 168, porque cuadre_unificado=False)
     - tiene_conteo_apertura = False (línea 165)
     - tiene_ventas = False (línea 169)
   
2. Barista hace conteo de apertura (desde PC):
   - GET /conteos/... marks tiene_conteo_apertura = True
   - turno.es_operativo debería ser False todavía:
     - tiene_ventas? No
     - tiene_cuadre_llegada? No → retorna False (línea 74)
   
3. Barista OLVIDA registrar cuadre_inicial
   - No llama POST /caja/{turno_id}/cuadre-inicial
   
4. Barista intenta vender:
   - POST /pos/tickets { items: [...] }
   - crear_ticket() valida es_operativo (línea 91)
   - _es_operativo() chequea:
     a) if tiene_ventas: return True
     b) if not tiene_cuadre_llegada: return False
     c) if tiene_conteo_apertura: return True ← PASA AQUÍ (línea 75)
   - POS ABRE sin cuadre_inicial registrado

5. Primera venta registrada:
   - crear_ticket() marca turno_db.tiene_ventas = True (línea 237)
   - Entrega efectivo sin base_real definido (sigue siendo 0.0 de apertura)

PROBLEMA REAL:
- Es posible vender sin base_real real registrado
- base_real sigue siendo 0.0 (de abrir_caja)
- El cuadre está roto: efectivo_esperado = 0 + total_ventas + ingresos - egresos
  (sin el efectivo de inicio real)

EVIDENCIA DEL AUDITOR:
- Línea 71: "if turno.tiene_ventas: return True" — BYPASS (pero no se activa aquí)
- Línea 75: "if turno.tiene_conteo_apertura: return True" — PUERTA ABIERTA
- Línea 237: "turno_db.tiene_ventas = True" — se escribe DESPUÉS del check

EL AUDITOR DICE:
"Si se cambia tuviera logica de has_previous_sales, círculo se rompe"

Esto significa: el bypass de línea 71 (tiene_ventas = True) es una medida de emergencia
para NO bloquear turnos que ya registraron ventas (legacy, al deployar este cambio).
No está diseñado para ser un BYPASS preventivo — es un salvavidas post-facto.

FIX PROPUESTO DEL AUDITOR:
"Cambiar _es_operativo: require tiene_cuadre_llegada sin exception.
El bypass tiene_ventas SOLO si hay ventas en el TURNO ANTERIOR."

ANÁLISIS:
1. El problema NO es el bypass de tiene_ventas (línea 71)
2. El problema ES que _es_operativo retorna True en línea 75 si:
   - turno.tipo_turno != "apertura" (es intermedio/cierre), O
   - turno.tiene_conteo_apertura=True sin respetar tiene_cuadre_llegada
3. La línea 75 SÍ está mal: permite vender sin cuadre_inicial si el conteo ya se hizo

GATE CORRECTO DEBE SER:
def _es_operativo(db: Session, turno) -> bool:
    if turno.tiene_ventas:
        return True  # Salvavidas legacy
    if not turno.tiene_cuadre_llegada:
        return False
    # AQUÍ: ya pasó cuadre de llegada
    if turno.tiene_conteo_apertura:
        return True  # Apertura + conteo + cuadre ✓
    if turno.tipo_turno in ("intermedio", "cierre"):
        return _hay_conteo_apertura_en_dia(db, turno)  # Hereda conteo del día ✓
    return False  # Apertura sin conteo aún

RIESGO OPERATIVO REAL (mañana Vida abre):
- Barista abre caja diferido (flujo nuevo)
- Hace conteo apertura
- Se olvida del cuadre inicial
- Intenta vender → ESPERADO: POS bloqueado
- REAL: POS ABRE porque tiene_conteo_apertura=True bypasea tiene_cuadre_llegada
- Base de caja queda en 0.0 en lugar del efectivo real
- Al cierre, diferencia de efectivo entera queda atribuida a "ventas" indetectable
