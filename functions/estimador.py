"""
Estimación automática de una mudanza para la calculadora de la web.

Aplica las reglas de Alberto (las mismas que usa la tarea de propuestas):
volumen → vehículo → equipo → horas (carga, descarga, desmontaje, plantas,
distancia del camión, embalaje, conducción) → `calcular()` con las tarifas
reales de la app. Al cliente solo se le enseña un RANGO orientativo; el
desglose (sueldos, alquileres, margen) nunca sale de aquí.

Todo es puro (sin Firebase ni red) para poder probarlo.
"""
import math

from mcp_escritura import calcular

# m³ aproximados por objeto (lo que identifica la IA en las fotos o marca el cliente)
VOLUMEN = {
    "sofa": 2.5, "sofa_pequeno": 1.5, "sillon": 0.8, "cama": 1.5, "cama_individual": 1.0, "canape": 1.2,
    "colchon": 0.5, "armario2": 1.0, "armario4": 2.0, "armario6": 3.0, "comoda": 0.6, "mesita": 0.2,
    "mesa": 0.8, "mesa_pequena": 0.3, "silla": 0.2, "estanteria": 0.7, "mueble_tv": 0.7, "aparador": 1.0,
    "escritorio": 0.7, "frigorifico": 1.0, "lavadora": 0.5, "secadora": 0.5, "lavavajillas": 0.5,
    "horno_microondas": 0.15, "televisor": 0.3, "bicicleta": 0.5, "caja": 0.1, "maleta": 0.15,
    "planta": 0.3, "electrodomestico": 0.3, "otro": 0.4,
}
# Minutos de DESMONTAJE por mueble para una pareja (reglas de Alberto; la cama es un supuesto)
DESMONTAJE_MIN = {"canape": 15, "armario2": 20, "armario4": 35, "armario6": 45, "cama": 15, "cama_individual": 10}
FACTOR_MONTAJE = 1.5            # el montaje lleva más que el desmontaje (supuesto)

# Volumen típico por tamaño de vivienda (mín, máx) y cajas si embalamos nosotros
CASA_M3 = {"estudio": (8, 12), "1": (12, 18), "2": (20, 28), "3": (28, 38), "4": (38, 48), "chalet": (42, 60)}
CASA_CAJAS = {"estudio": 20, "1": 35, "2": 50, "3": 60, "4": 75, "chalet": 90}
MATERIAL_PISO = 40.0            # € de cajas + film para un piso de 2-3 dormitorios (~55 cajas)
CAJAS_PISO = 55

PLANTAS = {"bajo": 0, "1": 1, "2": 2, "3": 3, "4": 4}
CRAFTER_M3 = 11
IVECO_M3 = 20
KM_RECOGIDA = 8                 # de donde se alquila el vehículo a Huelva (y vuelta)
VEL_MEDIA = 60                  # km/h para el tiempo de conducción
KM_MAX_PRECIO = 700             # a partir de aquí, el precio lo confirma Alberto en persona
RANGO = (0.92, 1.15)            # rango que se enseña al cliente sobre el precio calculado


def _r5(x):
    return int(5 * round(x / 5))


def volumen(items, casa=None, tipo="casa"):
    """m³ a partir de los objetos; en una casa completa, al menos lo típico de su tamaño."""
    suma = 0.0
    for it in items or []:
        cat = it.get("categoria") if it.get("categoria") in VOLUMEN else "otro"
        suma += VOLUMEN[cat] * max(0, min(60, int(it.get("cantidad") or 0)))
    if tipo == "casa":
        suma *= 1.15            # lo pequeño que no se ve en las fotos (lámparas, cuadros, bolsas…)
        if casa in CASA_M3:
            lo, hi = CASA_M3[casa]
            suma = min(max(suma, lo), hi * 1.2) if suma else (lo + hi) / 2
    return round(max(suma, 0.5), 1)


def vehiculos(tipo, m3, km_carga_descarga):
    """Lista de (tipo, viajes). Reglas de Alberto."""
    if tipo == "casa":
        if m3 <= IVECO_M3:
            return [("iveco", 1)]
        if m3 <= IVECO_M3 + CRAFTER_M3 - 1:
            return [("iveco", 1), ("crafter", 1)]
        return [("iveco", 1), ("iveco", 1)]
    # Portes
    if km_carga_descarga < 15:
        viajes = math.ceil(m3 / CRAFTER_M3)
        if viajes <= 3:
            return [("crafter", max(1, viajes))]
    if m3 <= CRAFTER_M3:
        return [("crafter", 1)]
    if m3 <= IVECO_M3:
        return [("iveco", 1)]
    return [("iveco", 1), ("crafter", 1)]


def trabajadores(tipo, m3):
    if tipo == "casa":
        return 3 if m3 > 35 else 2
    if m3 < 6:
        return 0
    return 1 if m3 <= 12 else 2


def _min_camion(metros):
    if metros is None:
        return 10
    if metros < 30:
        return 10
    return 35 if metros <= 100 else 50


def _min_plantas(lado):
    if lado.get("ascensor") is True:
        return 0
    return 10 * PLANTAS.get(str(lado.get("piso") or "bajo"), 0)


def estimar(d, legs_km, tarifas):
    """
    d: tipo ('casa'|'porte'), casa, items[{categoria,cantidad}], origen/destino
       {piso, ascensor, camion_m}, desmontaje ('si'|'desmontar'|'no'|'nose'),
       embalaje ('todo'|'fragil'|'yo'), especiales[].
    legs_km: (Huelva→carga, carga→descarga, descarga→Huelva).
    Devuelve el resultado completo (para la app) y lo que se enseña al cliente.
    """
    tipo = "porte" if d.get("tipo") == "porte" else "casa"
    items = d.get("items") or []
    casa = d.get("casa") if d.get("casa") in CASA_M3 else None
    m3 = volumen(items, casa, tipo)
    h_carga_km, cd_km, dh_km = (max(0.0, float(x or 0)) for x in legs_km)

    vehs = vehiculos(tipo, m3, cd_km)
    socios = 2
    trab = trabajadores(tipo, m3)
    personas = socios + trab
    km_base = KM_RECOGIDA + h_carga_km + cd_km + dh_km + KM_RECOGIDA

    supuestos, mins = [], {}
    # Carga y descarga (≈1 h 45 min por cada 20 m³ con 4 personas)
    carga = 105 * (m3 / 20) * (4 / personas)
    mins["carga"] = carga
    mins["descarga"] = 0.7 * carga
    viajes_extra = sum(v - 1 for _, v in vehs)
    # Desmontaje / montaje
    desm = 0
    for it in items:
        if it.get("categoria") in DESMONTAJE_MIN:
            desm += DESMONTAJE_MIN[it["categoria"]] * max(0, int(it.get("cantidad") or 0))
    desm /= max(1, personas / 2)    # se trabaja por parejas: con 4 personas, dos muebles a la vez
    modo = d.get("desmontaje") or "nose"
    if modo == "si" or (modo == "nose" and desm):
        mins["desmontaje y montaje"] = desm * (1 + FACTOR_MONTAJE)
    elif modo == "desmontar":
        mins["desmontaje"] = desm
    # Plantas sin ascensor y distancia del camión
    o, de = d.get("origen") or {}, d.get("destino") or {}
    mins["escaleras"] = _min_plantas(o) + _min_plantas(de)
    mins["camión hasta el portal"] = _min_camion(o.get("camion_m")) + _min_camion(de.get("camion_m"))
    # Embalaje
    material = 0.0
    if d.get("embalaje") in ("todo", "fragil"):
        cajas = CASA_CAJAS.get(casa or "2", CAJAS_PISO) if tipo == "casa" else max(5, int(m3 * 3))
        if d["embalaje"] == "fragil":
            cajas = math.ceil(cajas / 3)
        mins["embalaje"] = 60 * (cajas / 15) * (4 / personas)
        material = MATERIAL_PISO * cajas / CAJAS_PISO
        supuestos.append(f"Embalaje: unas {cajas} cajas")
    # Conducción
    km_viaje = km_base + viajes_extra * 2 * cd_km
    mins["conducción"] = 60 * km_viaje / VEL_MEDIA

    total_h = sum(mins.values()) / 60
    horas = max(2.0, math.ceil(total_h * 2) / 2)
    dias = 1 if horas <= 11 else 2

    vehicles = []
    for i, (t, v) in enumerate(vehs):
        km = km_base + (v - 1) * 2 * cd_km if i == 0 else km_base
        plan = 200 if km <= 200 * dias else 400
        vehicles.append({"type": t, "plan": plan, "days": dias, "km": round(km, 1)})

    est = {"vehicles": vehicles, "hours": horas, "workers": trab, "partners": socios,
           "matQty": {}, "fuel": None, "extras": round(material, 2), "m3": m3}
    res = calcular(est, tarifas)

    especiales = [e for e in (d.get("especiales") or []) if e]
    sin_precio = km_viaje > KM_MAX_PRECIO
    nombres = {"iveco": "camión de 20 m³", "crafter": "furgoneta grande"}
    veh_txt = " + ".join(nombres[t] + (f" ({v} viajes)" if v > 1 else "") for t, v in vehs)
    cliente = {
        "m3": m3, "vehiculo": veh_txt, "personas": personas, "horas": horas, "dias": dias,
        "km": round(km_viaje), "sin_precio": sin_precio, "especiales": especiales,
    }
    if not sin_precio:
        cliente["min"] = _r5(res["price"] * RANGO[0])
        cliente["max"] = _r5(res["price"] * RANGO[1])

    supuestos = [
        f"{m3} m³ ({'objetos de las fotos/lista' if items else 'tamaño de la vivienda'})",
        f"{veh_txt} · {round(km_viaje)} km en total",
        f"{personas} personas · {horas} h ("
        + ", ".join(f"{k} {round(v)} min" for k, v in mins.items() if v >= 1) + ")",
    ] + supuestos
    if especiales:
        supuestos.append("Objetos especiales aparte: " + ", ".join(especiales))
    return {"estimacion": est, "resultado": res, "cliente": cliente, "supuestos": supuestos,
            "minutos": {k: round(v) for k, v in mins.items()}}
