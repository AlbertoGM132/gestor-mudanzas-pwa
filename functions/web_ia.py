"""
IA de la web mudanzasdelsur.es (servida en presupuesto.mudanzasdelsur.es/api/ia/…):

  POST /api/ia/chat   {message, history[]}      → {ok, reply}
  POST /api/ia/fotos  {fotos:[dataURL…]}        → {ok, analisis:{casa, muebles, otros, m3, cajas, observaciones}}
  POST /api/ia/ruta   {origen, destino}         → {ok, km:{…}, puntos:{…}, linea:[[lat,lon]…]}

- La clave de Gemini (secreto GEMINI_KEY) solo vive aquí, nunca en la web.
- Solo responde a la web de Mudanzas del Sur (CORS + Origin obligatorio).
- Límites por IP y diarios para no gastar la capa gratuita de Gemini.
- Si la IA falla o no hay clave, devuelve un mensaje humano (la web tiene plan B).
"""
import base64
import hashlib
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from web_cors import cors_headers, origen_permitido

GEMINI_MODELOS = ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-flash-latest"]
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
UA = "MudanzasDelSur-web/1.0 (contactomudanzasdelsur@gmail.com)"
BASE = {"lat": 37.2614, "lon": -6.9447, "label": "Huelva"}           # de aquí salen los vehículos
WHATSAPP = "659 71 52 71"

LIMITES = {          # (por minuto e IP, por día e IP, total al día)
    "chat": (8, 100, 1500),
    "fotos": (4, 30, 300),
    "ruta": (10, 60, 1000),
}
MAX_FOTOS_IA = 8
MUEBLES_IA = ["camas", "canapes", "armario2", "armario4", "armario6", "sofas", "frigorifico", "lavadora", "mesas", "comodas"]
CASAS_IA = ["estudio", "1", "2", "3", "4", "chalet"]

CONOCIMIENTO = f"""Eres «Sur», el asistente de la web de Mudanzas del Sur, empresa de mudanzas con sede en Huelva.
Respondes en español de España, con tono cercano y profesional, en frases cortas (máximo 5-6 líneas).

QUÉ HACEMOS (solo esto; no inventes otros servicios):
- Mudanzas de particulares (pisos, casas, chalets) y de empresas y oficinas.
- Mudanzas locales en Huelva y provincia, y nacionales a toda la península.
- Portes (pocos muebles o cosas sueltas).
- Embalaje y desembalaje profesional (también vajilla y objetos frágiles), con material incluido cuando lo hacemos nosotros.
- Desmontaje y montaje de muebles (armarios, camas, canapés…).
- Traslado de empresas: clasificación de archivos y mobiliario, horarios flexibles y nocturnos para no parar el negocio.

CÓMO TRABAJAMOS:
- Presupuesto gratis y sin compromiso. Precio cerrado: el que se da es el que se paga, sin sorpresas.
- Seguro de transporte incluido en todos los servicios.
- 15 % de descuento en la primera mudanza para nuevos clientes, sin mínimo de servicio.
- Atendemos todos los días. Contacto: WhatsApp o teléfono {WHATSAPP}, email contactomudanzasdelsur@gmail.com.
- Para dar precio necesitamos ver lo que hay que llevar (fotos o un vídeo por WhatsApp), el piso y si hay ascensor en origen y destino, y dónde puede parar el camión.

CONSEJOS QUE PUEDES DAR (resumidos):
- Frágiles: caja pequeña de doble capa, platos de canto, rellenar huecos, marcar FRÁGIL y la habitación.
- No embalar: inflamables, productos químicos, alimentos perecederos; joyas, dinero y documentos importantes, mejor en tu propio coche.
- Preparación: vaciar armarios y cajones, descongelar el frigorífico el día antes, reservar sitio para el camión o pedir permiso de carga si hace falta, preparar una caja de «primera noche».

REGLAS:
- No des precios concretos ni rangos inventados: invita a usar la CALCULADORA de la web (botón «Calcula tu mudanza», te da un precio orientativo en 2 minutos con fotos) o a pedir presupuesto por WhatsApp al {WHATSAPP}.
- Si preguntan por algo que no está en esta lista (guardamuebles, pianos, mudanzas internacionales, fechas libres concretas…), di que lo consulten por WhatsApp y que Alberto les responde enseguida. No prometas nada que no esté aquí.
- No pidas datos personales en el chat (dirección, DNI…). Para el presupuesto, que usen la calculadora o WhatsApp.
- Si la pregunta no tiene que ver con mudanzas, responde amablemente que solo puedes ayudar con mudanzas.
- Termina, cuando venga a cuento, invitando a calcular su mudanza o a escribir por WhatsApp."""

PROMPT_FOTOS = """Eres un experto en mudanzas que estima el volumen de una vivienda a partir de fotos.
Mira TODAS las fotos y devuelve EXCLUSIVAMENTE un objeto JSON válido (sin texto ni ```), con EXACTAMENTE estas claves:
{
 "casa": uno de "estudio","1","2","3","4","chalet" (dormitorios que se deducen) o null si no se puede saber,
 "muebles": {"camas":n,"canapes":n,"armario2":n,"armario4":n,"armario6":n,"sofas":n,"frigorifico":n,"lavadora":n,"mesas":n,"comodas":n},
 "otros": texto corto con otros muebles o bultos grandes que veas (o ""),
 "m3": número con el volumen total aproximado en metros cúbicos de todo lo que se ve (muebles + cajas + enseres),
 "cajas": número aproximado de cajas de mudanza necesarias para los enseres sueltos que se ven, o null,
 "observaciones": texto corto con lo que haga la mudanza más difícil o fácil (objetos frágiles, muy pesados, escaleras visibles…) o ""
}
Reglas: cuenta SOLO lo que se ve en las fotos; si un tipo de mueble no aparece, pon 0; armario2/armario4/armario6 = armarios de 2, 4 y 6+ puertas o esquineros; canapes = camas con arcón; comodas = cómodas, aparadores, estanterías y muebles bajos; lavadora incluye secadora y lavavajillas sueltos.
No inventes: si una foto no sirve, ignórala. Usa punto como decimal."""


class IAError(Exception):
    def __init__(self, status, mensaje):
        super().__init__(mensaje)
        self.status, self.mensaje = status, mensaje


def _txt(v, n):
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(v or "")).strip()[:n]


# ── Gemini ───────────────────────────────────────────────────

def gemini(key, contents, system=None, json_mode=False, temperature=0.4, max_tokens=700, http=None):
    """Llama a Gemini probando varios modelos. Devuelve el texto o lanza IAError."""
    http = http or urllib.request.urlopen
    if not key:
        raise IAError(503, "sin_clave")
    cfg = {"temperature": temperature, "maxOutputTokens": max_tokens}
    if json_mode:
        cfg["responseMimeType"] = "application/json"
    body = {"contents": contents, "generationConfig": cfg,
            "safetySettings": [{"category": c, "threshold": "BLOCK_ONLY_HIGH"} for c in
                               ("HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
                                "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT")]}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    ultimo = None
    for modelo in GEMINI_MODELOS:
        req = urllib.request.Request(GEMINI_URL.format(modelo=modelo), data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "x-goog-api-key": key}, method="POST")
        try:
            with http(req, timeout=40) as r:
                data = json.loads(r.read().decode())
            partes = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
            texto = "".join(p.get("text", "") for p in partes).strip()
            if texto:
                return texto
            ultimo = "respuesta vacía"
        except Exception as e:  # noqa: BLE001 — probamos el siguiente modelo
            ultimo = repr(e)[:200]
    print("gemini falló:", ultimo)
    raise IAError(502, "ia_no_disponible")


# ── Asistente ────────────────────────────────────────────────

def chat(body, key, http=None):
    msg = _txt((body or {}).get("message"), 600)
    if not msg:
        raise IAError(400, "Escribe tu pregunta.")
    hist = []
    for h in ((body or {}).get("history") or [])[-8:]:
        if isinstance(h, dict) and h.get("role") in ("user", "assistant") and _txt(h.get("text"), 600):
            hist.append({"role": "user" if h["role"] == "user" else "model", "parts": [{"text": _txt(h["text"], 600)}]})
    contents = hist + [{"role": "user", "parts": [{"text": msg}]}]
    try:
        reply = gemini(key, contents, system=CONOCIMIENTO, temperature=0.4, max_tokens=500, http=http)
        return {"ok": True, "reply": reply[:1500]}
    except IAError:
        return {"ok": False, "fallback": True,
                "reply": f"Ahora mismo no puedo responder, perdona. Escríbenos por WhatsApp al {WHATSAPP} y te contestamos enseguida 🙂"}


# ── Lector de fotos ──────────────────────────────────────────

def limpiar_analisis(d):
    """Valida lo que devuelve la IA. Lo que no cuadre → vacío (nunca inventado)."""
    d = d if isinstance(d, dict) else {}
    out = {"casa": d.get("casa") if d.get("casa") in CASAS_IA else None, "muebles": {}}
    m = d.get("muebles") if isinstance(d.get("muebles"), dict) else {}
    for k in MUEBLES_IA:
        try:
            n = int(round(float(m.get(k) or 0)))
        except (TypeError, ValueError):
            n = 0
        if 0 < n <= 30:
            out["muebles"][k] = n
    out["otros"] = _txt(d.get("otros"), 300)
    try:
        m3 = float(d.get("m3"))
        out["m3"] = round(m3, 1) if 0.5 <= m3 <= 150 else None
    except (TypeError, ValueError):
        out["m3"] = None
    try:
        c = int(round(float(d.get("cajas"))))
        out["cajas"] = c if 0 <= c <= 400 else None
    except (TypeError, ValueError):
        out["cajas"] = None
    out["observaciones"] = _txt(d.get("observaciones"), 300)
    return out


def analizar_fotos(body, key, http=None, recomprimir=None):
    fotos = [f for f in ((body or {}).get("fotos") or []) if isinstance(f, str)][:MAX_FOTOS_IA]
    if not fotos:
        raise IAError(400, "Añade al menos una foto.")
    if recomprimir is None:
        from formulario_web import foto_jpeg as recomprimir
    partes = []
    for f in fotos:
        try:
            jpeg = recomprimir(f)                      # quita GPS/EXIF y reduce
        except Exception:
            continue
        partes.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(jpeg).decode()}})
    if not partes:
        raise IAError(400, "No hemos podido abrir las fotos. Prueba con otras o mándalas por WhatsApp.")
    try:
        texto = gemini(key, [{"role": "user", "parts": partes + [{"text": PROMPT_FOTOS}]}],
                       json_mode=True, temperature=0.1, max_tokens=800, http=http)
    except IAError:
        return {"ok": False, "fallback": True,
                "error": "Ahora mismo la IA no puede mirar las fotos. Rellena los muebles a mano y sigue adelante 🙂"}
    texto = re.sub(r"^```(json)?|```$", "", texto.strip()).strip()
    try:
        datos = json.loads(texto)
    except ValueError:
        return {"ok": False, "fallback": True, "error": "No hemos podido leer bien las fotos. Rellena los muebles a mano 🙂"}
    return {"ok": True, "analisis": limpiar_analisis(datos), "fotos_usadas": len(partes)}


# ── Ruta (km) ────────────────────────────────────────────────

def _get_json(url, http):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "es"})
    with http(req, timeout=15) as r:
        return json.loads(r.read().decode())


def geocodificar(texto, http=None):
    http = http or urllib.request.urlopen
    q = urllib.parse.urlencode({"q": texto, "format": "json", "limit": 1, "countrycodes": "es,pt", "addressdetails": 0})
    res = _get_json(f"https://nominatim.openstreetmap.org/search?{q}", http)
    if not res:
        return None
    r = res[0]
    return {"lat": float(r["lat"]), "lon": float(r["lon"]), "label": _txt(r.get("display_name"), 140)}


def _haversine(a, b):
    import math
    R = 6371.0
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp, dl = p2 - p1, math.radians(b["lon"] - a["lon"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def ruta(body, http=None):
    http = http or urllib.request.urlopen
    o_txt, d_txt = _txt((body or {}).get("origen"), 160), _txt((body or {}).get("destino"), 160)
    if len(o_txt) < 3 or len(d_txt) < 3:
        raise IAError(400, "Escribe el pueblo o la dirección de origen y de destino.")
    try:
        o, d = geocodificar(o_txt, http), geocodificar(d_txt, http)
    except Exception as e:  # noqa: BLE001
        print("geocodificar:", repr(e)[:200])
        o = d = None
    if not o or not d:
        falta = "origen" if not o else "destino"
        return {"ok": False, "error": f"No encontramos la dirección de {falta}. Prueba solo con el pueblo o la ciudad."}
    puntos = [BASE, o, d, BASE]
    coords = ";".join(f"{p['lon']:.5f},{p['lat']:.5f}" for p in puntos)
    km, linea, aprox = None, [], False
    try:
        r = _get_json(f"https://router.project-osrm.org/route/v1/driving/{coords}?overview=simplified&geometries=geojson", http)
        if r.get("code") == "Ok":
            legs = r["routes"][0]["legs"]
            km = [round(l["distance"] / 1000, 1) for l in legs]
            linea = [[c[1], c[0]] for c in r["routes"][0]["geometry"]["coordinates"]][:400]
    except Exception as e:  # noqa: BLE001
        print("osrm:", repr(e)[:200])
    if not km:                                     # plan B: línea recta × 1,3
        aprox = True
        km = [round(_haversine(a, b) * 1.3, 1) for a, b in zip(puntos, puntos[1:])]
        linea = [[p["lat"], p["lon"]] for p in puntos]
    return {"ok": True, "aproximado": aprox,
            "km": {"base_origen": km[0], "origen_destino": km[1], "destino_base": km[2]},
            "puntos": {"base": BASE, "origen": o, "destino": d}, "linea": linea}


# ── Límites de uso ───────────────────────────────────────────

def huella(ip, dia):
    return hashlib.sha256(f"mds-ia|{dia}|{ip}".encode()).hexdigest()[:20]


class FirebaseIARepo:
    def __init__(self):
        from firebase_admin import firestore
        self._db, self._fs = firestore.client(), firestore

    def contar(self, tipo, h, minuto, dia, lim):
        lim_min, lim_dia, lim_total = lim
        db, fs = self._db, self._fs
        ref_ip = db.collection("ia_limites").document(f"{tipo}_{h}")
        ref_tot = db.collection("ia_limites").document(f"{tipo}__total")

        @fs.transactional
        def tx(t):
            a = ref_ip.get(transaction=t).to_dict() or {}
            b = ref_tot.get(transaction=t).to_dict() or {}
            n_dia = a.get("n", 0) if a.get("dia") == dia else 0
            n_min = a.get("n_min", 0) if a.get("min") == minuto else 0
            n_tot = b.get("n", 0) if b.get("dia") == dia else 0
            if n_min >= lim_min or n_dia >= lim_dia or n_tot >= lim_total:
                return False
            t.set(ref_ip, {"dia": dia, "n": n_dia + 1, "min": minuto, "n_min": n_min + 1,
                           "caduca": datetime.now(timezone.utc) + timedelta(days=2)})
            t.set(ref_tot, {"dia": dia, "n": n_tot + 1})
            return True

        return tx(db.transaction())


def procesar(path, body, ip, key, repo, http=None, ahora=None):
    ahora = ahora or datetime.now(timezone.utc)
    tipo = (path or "").rstrip("/").rsplit("/", 1)[-1]
    if tipo not in LIMITES:
        raise IAError(404, "No existe.")
    if not repo.contar(tipo, huella(ip or "?", ahora.strftime("%Y%m%d")), ahora.strftime("%Y%m%d%H%M"),
                       ahora.strftime("%Y%m%d"), LIMITES[tipo]):
        raise IAError(429, f"Has hecho muchas consultas seguidas. Espera un poco o escríbenos por WhatsApp al {WHATSAPP} 🙂")
    if tipo == "chat":
        return chat(body, key, http)
    if tipo == "fotos":
        return analizar_fotos(body, key, http)
    return ruta(body, http)


# ── HTTP ─────────────────────────────────────────────────────

def handle(req, key, repo_factory=FirebaseIARepo, http=None):
    from firebase_functions import https_fn
    origin = req.headers.get("Origin", "")
    cab = cors_headers(origin)

    def resp(obj, status=200):
        return https_fn.Response(json.dumps(obj, ensure_ascii=False), status=status, mimetype="application/json",
                                 headers={**cab, "Cache-Control": "no-store"})

    if req.method == "OPTIONS":
        return https_fn.Response("", status=204 if cab else 403, headers=cab)
    if not origen_permitido(origin):
        return resp({"ok": False, "error": "No permitido."}, 403)
    if req.method != "POST":
        return resp({"ok": False, "error": "Usa la web."}, 405)
    if (req.content_length or 0) > 16 * 1024 * 1024:
        return resp({"ok": False, "error": "Las fotos pesan demasiado. Prueba con menos."}, 413)
    ip = (req.headers.get("X-Forwarded-For") or req.remote_addr or "").split(",")[0].strip()
    try:
        return resp(procesar(req.path, req.get_json(silent=True) or {}, ip, key, repo_factory(), http))
    except IAError as e:
        return resp({"ok": False, "error": e.mensaje}, e.status)
    except Exception as e:  # noqa: BLE001
        print("web_ia error:", repr(e))
        return resp({"ok": False, "error": f"Algo ha fallado. Escríbenos por WhatsApp al {WHATSAPP}."}, 500)


try:
    from firebase_functions import https_fn, options
    from firebase_functions.params import SecretParam

    GEMINI_KEY = SecretParam("GEMINI_KEY")

    @https_fn.on_request(region="europe-west1", memory=options.MemoryOption.MB_512, timeout_sec=60,
                         max_instances=3, secrets=[GEMINI_KEY])
    def web_ia(req: https_fn.Request) -> https_fn.Response:
        try:
            key = GEMINI_KEY.value
        except Exception:  # noqa: BLE001 — sin secreto configurado: la web usa su plan B
            key = ""
        return handle(req, (key or "").strip())
except ImportError:
    pass
