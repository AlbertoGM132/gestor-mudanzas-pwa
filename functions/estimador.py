"""
Presupuesto ORIENTATIVO para la calculadora de la web, con las reglas de Alberto.

Lo mismo que hace la tarea de propuestas de Claude, pero en código y al instante:
m³ → vehículo → km → horas → material → `calcular()` con las tarifas de la app →
horquilla (‑8 % / +12 %, redondeada a 10 €). Es solo una orientación para el
cliente; el precio cerrado lo da siempre Alberto.

Sin Firebase: se puede probar con `python -m pytest` o a mano.
"""
import math

from mcp_escritura import calcular

# m³ medios por tamaño de casa (si la IA o el cliente no dan otro dato)
M3_CASA = {"estudio": 10, "1": 15, "2": 22, "3": 32, "4": 42, "chalet": 45}
# m³ por mueble (portes o casas sin tamaño)
M3_MUEBLE = {"camas": 1.5, "canapes": 1.5, "armario2": 1.0, "armario4": 2.0, "armario6": 3.0, "sofas": 2.5,
             "frigorifico": 1.0, "lavadora": 0.5, "mesas": 0.8, "comodas": 0.8}
# Desmontaje (minutos, reglas de Alberto; «camas» normales es supuesto)
DESMONTAJE_MIN = {"canapes": 15, "armario2": 20, "armario4": 35, "armario6": 45, "camas": 10}
MONTAJE_FACTOR = 1.5                    # el montaje lleva más que el desmontaje (supuesto)
APARCAMIENTO_MIN = {"puerta": 0, "30": 10, "100": 35, "mas": 50}
PISO_N = {"bajo": 0, "1": 1, "2": 2, "3": 3, "4": 4}
KM_ALQUILER = 8                         # de donde se alquilan los vehículos a Huelva (cada sentido)
CRAFTER_M3 = 11


def _n(v, lo=0.0, hi=1e6):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return max(lo, min(hi, x))


def volumen(inv, m3=None, fuente=None):
    """m³ a usar: el que dé la IA/cliente; si no, por tamaño de casa; si no, por muebles."""
    m3 = _n(m3, 0, 150)
    if m3:
        return round(m3, 1), fuente or "estimado por las fotos"
    casa = (inv or {}).get("casa")
    if casa in M3_CASA:
        return float(M3_CASA[casa]), "por el tamaño de la casa"
    muebles = (inv or {}).get("muebles") or {}
    suma = sum(M3_MUEBLE.get(k, 0.8) * _n(n, 0, 30) for k, n in muebles.items())
    if suma:
        return round(max(2.0, suma * 1.3), 1), "por los muebles que indicó"   # +30 % de cajas y bultos
    return 8.0, "sin datos (supuesto prudente)"


def estimar(datos, tarifas):
    """
    datos = {
      servicios: ["mudanza","porte","montaje","embalaje","fragil",...],
      inventario: {casa, muebles:{clave:n}, desmontaje, embalaje, cajas},
      m3: float | None,
      origen/destino: {piso, ascensor, aparcamiento},
      km: {base_origen, origen_destino, destino_base}
    }
    """
    serv = set(datos.get("servicios") or [])
    inv = datos.get("inventario") or {}
    m3, fuente_m3 = volumen(inv, datos.get("m3"), datos.get("m3_fuente"))
    completa = "mudanza" in serv or inv.get("casa") in M3_CASA

    km = datos.get("km") or {}
    d_bo = _n(km.get("base_origen"), 0, 1500)
    d_od = _n(km.get("origen_destino"), 0, 1500)
    d_db = _n(km.get("destino_base"), 0, 1500)

    # Vehículos (reglas de Alberto)
    viajes = 1
    if completa:
        # El camión de 20 m³ bien cargado admite hasta ~24 m³ (en el ejemplo de Alberto, 22 m³ = solo camión)
        tipos = ["iveco"] if m3 <= 24 else (["iveco", "crafter"] if m3 <= 33 else ["iveco", "iveco"])
    elif d_od < 15 and m3 <= 3 * CRAFTER_M3:       # porte cerca: furgoneta y varios viajes
        tipos, viajes = ["crafter"], max(1, math.ceil(m3 / CRAFTER_M3))
    else:
        tipos = ["crafter"] if m3 <= CRAFTER_M3 else ["iveco"]
    km_veh = 2 * KM_ALQUILER + d_bo + d_od + d_db + (viajes - 1) * 2 * d_od
    vehiculos = [{"type": t, "plan": 400 if km_veh > 200 else 200, "days": 1, "km": round(km_veh)} for t in tipos]

    # Equipo: siempre los dos socios
    socios = 2
    trabajadores = 0 if m3 <= 6 else 1 if m3 <= 12 else 2 if m3 <= 35 else 3
    personas = socios + trabajadores
    escala = 4 / personas

    # Horas
    carga = 1.75 * (m3 / 20) * escala
    descarga = 0.7 * carga
    muebles = inv.get("muebles") or {}
    desm = 0.0
    if inv.get("desmontaje") in ("si", "desmontar") or "montaje" in serv:
        desm_min = sum(DESMONTAJE_MIN.get(k, 0) * _n(n, 0, 30) for k, n in muebles.items())
        desm = desm_min / 60
        if inv.get("desmontaje") != "desmontar":
            desm += desm * MONTAJE_FACTOR
    extra_min = 0.0
    for lado in (datos.get("origen") or {}, datos.get("destino") or {}):
        if lado.get("ascensor") != "si":
            extra_min += 10 * PISO_N.get(str(lado.get("piso") or ""), 0)
        extra_min += APARCAMIENTO_MIN.get(lado.get("aparcamiento"), 0)
    embalaje = inv.get("embalaje")
    cajas = 0
    if embalaje == "todo" or ("embalaje" in serv and not embalaje):
        cajas = round(m3 * 2.3)                   # ~55 cajas para 2 dormitorios
    elif embalaje == "fragil" or "fragil" in serv:
        cajas = 10
    emb_h = cajas / 15 * escala
    conduccion = km_veh / 60                      # incluye los viajes extra
    horas = carga + descarga + desm + extra_min / 60 + emb_h + conduccion
    horas = max(2.0, math.ceil(horas * 2) / 2)

    material = {}
    if cajas >= 20:
        material = {"Cajas grandes": cajas, "Plástico film": max(1, round(m3 / 25)), "Cinta adhesiva": math.ceil(cajas / 20)}
    elif cajas:
        material = {"Cajas pequeñas": cajas, "Papel de embalaje": 1, "Cinta adhesiva": 1}

    est = {"vehicles": vehiculos, "hours": horas, "workers": trabajadores, "partners": socios,
           "matQty": material, "fuel": None, "extras": 0, "m3": m3}
    res = calcular(est, tarifas)
    precio = res["price"]
    minimo = int(math.floor(precio * 0.92 / 10) * 10)
    maximo = int(math.ceil(precio * 1.12 / 10) * 10)

    nombres = {"iveco": "camión de 20 m³", "crafter": "furgoneta"}
    vtxt = " + ".join(nombres[t] for t in tipos) + (f" ({viajes} viajes)" if viajes > 1 else "")
    return {
        "min": minimo, "max": maximo, "precio": precio,
        "resumen": {"m3": m3, "fuente_m3": fuente_m3, "vehiculos": vtxt, "km": round(km_veh),
                    "horas": horas, "personas": personas, "cajas": cajas},
        "estimacion": est, "resultado": res,
    }
