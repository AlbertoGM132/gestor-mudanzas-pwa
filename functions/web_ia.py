"""
Funciones de IA de la web pública (mudanzasdelsur.es), en UNA función HTTP:

  POST /chat      asistente «Sur» (Gemini) que resuelve dudas de mudanzas
  POST /fotos     la IA mira las fotos del cliente y hace la lista de muebles
  POST /estimar   calcula un precio ORIENTATIVO con las tarifas reales y guarda
                  la solicitud en MudanzaPro (con fotos, inventario y propuesta)
  POST /contacto  formulario de contacto de la web → solicitud en MudanzaPro

Seguridad:
  - La clave de Gemini vive en Secret Manager (GEMINI_KEY); nunca llega al navegador.
  - Solo responde a las webs de Mudanzas del Sur (lista de orígenes permitidos).
  - Límites por persona (huella diaria de la IP, sin guardar la IP) y diarios
    globales, para no gastar la cuota gratuita.
  - Si la IA falla o no hay clave, se responde con un mensaje humano (WhatsApp).

La lógica está separada de Firebase/red para poder probarla.
"""
import base64
import io
import json
import math
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import estimador
import formulario_web as fw
from mcp_escritura import DEFAULT_TARIFAS
from web_conocimiento import CONOCIMIENTO

ORIGENES = {
    "https://mudanzasdelsur.es", "https://www.mudanzasdelsur.es",
    "https://mudanzas-del-sur.web.app", "https://mudanzas-del-sur.firebaseapp.com",
    "http://localhost:3000", "http://127.0.0.1:3000",
}
ORIGEN_PREVIEW = re.compile(r"^https://mudanzas-del-sur--[a-z0-9-]+\.web\.app$")

MODELOS_CHAT = [m.strip() for m in os.environ.get(
    "GEMINI_MODELOS_CHAT", "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-flash-lite-latest").split(",") if m.strip()]
MODELOS_FOTOS = [m.strip() for m in os.environ.get(
    "GEMINI_MODELOS_FOTOS", "gemini-3.6-flash,gemini-3.8-flash,gemini-3.5-flash-lite").split(",") if m.strip()]
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"

# (por minuto, por día y persona, total al día)
LIMITES = {"chat": (8, 80, 1500), "fotos": (3, 12, 300), "estimar": (3, 8, 120), "contacto": (3, 6, 60)}
MAX_FOTOS_IA = 8
LADO_IA = 1024
HUELVA = (37.2614, -6.9447)     # base desde la que salen los vehículos

WHATSAPP = "Escríbenos por WhatsApp al 659 71 52 71 y te atendemos enseguida."
SEGURIDAD = [{"category": c, "threshold": "BLOCK_ONLY_HIGH"} for c in (
    "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT")]

CATEGORIAS = list(estimador.VOLUMEN)
ESPECIALES = list(fw.ESPECIALES)
PROMPT_FOTOS = f"""Eres el ayudante de una empresa de mudanzas. Te paso fotos de la casa o de las cosas que un cliente quiere mudar.
Haz el INVENTARIO de los muebles y objetos que hay que transportar.
Devuelve EXCLUSIVAMENTE un objeto JSON válido (sin texto alrededor, sin ```), con EXACTAMENTE estas claves:
{{"items": [{{"nombre": "texto corto en español, p. ej. 'sofá de 3 plazas'", "categoria": "una de la lista", "cantidad": 1, "estancia": "salón|dormitorio|cocina|baño|terraza|otro"}}],
 "cajas": null, "fragil": false, "especiales": [], "fotos_sin_muebles": 0, "comentario": "una frase útil para la empresa o cadena vacía"}}
Categorías permitidas para "categoria": {", ".join(CATEGORIAS)}.
- armario2 = armario de 1-2 puertas; armario4 = 3-4 puertas; armario6 = 5-6 puertas o esquinero. canape = cama con canapé abatible.
- "especiales" solo puede contener: {", ".join(ESPECIALES)} (piano, caja fuerte, nevera americana, algo de más de 100 kg, plantas grandes, cuadros u obras de arte).
Reglas:
- Cuenta SOLO lo que se ve con claridad. NO inventes objetos que no aparecen.
- Si el mismo mueble sale en varias fotos, cuéntalo UNA vez.
- No cuentes lo que es parte del edificio (encimeras, armarios empotrados, sanitarios, radiadores, puertas).
- "cajas": número de cajas de mudanza ya hechas que se ven, o null si no hay.
- "fragil": true si se ve vajilla, cristalería, espejos o cuadros que haya que proteger.
- "fotos_sin_muebles": cuántas fotos no muestran muebles ni objetos para mudar.
- Si no hay nada que mudar en las fotos, devuelve "items": [].
"""


class WebError(Exception):
    def __init__(self, status, mensaje):
        super().__init__(mensaje)
        self.status = status
        self.mensaje = mensaje


def origen_permitido(origen):
    return bool(origen) and (origen in ORIGENES or bool(ORIGEN_PREVIEW.match(origen)))


# ── Gemini ──────────────────────────────────────────────────

def _post_json(url, body, headers, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def gemini(modelos, contents, clave, system=None, config=None, timeout=40, post=_post_json, motivos=None):
    """Prueba los modelos en orden. Devuelve el texto o lanza WebError(503).

    `motivos` (lista) recoge por qué falló cada modelo, sin datos sensibles, para el registro.
    """
    if not clave:
        raise WebError(503, "sin clave")
    motivos = motivos if motivos is not None else []
    for modelo in modelos:
        body = {"contents": contents, "safetySettings": SEGURIDAD, "generationConfig": dict(config or {})}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        for intento in (1, 2):
            try:
                data = post(GEMINI_URL.format(modelo), body, {"x-goog-api-key": clave}, timeout)
                cand = (data.get("candidates") or [{}])[0]
                partes = (cand.get("content") or {}).get("parts") or []
                texto = "".join(p.get("text", "") for p in partes if not p.get("thought"))
                if texto.strip():
                    return texto.strip()
                motivos.append(f"{modelo}: vacía ({cand.get('finishReason') or (data.get('promptFeedback') or {}).get('blockReason') or '?'})")
                break
            except urllib.error.HTTPError as e:
                try:
                    detalle = json.loads(e.read().decode()).get("error", {}).get("status", "")
                except Exception:  # noqa: BLE001
                    detalle = ""
                motivos.append(f"{modelo}: HTTP {e.code} {detalle}".strip())
                # Si el modelo no acepta la config de razonamiento, se reintenta sin ella
                if e.code == 400 and intento == 1 and "thinkingConfig" in body["generationConfig"]:
                    body["generationConfig"].pop("thinkingConfig")
                    continue
                break
            except Exception as e:  # noqa: BLE001 (timeouts, red)
                motivos.append(f"{modelo}: {type(e).__name__}")
                break
    print("gemini fallo:", " | ".join(motivos))
    raise WebError(503, "ia no disponible")


def _json_de_texto(texto):
    s = texto.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j < i:
        raise ValueError("sin JSON")
    return json.loads(s[i:j + 1])


# ── Chat ────────────────────────────────────────────────────

def chat(body, clave, gem=gemini):
    msg = fw._txt((body or {}).get("message"), 600)
    if not msg:
        raise WebError(400, "Escribe tu pregunta.")
    contents = []
    for h in ((body or {}).get("history") or [])[-8:]:
        if not isinstance(h, dict):
            continue
        rol = "model" if h.get("role") in ("model", "assistant", "bot") else "user"
        txt = fw._txt(h.get("text"), 800)
        if txt:
            contents.append({"role": rol, "parts": [{"text": txt}]})
    while contents and contents[0]["role"] != "user":
        contents.pop(0)
    contents.append({"role": "user", "parts": [{"text": msg}]})
    try:
        reply = gem(MODELOS_CHAT, contents, clave, system=CONOCIMIENTO,
                    config={"temperature": 0.4, "maxOutputTokens": 600, "thinkingConfig": {"thinkingLevel": "minimal"}})
    except WebError:
        return {"ok": False, "fallback": True,
                "reply": "Ahora mismo no puedo contestarte desde aquí. " + WHATSAPP}
    return {"ok": True, "reply": reply[:2000]}


# ── Fotos → inventario ──────────────────────────────────────

def foto_ia(dato):
    """Foto del cliente → JPEG pequeño (1024 px, sin EXIF) en base64 para la IA."""
    from PIL import Image, ImageOps
    s = str(dato or "")
    if s.startswith("data:"):
        s = s.split(",", 1)[-1]
    if len(s) > fw.MAX_FOTO_BYTES * 4 // 3 + 16:
        raise ValueError("foto demasiado grande")
    img = Image.open(io.BytesIO(base64.b64decode(s, validate=True)))
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((LADO_IA, LADO_IA))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=80)
    return base64.b64encode(out.getvalue()).decode()


def limpiar_inventario(raw):
    """Valida lo que devuelve la IA: nada fuera de la lista, nada inventado por el código."""
    raw = raw if isinstance(raw, dict) else {}
    items = []
    for it in (raw.get("items") or [])[:80]:
        if not isinstance(it, dict):
            continue
        try:
            n = int(it.get("cantidad") or 1)
        except (TypeError, ValueError):
            n = 1
        nombre = fw._txt(it.get("nombre"), 60)
        if not nombre:
            continue
        cat = it.get("categoria") if it.get("categoria") in estimador.VOLUMEN else "otro"
        items.append({"nombre": nombre, "categoria": cat, "cantidad": max(1, min(30, n)),
                      "estancia": fw._txt(it.get("estancia"), 20)})
    try:
        cajas = int(raw["cajas"]) if raw.get("cajas") not in (None, "") else None
    except (TypeError, ValueError):
        cajas = None
    return {"items": items, "cajas": cajas, "fragil": bool(raw.get("fragil")),
            "especiales": [e for e in (raw.get("especiales") or []) if e in fw.ESPECIALES],
            "comentario": fw._txt(raw.get("comentario"), 300)}


def fotos(body, clave, gem=gemini, preparar=foto_ia):
    lista = ((body or {}).get("fotos") or [])[:MAX_FOTOS_IA]
    if not lista:
        raise WebError(400, "Sube al menos una foto.")
    partes = []
    for f in lista:
        try:
            partes.append({"inline_data": {"mime_type": "image/jpeg", "data": preparar(f)}})
        except Exception:
            continue
    if not partes:
        raise WebError(400, "No hemos podido abrir las fotos. Prueba con fotos JPG o PNG.")
    tipo = "una casa completa" if (body or {}).get("tipo") != "porte" else "unas pocas cosas (un porte)"
    partes.append({"text": PROMPT_FOTOS + f"\nEl cliente dice que se muda {tipo}."})
    # Cada modelo por separado: si uno devuelve algo que no es JSON válido, se prueba el siguiente
    motivos, inv = [], None
    for modelo in MODELOS_FOTOS:
        try:
            texto = gem([modelo], [{"role": "user", "parts": partes}], clave, motivos=motivos, timeout=60,
                        config={"temperature": 0.1, "maxOutputTokens": 8192, "responseMimeType": "application/json",
                                "thinkingConfig": {"thinkingLevel": "low"}})
            inv = limpiar_inventario(_json_de_texto(texto))
            break
        except WebError:
            continue
        except ValueError:
            motivos.append(f"{modelo}: JSON no válido")
            continue
    if inv is None:
        print("fotos fallo:", " | ".join(motivos))
        return {"ok": False, "fallback": True, "motivo": " | ".join(motivos)[:300],
                "error": "No hemos podido analizar las fotos ahora mismo. Puedes poner tus muebles a mano."}
    inv["ok"] = True
    inv["fotos"] = len(partes) - 1
    return inv


# ── Distancias ──────────────────────────────────────────────

def _haversine(a, b):
    r = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _osrm(puntos, timeout=8):
    coords = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in puntos)
    url = f"https://router.project-osrm.org/route/v1/driving/{coords}?overview=false"
    req = urllib.request.Request(url, headers={"User-Agent": "MudanzasDelSur/1.0 (mudanzasdelsur.es)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode())
    return [leg["distance"] / 1000 for leg in data["routes"][0]["legs"]]


def tramos_km(origen, destino, ruta=_osrm):
    """(Huelva→carga, carga→descarga, descarga→Huelva) por carretera; si falla, en línea recta × 1,3."""
    puntos = [HUELVA, origen, destino, HUELVA]
    try:
        legs = ruta(puntos)
        if len(legs) == 3:
            return tuple(round(x, 1) for x in legs), "carretera"
    except Exception as e:  # noqa: BLE001
        print("osrm fallo:", repr(e))
    return tuple(round(_haversine(puntos[i], puntos[i + 1]) * 1.3, 1) for i in range(3)), "aprox"


def _coord(lado):
    try:
        lat, lng = float(lado.get("lat")), float(lado.get("lng"))
    except (TypeError, ValueError, AttributeError):
        return None
    if not (27 <= lat <= 44.5 and -19 <= lng <= 5):      # España (con Canarias)
        return None
    return (lat, lng)


# ── Calculadora → solicitud ─────────────────────────────────

def _items_entrada(lista):
    out = []
    for it in (lista or [])[:120]:
        if not isinstance(it, dict):
            continue
        try:
            n = int(it.get("cantidad") or 0)
        except (TypeError, ValueError):
            continue
        if n <= 0:
            continue
        out.append({"nombre": fw._txt(it.get("nombre"), 60) or it.get("categoria") or "objeto",
                    "categoria": it.get("categoria") if it.get("categoria") in estimador.VOLUMEN else "otro",
                    "cantidad": min(60, n)})
    return out


# Objetos de la calculadora → contadores del formulario (para el inventario de la app)
A_FORM = {"cama": "camas", "cama_individual": "camas", "canape": "canapes", "armario2": "armario2",
          "armario4": "armario4", "armario6": "armario6", "sofa": "sofas", "sofa_pequeno": "sofas",
          "frigorifico": "frigorifico", "lavadora": "lavadora", "secadora": "lavadora",
          "mesa": "mesas", "mesa_pequena": "mesas", "comoda": "comodas", "estanteria": "comodas", "aparador": "comodas"}


def _metros(v):
    try:
        m = float(v)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(2000.0, m))


def _parking(m):
    if m is None:
        return None
    return "puerta" if m < 10 else ("30" if m < 30 else ("100" if m <= 100 else "mas"))


def estimar(body, ip, repo, tarifas, ruta=_osrm, ahora=None):
    body = body if isinstance(body, dict) else {}
    # Bots: igual que el formulario (campo trampa / envío instantáneo)
    if fw._txt(body.get("web"), 200):
        return {"ok": True}
    if not body.get("consentimiento"):
        raise WebError(400, "Marca la casilla de privacidad para poder enviarte el estudio.")
    email = fw._txt(body.get("email"), 120)
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]{2,}", email):
        raise WebError(400, "Revisa el email: lo necesitamos para mandarte el estudio.")
    o_in, d_in = body.get("origen") or {}, body.get("destino") or {}
    o_xy, d_xy = _coord(o_in), _coord(d_in)
    if not o_xy or not d_xy:
        raise WebError(400, "Marca en el mapa las dos direcciones (origen y destino).")

    tipo = "porte" if body.get("tipo") == "porte" else "casa"
    items = _items_entrada(body.get("items"))
    lado = lambda x: {"piso": x.get("piso") if x.get("piso") in fw.PISOS else "bajo",
                      "ascensor": {"si": True, "no": False}.get(x.get("ascensor")),
                      "camion_m": _metros(x.get("camion_m"))}
    datos = {"tipo": tipo, "casa": body.get("casa"), "items": items, "origen": lado(o_in), "destino": lado(d_in),
             "desmontaje": body.get("desmontaje") if body.get("desmontaje") in fw.DESMONTAJE else "nose",
             "embalaje": body.get("embalaje") if body.get("embalaje") in fw.EMBALAJE else "yo",
             "especiales": [fw.ESPECIALES[e] for e in (body.get("especiales") or []) if e in fw.ESPECIALES]}
    legs, fuente_km = tramos_km(o_xy, d_xy, ruta)
    r = estimador.estimar(datos, legs, {**DEFAULT_TARIFAS, **(tarifas or {})})
    c = r["cliente"]

    # Lo mismo que el formulario de presupuesto, para que la app lo entienda igual
    muebles = {}
    for it in items:
        k = A_FORM.get(it["categoria"])
        if k:
            muebles[k] = muebles.get(k, 0) + it["cantidad"]
    otros = ", ".join(f"{it['cantidad']} {it['nombre']}" for it in items if it["categoria"] not in A_FORM)
    form = {
        "nombre": body.get("nombre"), "telefono": body.get("telefono"), "email": email,
        "t": body.get("t"), "web": "", "fecha": body.get("fecha"), "cuando": body.get("cuando"),
        "flexible": body.get("flexible"), "comentario": body.get("comentario"), "fotos": body.get("fotos"),
        "servicios": ["porte" if tipo == "porte" else "mudanza"],
        "inventario": {"casa": body.get("casa") if tipo == "casa" else None, "muebles": muebles, "otros": otros,
                       "desmontaje": datos["desmontaje"], "embalaje": datos["embalaje"],
                       "especiales": [e for e in (body.get("especiales") or []) if e in fw.ESPECIALES]},
    }
    for clave_lado, src, xy in (("origen", o_in, o_xy), ("destino", d_in, d_xy)):
        form[clave_lado] = {"calle": src.get("calle"), "poblacion": src.get("poblacion"),
                            "piso": src.get("piso"), "ascensor": src.get("ascensor"),
                            "aparcamiento": _parking(_metros(src.get("camion_m")))}

    rango = "sin precio (por la distancia, hay que calcularlo a mano)" if c["sin_precio"] else f"{c['min']}-{c['max']} €"
    nota = (f"🧮 Calculadora web: al cliente le salió {rango} (orientativo) · {c['m3']} m³ · "
            f"{c['vehiculo']} · {c['personas']} personas · {c['horas']} h · {c['km']} km")
    camion = [f"{n}: camión a ~{int(m)} m del portal" for n, m in
              (("Carga", datos["origen"]["camion_m"]), ("Descarga", datos["destino"]["camion_m"])) if m is not None]
    ahora_iso = (ahora or datetime.now(timezone.utc)).isoformat()
    extra = {
        "notas": [nota] + camion + (["⚠️ Km aproximados (sin ruta por carretera)"] if fuente_km != "carretera" else []),
        "origen_txt": "🌐 Llegó por la calculadora de la web",
        "createdBy": "Calculadora web",
        "data": {
            "originCoords": {"lat": o_xy[0], "lng": o_xy[1]}, "destinCoords": {"lat": d_xy[0], "lng": d_xy[1]},
            "webEstimate": {**c, "supuestos": r["supuestos"], "fuenteKm": fuente_km, "at": ahora_iso},
            "proposal": {"estimate": r["estimacion"], "result": r["resultado"], "price": r["resultado"]["price"],
                         "notes": "\n".join(r["supuestos"]), "confidence": "alta" if items else "media",
                         "at": ahora_iso, "by": "Calculadora web"},
        },
    }
    try:
        res = fw.procesar(form, ip, repo, ahora=ahora, extra=extra)
    except fw.FormError as e:
        raise WebError(e.status, e.mensaje)
    if res.get("ignorada"):
        return {"ok": True}
    publico = {k: c[k] for k in ("m3", "vehiculo", "personas", "horas", "dias", "km", "sin_precio", "especiales")}
    if not c["sin_precio"]:
        publico.update(min=c["min"], max=c["max"])
    return {"ok": True, "id": res.get("id"), "estudio": publico}


def contacto(body, ip, repo, ahora=None):
    body = body if isinstance(body, dict) else {}
    partes = [fw._txt(body.get("mensaje"), 1200)]
    if fw._txt(body.get("ruta"), 120):
        partes.insert(0, "Ruta: " + fw._txt(body.get("ruta"), 120))
    form = {"nombre": body.get("nombre"), "telefono": body.get("telefono"), "email": body.get("email"),
            "t": body.get("t"), "web": body.get("web"), "comentario": "\n".join(p for p in partes if p),
            "servicios": [s for s in (body.get("servicios") or []) if s in fw.SERVICIOS]}
    try:
        res = fw.procesar(form, ip, repo, ahora=ahora,
                          extra={"origen_txt": "🌐 Llegó por el formulario de contacto de la web", "createdBy": "Web"})
    except fw.FormError as e:
        raise WebError(e.status, e.mensaje)
    return {"ok": True}


# ── HTTP ────────────────────────────────────────────────────

def huella(ip, dia):
    return fw.huella_ip(f"web|{ip}", dia)


def handle(req, repo_factory=None, clave=None):
    origen = req.headers.get("Origin", "")
    cors = {"Access-Control-Allow-Origin": origen, "Vary": "Origin",
            "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Max-Age": "3600"} if origen_permitido(origen) else {"Vary": "Origin"}

    def resp(obj, status=200):
        from firebase_functions import https_fn
        return https_fn.Response(json.dumps(obj, ensure_ascii=False), status=status, mimetype="application/json",
                                 headers={**cors, "Cache-Control": "no-store"})

    if req.method == "OPTIONS":
        return resp({}, 204 if origen_permitido(origen) else 403)
    if req.method != "POST" or not origen_permitido(origen):
        return resp({"ok": False, "error": "No permitido."}, 403)
    accion = (req.path or "").rstrip("/").rsplit("/", 1)[-1]
    if accion not in LIMITES:
        return resp({"ok": False, "error": "No encontrado."}, 404)
    if (req.content_length or 0) > fw.MAX_BODY_BYTES:
        return resp({"ok": False, "error": "Las fotos pesan demasiado. Prueba con menos fotos."}, 413)

    ip = (req.headers.get("X-Forwarded-For") or req.remote_addr or "").split(",")[0].strip()
    body = req.get_json(silent=True)
    try:
        repo = (repo_factory or WebRepo)()
        ahora = datetime.now(timezone.utc)
        por_min, por_dia, total = LIMITES[accion]
        if not repo.limitar(accion, huella(ip or "?", ahora.strftime("%Y%m%d")), ahora, por_min, por_dia, total):
            return resp({"ok": False, "limite": True,
                         "error": "Has hecho muchas consultas seguidas. " + WHATSAPP}, 429)
        clave = clave if clave is not None else os.environ.get("GEMINI_KEY", "").strip()
        if accion == "chat":
            return resp(chat(body, clave))
        if accion == "fotos":
            return resp(fotos(body, clave))
        if accion == "estimar":
            return resp(estimar(body, ip, repo, repo.tarifas()))
        return resp(contacto(body, ip, repo))
    except WebError as e:
        return resp({"ok": False, "error": e.mensaje}, e.status)
    except Exception as e:  # noqa: BLE001
        print(f"web_api {accion} error:", repr(e))
        return resp({"ok": False, "error": "Algo ha fallado. " + WHATSAPP}, 500)


class WebRepo(fw.FirebaseFormRepo):
    """El repositorio del formulario + límites de la IA + tarifas."""

    def limitar(self, accion, huella_ip, ahora, por_min, por_dia, total):
        db, fs = self._db, self._fs
        minuto, dia = ahora.strftime("%Y%m%d%H%M"), ahora.strftime("%Y%m%d")
        ref_ip = db.collection("web_ia_limites").document(f"{accion}_{huella_ip}")
        ref_tot = db.collection("web_ia_limites").document(f"_{accion}")

        @fs.transactional
        def tx(t):
            a = ref_ip.get(transaction=t).to_dict() or {}
            g = ref_tot.get(transaction=t).to_dict() or {}
            n_min = a.get("n_min", 0) if a.get("minuto") == minuto else 0
            n_dia = a.get("n_dia", 0) if a.get("dia") == dia else 0
            n_tot = g.get("n", 0) if g.get("dia") == dia else 0
            if n_min >= por_min or n_dia >= por_dia or n_tot >= total:
                return False
            t.set(ref_ip, {"minuto": minuto, "n_min": n_min + 1, "dia": dia, "n_dia": n_dia + 1,
                           "caduca": datetime.now(timezone.utc) + timedelta(days=2)})
            t.set(ref_tot, {"dia": dia, "n": n_tot + 1})
            return True

        return tx(db.transaction())

    def tarifas(self):
        snap = self._db.collection("config").document("tarifas").get()
        return snap.to_dict() if snap.exists else {}


try:
    from firebase_functions import https_fn, options

    @https_fn.on_request(region="europe-west1", memory=options.MemoryOption.MB_512, timeout_sec=90,
                         max_instances=4, secrets=["GEMINI_KEY"])
    def web_api(req: https_fn.Request) -> https_fn.Response:
        return handle(req)
except ImportError:  # pruebas locales sin firebase_functions
    pass
