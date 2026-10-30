"""
Motor de presupuestos de MudanzaPro (determinista).

Mismos datos → mismo precio. Aplica las reglas afinadas con Alberto en el documento
«Motor de presupuestos de MudanzaPro» (octubre 2026): volumen → vehículos → equipo →
horas → días → coste con las tarifas de la app (`calcular`). No ve fotos ni entiende
notas libres: cuando falta un dato o algo se sale de lo normal lo dice en la etiqueta
(«lista», «revisar», «a mano») en vez de inventar.

Todo lo de este archivo es puro (sin Firebase ni red) salvo `Rutas`, que se inyecta.
Los parámetros se pueden cambiar sin desplegar con el campo `motor` del documento de
tarifas (mismas claves que CONFIG).
"""
import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from mcp_escritura import DEFAULT_TARIFAS, calcular

VERSION = "motor-1"

CONFIG = {
    # m³ por objeto (lo que ocupa cargado)
    "vol": {"cama": 1.5, "cama_individual": 1.0, "canape": 1.2, "somier": 0.3, "colchon": 0.5,
            "armario2": 1.0, "armario4": 2.0, "armario6": 3.0, "comoda": 0.5, "sofa": 1.5, "sillon": 0.6,
            "mesa": 0.8, "mesa_pequena": 0.3, "silla": 0.2, "aparador": 0.8, "televisor": 0.3,
            "frigorifico": 1.0, "lavadora": 0.5, "electro": 0.3, "jardin": 0.5, "escritorio": 0.7,
            "bici": 0.5, "caja": 0.1, "otro": 0.4},
    # minutos de desmontaje por pareja; el montaje lleva 1,5 veces más
    "desmontaje_min": {"canape": 15, "armario2": 20, "armario4": 35, "armario6": 45, "cama": 15},
    "factor_montaje": 1.5,
    "casa_m3": {"estudio": [8, 12], "1": [12, 18], "2": [20, 28], "3": [28, 38], "4": [38, 48], "chalet": [42, 60]},
    "casa_cajas": {"estudio": 20, "1": 35, "2": 50, "3": 60, "4": 75, "chalet": 90},
    "margen_pequenos": 0.15,              # casa completa sin cajas contadas: cosas pequeñas que no se ven
    "cajas_por_respuesta": {"10": 8, "30": 20, "60": 45, "mas": 70},
    "parte_fragil": 0.3,                  # parte de las cajas que es cristalería o frágil
    "min_caja_fragil": 7.5, "min_caja_normal": 3.0,   # minutos de UNA persona por caja
    "material_por_caja": 40 / 55,         # € de cajas y film por caja
    "capacidad": {"crafter": 12, "iveco": 20},
    "margen_furgoneta": 0.75,             # por encima de esto, camión (con la furgoneta como «va justa»)
    "km_cerca": 15,                       # entre carga y descarga: un vehículo con varios viajes
    "max_viajes_furgoneta": 3,
    "carga_min_20m3_4p": 105, "descarga_factor": 0.7,
    "min_planta": 10, "min_camion": {"puerta": 10, "30": 10, "100": 35, "mas": 50},
    "escala_m3": 10,                      # escaleras y distancia del camión crecen con el volumen (m³/10)
    "factor_conduccion": 1.05, "km_recogida": 8, "min_recogida": 8,
    "jornada": 12, "jornada_fuera": 14, "conduccion_max_dia": 9, "jornada_casa_grande": 9,
    "jornada_trabajo_mas_uno": 10, "max_personas": 6,
    "ratio_viaje_largo": 1.2,             # conducción ≥ 1,2 × trabajo: el equipo lo marca el trabajo
    "hotel_habitacion": 80, "personas_habitacion": 3, "comida_persona": 35,
    "km_max": 700, "horas_minimas": 2,
}

# Contadores del formulario → objeto del motor
DESDE_FORM = {"camas": "cama", "canapes": "canape", "somieres": "somier", "colchones": "colchon",
              "armario2": "armario2", "armario4": "armario4", "armario6": "armario6", "comodas": "comoda",
              "sofas": "sofa", "sillones": "sillon", "mesas": "mesa", "mesascentro": "mesa_pequena",
              "sillas": "silla", "muebletv": "aparador", "tv": "televisor", "frigorifico": "frigorifico",
              "lavadora": "lavadora", "electro": "electro", "jardin": "jardin", "escritorios": "escritorio",
              "bicis": "bici"}
ESPECIALES_A_MANO = {"piano", "caja-fuerte", "pesado"}
NOMBRE_VEH = {"crafter": "furgoneta grande", "iveco": "camión de 20 m³"}
PROVINCIA_HUELVA = (36.9, 38.3, -7.6, -6.0)   # lat min/max, lng min/max (aprox.) para «dentro de la provincia»


def cfg(tarifas=None):
    c = json.loads(json.dumps(CONFIG))
    extra = (tarifas or {}).get("motor") if isinstance(tarifas, dict) else None
    for k, v in (extra or {}).items():
        if k in c and isinstance(c[k], dict) and isinstance(v, dict):
            c[k].update(v)
        elif k in c:
            c[k] = v
    return c


# ── 1. Entrada: la solicitud de la app → datos del motor ────────────────

def _inv(mapa):
    """Etiqueta (singular o plural) → clave, a partir de un mapa clave → (sing, plural) o clave → texto."""
    out = {}
    for k, v in mapa.items():
        for t in (v if isinstance(v, (tuple, list)) else [v]):
            out[str(t).lower()] = k
    return out


def _piso(etiqueta):
    t = str(etiqueta or "").strip().lower()
    if not t:
        return None
    if t.startswith("bajo") or "casa" in t:
        return 0
    for ch in t:
        if ch.isdigit():
            return min(4, int(ch))
    return None


def entrada_desde_solicitud(job):
    """Lee una solicitud (trabajo sin fecha) y devuelve (entrada, avisos).
    Usa `formKeys` (claves del formulario) si existe; si no, traduce las etiquetas guardadas."""
    import formulario_web as fw
    job = job or {}
    keys = job.get("formKeys") if isinstance(job.get("formKeys"), dict) else {}
    inv = job.get("inventory") if isinstance(job.get("inventory"), dict) else {}
    avisos = []

    casa = keys.get("casa") or _inv(fw.CASAS).get(str(inv.get("casa") or "").lower())
    muebles_raw = keys.get("muebles")
    if not isinstance(muebles_raw, dict):
        lab = _inv(fw.MUEBLES)
        muebles_raw = {}
        for etiqueta, n in (inv.get("muebles") or {}).items():
            k = lab.get(str(etiqueta).lower())
            if k:
                muebles_raw[k] = muebles_raw.get(k, 0) + int(n or 0)
    items = {}
    for k, n in muebles_raw.items():
        obj = DESDE_FORM.get(k)
        try:
            n = int(n)
        except (TypeError, ValueError):
            continue
        if obj and n > 0:
            items[obj] = items.get(obj, 0) + n
    # Camas: si el detalle dice 90/individual, cuentan como individuales
    det = " ".join(str(v) for v in (inv.get("detalles") or {}).values()).lower()
    if items.get("cama") and ("individual" in det or " 90" in f" {det}"):
        items["cama_individual"] = items.pop("cama")

    def clave(campo, tabla):
        if keys.get(campo) in tabla:
            return keys[campo]
        return _inv(tabla).get(str(inv.get(campo) or "").lower())

    desmontaje = clave("desmontaje", fw.DESMONTAJE)
    embalaje = clave("embalaje", fw.EMBALAJE)
    cajas_resp = clave("cajas", fw.CAJAS)
    especiales = keys.get("especiales") if isinstance(keys.get("especiales"), list) else \
        [k for k, t in fw.ESPECIALES.items() if t in (inv.get("especiales") or [])]
    servicios = job.get("services") or []
    tipo = "casa" if (casa or "Mudanza completa" in servicios) else "porte"

    def lado(pref):
        acc = job.get(f"{pref}Access") if isinstance(job.get(f"{pref}Access"), dict) else {}
        piso = keys.get(f"{pref}_piso")
        piso = int(piso) if str(piso).isdigit() else (0 if piso == "bajo" else _piso(job.get(f"{pref}Floor")))
        asc = job.get(f"{pref}Elevator")
        coords = job.get(f"{pref}Coords") if isinstance(job.get(f"{pref}Coords"), dict) else None
        return {"direccion": job.get(f"{pref}Address") or "", "piso": piso,
                "ascensor": asc if isinstance(asc, bool) else None,
                "aparcamiento": acc.get("parking") if acc.get("parking") in ("puerta", "30", "100", "mas") else None,
                "coords": [coords["lat"], coords["lng"]] if coords and "lat" in coords else None}

    entrada = {
        "tipo": tipo, "casa": casa, "items": items, "otros": str(inv.get("otros") or "").strip(),
        "cajas_respuesta": cajas_resp, "desmontaje": desmontaje or "nose", "embalaje": embalaje,
        "especiales": especiales, "origen": lado("origin"), "destino": lado("destin"),
        "fotos": len(job.get("photos") or []), "comentario": bool(keys.get("comentario")),
        "fecha": job.get("desiredDate") or "",
    }
    return entrada, avisos


# ── 2. Rutas ──────────────────────────────────────────────────────────

HUELVA = (37.2614, -6.9447)


class Rutas:
    """Geocodifica y calcula tramos por carretera. Con clave de Google usa Google; si no, OSM.
    Devuelve km y minutos; los resultados se guardan en la solicitud para que un recálculo dé lo mismo."""

    def __init__(self, google_key="", timeout=10):
        self.key, self.timeout = google_key, timeout

    def _get(self, url, data=None, headers=None):
        h = {"User-Agent": "MudanzasDelSur/1.0 (mudanzasdelsur.es)", **(headers or {})}
        req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None, headers=h)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode())

    def geocodificar(self, texto):
        texto = (texto or "").strip()
        if not texto:
            return None
        if self.key:
            u = "https://maps.googleapis.com/maps/api/geocode/json?" + urllib.parse.urlencode(
                {"address": texto + ", España", "region": "es", "key": self.key})
            r = self._get(u).get("results") or []
            return [r[0]["geometry"]["location"]["lat"], r[0]["geometry"]["location"]["lng"]] if r else None
        u = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
            {"q": texto, "format": "json", "limit": 1, "countrycodes": "es"})
        r = self._get(u)
        return [float(r[0]["lat"]), float(r[0]["lon"])] if r else None

    def tramos(self, puntos):
        """[(km, min)] entre puntos consecutivos [(lat, lng), …]."""
        if self.key:
            out = []
            for a, b in zip(puntos, puntos[1:]):
                body = {"origin": {"location": {"latLng": {"latitude": a[0], "longitude": a[1]}}},
                        "destination": {"location": {"latLng": {"latitude": b[0], "longitude": b[1]}}},
                        "travelMode": "DRIVE", "routingPreference": "TRAFFIC_UNAWARE"}
                r = self._get("https://routes.googleapis.com/directions/v2:computeRoutes", body,
                              {"Content-Type": "application/json", "X-Goog-Api-Key": self.key,
                               "X-Goog-FieldMask": "routes.distanceMeters,routes.duration"})["routes"][0]
                out.append((r["distanceMeters"] / 1000, int(str(r["duration"]).rstrip("s")) / 60))
            return out
        coords = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in puntos)
        r = self._get(f"https://router.project-osrm.org/route/v1/driving/{coords}?overview=false")
        return [(l["distance"] / 1000, l["duration"] / 60) for l in r["routes"][0]["legs"]]


def preparar_rutas(entrada, rutas, guardadas=None):
    """(legs, coords, avisos). legs = [(km, min)] Huelva→carga, carga→descarga, descarga→Huelva."""
    avisos = []
    if guardadas and len(guardadas.get("legs") or []) == 3:
        # Firestore no admite listas dentro de listas: los tramos se guardan como {km, min}
        legs = [(x["km"], x["min"]) if isinstance(x, dict) else tuple(x) for x in guardadas["legs"]]
        return legs, guardadas.get("coords") or {}, avisos
    coords = {}
    for lado in ("origen", "destino"):
        d = entrada[lado]
        c = d.get("coords")
        nombre = "carga" if lado == "origen" else "descarga"
        if not c and rutas:
            # Primero la dirección entera; si no aparece (calle mal escrita o que no está en el mapa),
            # el centro del pueblo: para el precio basta y se avisa.
            direccion = (d.get("direccion") or "").strip()
            pueblo = direccion.split(",")[-1].strip() if "," in direccion else ""
            for intento in [direccion] + ([pueblo] if pueblo and pueblo != direccion else []):
                try:
                    c = rutas.geocodificar(intento)
                except Exception as e:  # noqa: BLE001
                    print("motor geocodificar:", repr(e))
                    c = None
                if c:
                    if intento == pueblo:
                        avisos.append(f"No encuentro la calle de la {nombre}: calculo desde el centro de {pueblo}")
                    break
        if not c:
            avisos.append(f"No encuentro la dirección de {nombre}")
            return None, coords, avisos
        coords[lado] = c
    try:
        legs = rutas.tramos([HUELVA, coords["origen"], coords["destino"], HUELVA])
    except Exception as e:  # noqa: BLE001
        print("motor tramos:", repr(e))
        avisos.append("No he podido calcular la ruta por carretera")
        return None, coords, avisos
    return [(round(km, 1), round(mn, 1)) for km, mn in legs], coords, avisos


def en_provincia(coords):
    la0, la1, lo0, lo1 = PROVINCIA_HUELVA
    return all(la0 <= c[0] <= la1 and lo0 <= c[1] <= lo1 for c in (coords or {}).values()) and len(coords or {}) == 2


# ── 3. Cálculo ────────────────────────────────────────────────────────

def _cajas(e, c):
    """(frágiles, normales) que embalamos nosotros."""
    if e.get("embalaje") not in ("todo", "fragil"):
        return 0, 0
    total = e.get("items", {}).get("caja") or c["cajas_por_respuesta"].get(e.get("cajas_respuesta")) \
        or c["casa_cajas"].get(e.get("casa") or "", 0) or 10
    fragil = round(total * c["parte_fragil"])
    return (fragil, 0) if e["embalaje"] == "fragil" else (fragil, total - fragil)


def volumen(e, c):
    s = sum(c["vol"].get(k, c["vol"]["otro"]) * n for k, n in e.get("items", {}).items() if k != "caja")
    cajas_txt = e.get("items", {}).get("caja") or c["cajas_por_respuesta"].get(e.get("cajas_respuesta"))
    if cajas_txt:
        s += c["vol"]["caja"] * cajas_txt
    if e["tipo"] == "casa":
        if not cajas_txt:
            s *= 1 + c["margen_pequenos"]
        lo = c["casa_m3"].get(e.get("casa") or "", [0])[0]
        s = max(s, lo)
    return round(max(s, 0.5), 1)


def vehiculos(e, m3, cd_km, c, forzar_furgoneta=False):
    """[(tipo, viajes)]"""
    cap_f, cap_i = c["capacidad"]["crafter"], c["capacidad"]["iveco"]
    util_f = cap_f if forzar_furgoneta else cap_f * c["margen_furgoneta"]
    if cd_km < c["km_cerca"]:
        if e["tipo"] == "casa" or m3 > c["max_viajes_furgoneta"] * cap_f:
            return [("iveco", math.ceil(m3 / cap_i))]
        return [("crafter", max(1, math.ceil(m3 / cap_f)))]
    if e["tipo"] == "casa":
        if m3 <= cap_i:
            return [("iveco", 1)]
        return [("iveco", 1), ("crafter", 1)] if m3 <= cap_i + cap_f else [("iveco", 1), ("iveco", 1)]
    if m3 <= util_f:
        return [("crafter", 1)]
    return [("iveco", 1)] if m3 <= cap_i else [("iveco", 1), ("crafter", 1)]


def personas_por_volumen(e, m3):
    p = 2 if m3 < 6 else 3 if m3 <= 15 else 4 if m3 <= 25 else 5
    if e["tipo"] == "casa" and e.get("casa") in ("3", "4", "chalet"):
        p = max(p, 5)
    return p


def personas_viaje_largo(m3, c):
    return 2 if m3 <= c["capacidad"]["crafter"] else 3 if m3 <= 25 else 4


def _plan_barato(t, kind, km, dias):
    coste = lambda plan: float(t[f"rent_{kind}_{plan}"]) * dias + max(0, km - plan * dias) * float(t["extraKm"])
    return min((200, 400), key=coste)


def _horas(e, m3, p, legs, vehs, c):
    f = max(1.0, m3 / c["escala_m3"])
    mins = {"carga": c["carga_min_20m3_4p"] * (m3 / 20) * (4 / p)}
    mins["descarga"] = c["descarga_factor"] * mins["carga"]
    for lado, nombre in (("origen", "carga"), ("destino", "descarga")):
        a = e[lado]
        plantas = 0 if a.get("ascensor") else (a.get("piso") or 0)
        mins[f"escaleras en la {nombre}"] = c["min_planta"] * plantas * f
        mins[f"camión hasta el portal en la {nombre}"] = c["min_camion"].get(a.get("aparcamiento") or "100", 35) * f
    desm = sum(c["desmontaje_min"].get(k, 0) * n for k, n in e.get("items", {}).items()) / max(1, p / 2)
    if e.get("desmontaje") in ("si", "nose") and desm:
        mins["desmontaje y montaje"] = desm * (1 + c["factor_montaje"])
    elif e.get("desmontaje") == "desmontar":
        mins["desmontaje"] = desm
    cf, cn = _cajas(e, c)
    if cf + cn:
        mins["embalaje"] = (cf * c["min_caja_fragil"] + cn * c["min_caja_normal"]) / p
    (h0, m0), (cd, mcd), (dh, mdh) = legs
    viajes = max(v for _, v in vehs)
    km = 2 * c["km_recogida"] + h0 + cd + dh + (viajes - 1) * 2 * cd
    cond = 2 * c["min_recogida"] + (m0 + mcd + mdh + (viajes - 1) * 2 * mcd) * c["factor_conduccion"]
    trabajo = {k: v for k, v in mins.items() if v >= 0.5}
    return trabajo, sum(trabajo.values()) / 60, cond / 60, km, cf + cn


def _dias(e, h_trab, h_cond, provincia, c):
    total = h_trab + h_cond
    if total <= c["jornada"]:
        return 1
    if not provincia and h_cond <= c["conduccion_max_dia"] and total <= c["jornada_fuera"]:
        return 1
    return 2


def _coste(t, vehs, km, dias, horas, personas, socios, extras):
    vlist = [{"type": tp, "plan": _plan_barato(t, "furgoneta" if tp == "crafter" else "camion", km, dias),
              "days": dias, "km": round(km, 1)} for tp, _ in vehs]
    est = {"vehicles": vlist, "hours": horas, "workers": personas - socios, "partners": socios,
           "matQty": {}, "fuel": None, "extras": round(extras, 2)}
    return est, calcular(est, t)


def calcular_presupuesto(e, legs, tarifas=None, provincia=False, otro_trabajo_ese_dia=False, _forzar_furgoneta=False):
    """El cálculo completo. `legs` = [(km, min)] × 3. Devuelve dict con precio, desglose y alternativas."""
    t = {**DEFAULT_TARIFAS, **{k: v for k, v in (tarifas or {}).items() if k != "motor"}}
    c = cfg(tarifas)
    m3 = volumen(e, c)
    vehs = vehiculos(e, m3, legs[1][0], c, _forzar_furgoneta)
    p = personas_por_volumen(e, m3)
    mins, h_trab, h_cond, km, cajas = _horas(e, m3, p, legs, vehs, c)
    if h_cond >= c["ratio_viaje_largo"] * h_trab:          # viaje largo: manda el trabajo, no los m³
        p2 = min(p, personas_viaje_largo(m3, c))
        r2 = _horas(e, m3, p2, legs, vehs, c)
        if r2[2] >= r2[1]:
            p, (mins, h_trab, h_cond, km, cajas) = p2, r2
    dias = _dias(e, h_trab, h_cond, provincia, c)
    casa_grande = (e["tipo"] == "casa" and e.get("embalaje") == "todo" and h_trab + h_cond > c["jornada_casa_grande"])
    if h_trab / dias > c["jornada_trabajo_mas_uno"] and p < c["max_personas"] and not casa_grande:
        p += 1
        mins, h_trab, h_cond, km, cajas = _horas(e, m3, p, legs, vehs, c)
        dias = _dias(e, h_trab, h_cond, provincia, c)
    noches = 0
    if casa_grande:                                        # día 1 embalar y desmontar, día 2 llevar y montar
        dias = 2
        horas = max(math.ceil((h_trab + h_cond) * 2) / 2, 2 * c["jornada_casa_grande"])
    else:
        horas = max(c["horas_minimas"], math.ceil((h_trab + h_cond) * 2) / 2)
        noches = dias - 1
    socios = min(2, p)
    noche_eur = noches * (c["hotel_habitacion"] * math.ceil(p / c["personas_habitacion"]) + c["comida_persona"] * p)
    material = cajas * c["material_por_caja"]
    est, res = _coste(t, vehs, km, dias, horas, p, socios, material + noche_eur)

    alternativas = []
    if socios == 2:
        _, r1 = _coste(t, vehs, km, dias, horas, p, 1, material + noche_eur)
        alternativas.append({"tipo": "un_socio", "texto": "Con un solo socio (un trabajador en su lugar)",
                             "price": r1["price"]})
    if not _forzar_furgoneta and vehs == [("iveco", 1)] and m3 <= c["capacidad"]["crafter"] and e["tipo"] == "porte":
        rf = calcular_presupuesto(e, legs, tarifas, provincia, otro_trabajo_ese_dia, _forzar_furgoneta=True)
        alternativas.append({"tipo": "furgoneta_justa", "texto": "Con la furgoneta grande (va justa)",
                             "price": rf["price"], "estimate": rf["estimate"]})
    if otro_trabajo_ese_dia:
        # Solo horas, gasoil y km extra: el alquiler ya lo paga el otro trabajo y no hay mínimo de 2 h
        sin_alquiler = {**t, "rent_furgoneta_200": 0, "rent_furgoneta_400": 0, "rent_camion_200": 0,
                        "rent_camion_400": 0, "extraKm": 0}
        est_s = {**est, "vehicles": [{**v, "plan": 400, "days": 1} for v in est["vehicles"]],
                 "hours": math.ceil((h_trab + h_cond) * 2) / 2,
                 "extras": round(material + km * float(t["extraKm"]) * len(est["vehicles"]), 2)}
        alternativas.append({"tipo": "aprovechando_salida", "price": calcular(est_s, sin_alquiler)["price"],
                             "texto": "Aprovechando la salida de otro trabajo ese día (sin alquiler)"})

    return {"m3": m3, "vehiculos": vehs, "personas": p, "socios": socios, "dias": dias, "noches": noches,
            "horas": est["hours"], "horas_trabajo": round(h_trab, 2), "horas_conduccion": round(h_cond, 2),
            "km": round(km), "cajas": cajas, "minutos": {k: round(v) for k, v in mins.items()},
            "noche_eur": round(noche_eur, 2), "material_eur": round(material, 2), "casa_grande": casa_grande,
            "estimate": {**est, "m3": m3}, "result": res, "price": res["price"], "alternativas": alternativas}


# ── 4. Etiqueta y textos ──────────────────────────────────────────────

def revisar(e, legs, r, c):
    """(etiqueta, motivos, supuestos_aplicados). etiqueta: lista | revisar | a_mano."""
    a_mano, revisar_, supuestos = [], [], []
    if not e["items"] and not e.get("casa"):
        a_mano.append("No hay inventario ni tamaño de la vivienda")
    esp = set(e.get("especiales") or [])
    if esp & ESPECIALES_A_MANO:
        a_mano.append("Objeto especial: " + ", ".join(sorted(esp & ESPECIALES_A_MANO)))
    if legs is None:
        a_mano.append("Sin ruta: falta o no se encuentra una dirección")
    if r:
        if r["km"] > c["km_max"]:
            a_mano.append(f"{r['km']} km: más de {c['km_max']}")
        if len(r["vehiculos"]) > 2 or r["dias"] > 2:
            a_mano.append("Más de dos vehículos o de dos días")
    for lado, nombre in (("origen", "carga"), ("destino", "descarga")):
        a = e[lado]
        if a.get("piso") is None:
            supuestos.append(f"No dice el piso de la {nombre}: cuento bajo")
        elif a["piso"] > 0 and a.get("ascensor") is None:
            supuestos.append(f"No dice si hay ascensor en la {nombre}: cuento sin ascensor")
        if not a.get("aparcamiento"):
            supuestos.append(f"No dice dónde para el camión en la {nombre}: cuento a 30–100 m")
    if e.get("desmontaje") == "nose" and any(k in e["items"] for k in c["desmontaje_min"]):
        supuestos.append("No sabe si hay que desmontar: cuento desmontar y montar")
    if e["tipo"] == "casa" and not e["items"]:
        supuestos.append("Solo dice el tamaño de la casa: volumen típico")
    if e.get("embalaje") in ("todo", "fragil") and not (e["items"].get("caja") or e.get("cajas_respuesta") in c["cajas_por_respuesta"]):
        supuestos.append("No dice cuántas cajas: cuento las típicas de su casa")
    if esp - ESPECIALES_A_MANO:
        revisar_.append("Ojo: " + ", ".join(sorted(esp - ESPECIALES_A_MANO)))
    if e.get("otros"):
        revisar_.append("Hay muebles descritos a mano: «" + e["otros"][:80] + "»")
    if e.get("comentario"):
        revisar_.append("El cliente dejó un comentario")
    if e["tipo"] == "casa" and e["items"] and e.get("casa") and r:
        lo, hi = c["casa_m3"][e["casa"]]
        bruto = sum(c["vol"].get(k, 0.4) * n for k, n in e["items"].items())
        if bruto < lo * 0.6:
            revisar_.append(f"Los muebles marcados suman {bruto:.0f} m³; para esa casa cuento al menos {lo} m³ "
                            "(lo que no se marca: cajas, lámparas, cocina…)")
        elif bruto > hi * 1.4:
            revisar_.append(f"Los muebles marcados suman {bruto:.0f} m³: mucho para una casa de ese tamaño")
    if a_mano:
        return "a_mano", a_mano + revisar_ + supuestos, supuestos
    if revisar_ or supuestos:
        return "revisar", revisar_ + supuestos, supuestos
    return "lista", [], supuestos


def _veh_txt(vehs):
    return " + ".join(NOMBRE_VEH[t] + (f" ({v} viajes)" if v > 1 else "") for t, v in vehs)


def _n(x, dec=1):
    """Número en español: 6,6 · 18."""
    t = f"{x:.{dec}f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)
    return t.replace(".", ",")


def texto_supuestos(r, provincia):
    """Lo que hay detrás del precio, en frases cortas (el m³, vehículo y equipo van aparte, en `detalle`)."""
    lineas = [f"{_n(r['m3'])} m³ en {_veh_txt(r['vehiculos'])} · {r['km']} km"
              + (" (dentro de la provincia)" if provincia else ""),
              f"Horas: {_n(float(r['horas']))} (trabajo {_n(r['horas_trabajo'])} + conducción {_n(r['horas_conduccion'])})",
              "Trabajo: " + ", ".join(f"{k} {v} min" for k, v in r["minutos"].items() if v)]
    if r["casa_grande"]:
        lineas.append("Casa grande con embalaje: día 1 embalar y desmontar, día 2 llevar y montar")
    if r["noches"]:
        lineas.append(f"Noche fuera: {r['noche_eur']:.0f} € (hotel y comida)")
    if r["cajas"]:
        lineas.append(f"Embalaje: {r['cajas']} cajas · material {r['material_eur']:.0f} €")
    return lineas


# ── 5. Todo junto: lo que se guarda en la solicitud ──────────────────

def proponer(job, tarifas=None, rutas=None, otro_trabajo_ese_dia=False, ahora=None):
    """Calcula la propuesta del motor para una solicitud. Nunca lanza: si algo falla, etiqueta «a_mano»."""
    c = cfg(tarifas)
    e, _ = entrada_desde_solicitud(job)
    guardadas = (job.get("motorProposal") or {}).get("rutas") if isinstance(job.get("motorProposal"), dict) else None
    legs, coords, avisos = preparar_rutas(e, rutas, guardadas)
    provincia = en_provincia(coords)
    r = None
    if legs:
        try:
            r = calcular_presupuesto(e, legs, tarifas, provincia, otro_trabajo_ese_dia)
        except Exception as ex:  # noqa: BLE001
            avisos.append(f"Error del motor: {ex}")
    etiqueta, motivos, _ = revisar(e, legs, r, c)
    if etiqueta == "lista" and avisos:
        etiqueta = "revisar"
    motivos = avisos + [m for m in motivos if not (avisos and m.startswith("Sin ruta"))]
    prop = {"by": "Motor", "version": VERSION, "at": (ahora or datetime.now(timezone.utc)).isoformat(),
            "etiqueta": etiqueta, "motivos": motivos, "entrada": e,
            "rutas": {"legs": [{"km": km, "min": mn} for km, mn in legs], "coords": coords} if legs else None,
            "fotosSinRevisar": e["fotos"]}
    if r and etiqueta != "a_mano":
        prop.update({"price": r["price"], "estimate": r["estimate"], "result": r["result"],
                     "notes": "\n".join(texto_supuestos(r, provincia)),
                     "alternativas": r["alternativas"],
                     "detalle": {k: r[k] for k in ("m3", "personas", "socios", "dias", "horas", "horas_trabajo",
                                                    "horas_conduccion", "km", "cajas", "minutos", "noche_eur")}})
    elif r:
        prop["referencia"] = {"price": r["price"], "notes": "\n".join(texto_supuestos(r, provincia))}
    return prop
