"""
Formulario público «Pide tu presupuesto» (public/presupuesto.html).

El cliente rellena el formulario sin cuenta; esta función valida lo que llega,
recomprime las fotos (quitando la ubicación GPS y demás datos EXIF), crea una
solicitud en `trabajos` (etapa 'solicitud', sin fecha) igual que las que se crean
desde la app o desde Claude, y avisa al equipo con una notificación push.

Antispam, sin molestar al cliente:
  - campo trampa oculto ('web') que solo rellenan los bots;
  - tiempo mínimo desde que se abre la página;
  - máximo de envíos por IP y hora, y máximo diario total.
A los bots se les responde "ok" sin guardar nada, para no darles pistas.

La lógica está en `procesar()` (sin Firebase) para poder probarla; el endpoint
HTTP y el repositorio de Firebase van al final.
"""
import base64
import binascii
import hashlib
import io
import json
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

MAX_FOTOS = 12
MAX_FOTO_BYTES = 6 * 1024 * 1024        # por foto, ya decodificada
MAX_BODY_BYTES = 24 * 1024 * 1024
LADO_FOTO = 1600                        # px del lado mayor al guardar
MIN_MS = 4000                           # menos que esto desde que abrió la página = bot
LIMITE_IP_HORA = 4
LIMITE_DIA = 40

SERVICIOS = {
    "mudanza": "Mudanza completa",
    "porte": "Porte",
    "montaje": "Desmontaje y montaje",
    "embalaje": "Embalaje",
    "fragil": "Vajilla / frágil",
    "otro": "Otro",
}
PISOS = {"bajo": "Bajo / casa", "1": "1º", "2": "2º", "3": "3º", "4": "4º o más"}
PARKING = {"puerta", "30", "100", "mas"}
CUANDO = {"pronto": "lo antes posible", "nosabe": "aún no lo sabe"}

CASAS = {"estudio": "Estudio", "1": "1 dormitorio", "2": "2 dormitorios", "3": "3 dormitorios",
         "4": "4 o más dormitorios", "chalet": "Chalet o casa grande"}
MUEBLES = {"camas": ("cama", "camas"), "canapes": ("canapé", "canapés"),
           "armario2": ("armario de 2 puertas", "armarios de 2 puertas"), "armario4": ("armario de 4 puertas", "armarios de 4 puertas"),
           "armario6": ("armario de 6 puertas o esquinero", "armarios de 6 puertas o esquineros"), "sofas": ("sofá", "sofás"),
           "frigorifico": ("frigorífico", "frigoríficos"), "lavadora": ("lavadora/secadora", "lavadoras/secadoras"),
           "mesas": ("mesa", "mesas"), "comodas": ("cómoda, aparador o estantería", "cómodas, aparadores o estanterías")}
DESMONTAJE = {"si": "desmontar y montar (lo hacemos nosotros)", "desmontar": "solo desmontar",
              "no": "no hace falta", "nose": "no lo sabe"}
EMBALAJE = {"todo": "lo embalamos nosotros (todo)", "fragil": "nosotros solo lo frágil", "yo": "lo embala el cliente"}
CAJAS = {"10": "menos de 10", "30": "10 a 30", "60": "30 a 60", "mas": "más de 60", "nose": "no lo sabe"}
ESPECIALES = {"piano": "piano", "caja-fuerte": "caja fuerte", "nevera-americana": "nevera americana",
              "pesado": "algo de más de 100 kg", "plantas": "plantas grandes", "arte": "cuadros u obras de arte"}

MSG_WHATSAPP = "Escríbenos por WhatsApp y te atendemos."


class FormError(Exception):
    def __init__(self, status, mensaje):
        super().__init__(mensaje)
        self.status = status
        self.mensaje = mensaje


def _txt(v, n):
    s = str(v or "")
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", s)
    return s.strip()[:n]


def telefono(v):
    """Devuelve el teléfono limpio (dígitos, con + si lo traía) o lanza FormError."""
    s = _txt(v, 30)
    digitos = re.sub(r"\D", "", s)
    if s.startswith("00"):
        digitos = digitos[2:]
        s = "+" + s[2:]
    if not 9 <= len(digitos) <= 15:
        raise FormError(400, "Revisa el teléfono: tiene que tener al menos 9 números.")
    if len(digitos) == 9:
        if digitos[0] not in "6789":
            raise FormError(400, "Revisa el teléfono: no parece un número español.")
        return f"{digitos[:3]} {digitos[3:6]} {digitos[6:]}"
    return ("+" if s.startswith("+") else "+") + digitos


def _lado(d):
    """Datos de una dirección del formulario → (dirección, piso, ascensor, accesos, población)."""
    d = d if isinstance(d, dict) else {}
    pob, calle = _txt(d.get("poblacion"), 60), _txt(d.get("calle"), 120)
    direccion = ", ".join(x for x in (calle, pob) if x)
    piso = PISOS.get(str(d.get("piso") or ""), "")
    asc = {"si": True, "no": False}.get(d.get("ascensor"))
    acceso = {}
    if d.get("aparcamiento") in PARKING:
        acceso["parking"] = d["aparcamiento"]
    return direccion, piso, asc, acceso, pob


def foto_jpeg(dato):
    """data URL o base64 → JPEG recomprimido, girado bien y sin EXIF (sin GPS)."""
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = 40_000_000
    s = str(dato or "")
    if s.startswith("data:"):
        s = s.split(",", 1)[-1]
    if len(s) > MAX_FOTO_BYTES * 4 // 3 + 16:
        raise ValueError("foto demasiado grande")
    try:
        raw = base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("foto no válida")
    img = Image.open(io.BytesIO(raw))
    if img.format not in ("JPEG", "PNG", "WEBP", "MPO", "HEIF", "HEIC"):
        raise ValueError(f"formato no admitido: {img.format}")
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")
    img.thumbnail((LADO_FOTO, LADO_FOTO))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=82, optimize=True)   # sin exif=… → no se copia nada
    return out.getvalue()


def inventario(d):
    """Lo que el cliente marca en el formulario → (dict ordenado, líneas para las notas)."""
    d = d if isinstance(d, dict) else {}
    inv, lineas = {}, []
    if d.get("casa") in CASAS:
        inv["casa"] = CASAS[d["casa"]]
        lineas.append(f"🏠 Casa: {inv['casa']}")
    muebles = {}
    for k, v in (d.get("muebles") or {}).items() if isinstance(d.get("muebles"), dict) else []:
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if k in MUEBLES and 0 < n <= 30:
            muebles[k] = n
    if muebles:
        nombre = lambda k, n: MUEBLES[k][0 if n == 1 else 1]
        inv["muebles"] = {nombre(k, n): n for k, n in muebles.items()}
        lineas.append("🛋 Muebles: " + ", ".join(f"{n} {nombre(k, n)}" for k, n in muebles.items()))
    otros = _txt(d.get("otros"), 800)
    if otros:
        inv["otros"] = otros
        lineas.append(f"🛋 Otros muebles: {otros}")
    for campo, tabla, icono, titulo in (("desmontaje", DESMONTAJE, "🔧", "Desmontaje"), ("embalaje", EMBALAJE, "📦", "Embalaje"),
                                        ("cajas", CAJAS, "📦", "Cajas")):
        if d.get(campo) in tabla:
            inv[campo] = tabla[d[campo]]
            lineas.append(f"{icono} {titulo}: {inv[campo]}")
    esp = [ESPECIALES[x] for x in (d.get("especiales") or []) if x in ESPECIALES]
    if esp:
        inv["especiales"] = esp
        lineas.append("⚠️ Especial: " + ", ".join(esp))
    return inv, lineas


SERV_CLAVES = {v: k for k, v in SERVICIOS.items()}


def calculadora(body, servicios, inv, raw_inv, repo):
    """Si la solicitud viene de la calculadora: horquilla orientativa con las tarifas reales."""
    c = body.get("calculadora")
    if not isinstance(c, dict):
        return None
    from estimador import estimar
    from mcp_escritura import DEFAULT_TARIFAS
    try:
        tarifas = {**DEFAULT_TARIFAS, **(repo.tarifas() or {})}
    except Exception:  # noqa: BLE001
        tarifas = dict(DEFAULT_TARIFAS)
    km = c.get("km") if isinstance(c.get("km"), dict) else {}
    lado = lambda d: {k: (d or {}).get(k) for k in ("piso", "ascensor", "aparcamiento")}
    datos = {"servicios": [SERV_CLAVES.get(s) for s in servicios], "inventario": raw_inv, "m3": c.get("m3"),
             "m3_fuente": "estimado por la IA con las fotos" if c.get("m3_ia") else "indicado por el cliente",
             "origen": lado(body.get("origen")), "destino": lado(body.get("destino")), "km": km}
    r = estimar(datos, tarifas)
    res = r["resumen"]
    notas = []
    ia = c.get("analisis_ia") if isinstance(c.get("analisis_ia"), dict) else None
    if ia and (ia.get("m3") or ia.get("muebles")):
        notas.append(f"🤖 La IA vio en las fotos: {ia.get('m3') or '—'} m³" + (f" · {ia.get('observaciones')}" if ia.get("observaciones") else ""))
    notas.append(f"📏 {res['m3']} m³ ({res['fuente_m3']}) · {res['vehiculos']} · {res['km']} km · {res['horas']} h · {res['personas']} personas")
    notas.append(f"💶 La web le mostró: {r['min']}–{r['max']} € (orientativo; el cálculo daba {r['precio']} €)")
    campos = {"webEstimate": {"min": r["min"], "max": r["max"], "price": r["precio"], "summary": res,
                              "estimate": r["estimacion"], "result": r["resultado"], "km": km,
                              "at": datetime.now(timezone.utc).isoformat()},
              "channel": "calculadora"}
    return {"notas": notas, "campos": campos,
            "horquilla": {"min": r["min"], "max": r["max"], "resumen": res}}


def huella_ip(ip, dia):
    """No guardamos la IP: solo un resumen que cambia cada día."""
    return hashlib.sha256(f"mds-form|{dia}|{ip}".encode()).hexdigest()[:20]


def procesar(body, ip, repo, ahora=None):
    """Valida y guarda una solicitud del formulario. Devuelve {'ok': True, ...}."""
    ahora = ahora or datetime.now(timezone.utc)
    if not isinstance(body, dict):
        raise FormError(400, "No se ha podido leer el formulario. " + MSG_WHATSAPP)

    # 1) Bots: campo trampa o envío instantáneo → "ok" sin guardar
    if _txt(body.get("web"), 200):
        return {"ok": True, "ignorada": "trampa"}
    try:
        ms = float(body.get("t") or 0)
    except (TypeError, ValueError):
        ms = 0
    if ms < MIN_MS:
        return {"ok": True, "ignorada": "rapida"}

    # 2) Datos obligatorios
    nombre = _txt(body.get("nombre"), 80)
    if len(nombre) < 2:
        raise FormError(400, "Pon tu nombre para saber a quién contestar.")
    tel = telefono(body.get("telefono"))

    # 3) Límites de envíos
    huella = huella_ip(ip or "?", ahora.strftime("%Y%m%d"))
    if not repo.contar_envio(huella, ahora.strftime("%Y%m%d%H"), ahora.strftime("%Y%m%d"),
                             LIMITE_IP_HORA, LIMITE_DIA):
        raise FormError(429, "Hemos recibido varias solicitudes seguidas. " + MSG_WHATSAPP)

    # 4) Resto del formulario (todo opcional)
    servicios = [SERVICIOS[s] for s in (body.get("servicios") or []) if s in SERVICIOS]
    o_dir, o_piso, o_asc, o_acc, o_pob = _lado(body.get("origen"))
    d_dir, d_piso, d_asc, d_acc, d_pob = _lado(body.get("destino"))
    comentario = _txt(body.get("comentario"), 1500)
    cuando = body.get("cuando")
    fecha = _txt(body.get("fecha"), 10)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fecha):
        fecha = ""
    if fecha:
        cuando_txt = datetime.strptime(fecha, "%Y-%m-%d").strftime("%d/%m/%Y")
        if body.get("flexible"):
            cuando_txt += " (con flexibilidad)"
    else:
        cuando_txt = CUANDO.get(cuando, "")

    inv, lineas_inv = inventario(body.get("inventario"))
    raw_inv = body.get("inventario") if isinstance(body.get("inventario"), dict) else {}
    # Lo que marca en desmontaje/embalaje también cuenta como servicio pedido
    extra = []
    if raw_inv.get("desmontaje") in ("si", "desmontar"):
        extra.append(SERVICIOS["montaje"])
    if raw_inv.get("embalaje") == "todo":
        extra.append(SERVICIOS["embalaje"])
    if raw_inv.get("embalaje") in ("todo", "fragil"):
        extra.append(SERVICIOS["fragil"])
    servicios += [x for x in extra if x not in servicios]

    notas = list(lineas_inv)
    calc = calculadora(body, servicios, inv, raw_inv, repo)
    if calc:
        notas += calc["notas"]
    if comentario:
        notas.append(comentario)
    if cuando_txt:
        notas.append(f"📅 Fecha que le viene bien: {cuando_txt}")
    if body.get("fotos_whatsapp"):
        notas.append("📷 Dice que mandará las fotos por WhatsApp")
    notas.append("🧮 Llegó por la calculadora de la web" if calc else "🌐 Llegó por el formulario web")

    data = {
        "clientName": nombre, "phone": tel, "email": _txt(body.get("email"), 120),
        "location": o_pob or d_pob, "services": servicios,
        "originAddress": o_dir, "originFloor": o_piso, "originElevator": o_asc, "originAccess": o_acc,
        "destinAddress": d_dir, "destinFloor": d_piso, "destinElevator": d_asc, "destinAccess": d_acc,
        "notes": "\n".join(notas), "desiredDate": fecha,
        "desiredWhen": "" if fecha else (cuando if cuando in CUANDO else ""),
        "inventory": inv,
        "stage": "solicitud", "date": "", "days": 1, "startTime": "08:00", "status": "pendiente",
        "crew": [], "vehicles": [], "materials": [], "photos": [], "price": "",
        "source": "web", "createdBy": "Formulario web", "updatedBy": "Formulario web",
    }
    if calc:
        data.update(calc["campos"])

    # 5) Fotos: las que fallen se saltan, no tiramos la solicitud por una foto
    sello = ahora.strftime("%Y%m%d_%H%M%S")
    fallidas = 0
    for i, f in enumerate((body.get("fotos") or [])[:MAX_FOTOS]):
        try:
            jpeg = foto_jpeg(f)
            ruta = f"trabajos/web/{sello}_{uuid.uuid4().hex[:6]}_{i + 1}.jpg"
            data["photos"].append({"url": repo.subir_foto(ruta, jpeg), "storagePath": ruta})
        except Exception:
            fallidas += 1
    if fallidas:
        data["notes"] += f"\n⚠️ {fallidas} foto(s) no se pudieron guardar"

    doc_id = repo.crear(data)

    # 6) Aviso al equipo (solo nombre y población)
    try:
        lugar = f" ({data['location']})" if data["location"] else ""
        qué = f" · {', '.join(servicios)}" if servicios else ""
        repo.avisar("📥 Nueva solicitud", f"{nombre}{lugar}{qué} · {len(data['photos'])} fotos")
    except Exception:
        pass
    out = {"ok": True, "id": doc_id, "fotos": len(data["photos"]), "fotos_fallidas": fallidas}
    if calc:
        out["horquilla"] = calc["horquilla"]
    return out


# ── Firebase ────────────────────────────────────────────────

class FirebaseFormRepo:
    def __init__(self):
        from firebase_admin import firestore, storage
        self._db = firestore.client()
        self._bucket = storage.bucket()
        self._fs = firestore

    def contar_envio(self, huella, hora, dia, lim_ip, lim_dia):
        """Suma el envío si cabe en los límites. Devuelve False si se pasa."""
        db, fs = self._db, self._fs
        ref_ip = db.collection("formulario_limites").document(huella)
        ref_dia = db.collection("formulario_limites").document("_dia")

        @fs.transactional
        def tx(t):
            ip = ref_ip.get(transaction=t).to_dict() or {}
            total = ref_dia.get(transaction=t).to_dict() or {}
            n_ip = ip.get("n", 0) if ip.get("hora") == hora else 0
            n_dia = total.get("n", 0) if total.get("dia") == dia else 0
            if n_ip >= lim_ip or n_dia >= lim_dia:
                return False
            caduca = datetime.now(timezone.utc) + timedelta(days=2)
            t.set(ref_ip, {"hora": hora, "n": n_ip + 1, "caduca": caduca})
            t.set(ref_dia, {"dia": dia, "n": n_dia + 1})
            return True

        return tx(db.transaction())

    def tarifas(self):
        snap = self._db.collection("config").document("tarifas").get()
        return snap.to_dict() if snap.exists else {}

    def subir_foto(self, ruta, jpeg):
        token = str(uuid.uuid4())
        blob = self._bucket.blob(ruta)
        blob.metadata = {"firebaseStorageDownloadTokens": token}
        blob.upload_from_string(jpeg, content_type="image/jpeg")
        return (f"https://firebasestorage.googleapis.com/v0/b/{self._bucket.name}/o/"
                f"{quote(ruta, safe='')}?alt=media&token={token}")

    def crear(self, data):
        ahora = self._fs.SERVER_TIMESTAMP
        ref = self._db.collection("trabajos").document()
        ref.set({**data, "createdAt": ahora, "updatedAt": ahora})
        return ref.id

    def avisar(self, titulo, texto):
        from firebase_admin import messaging
        tokens = sorted({(d.to_dict() or {}).get("token") for d in self._db.collection("fcm_tokens").stream()} - {None, ""})
        if not tokens:
            return
        # Solo datos: el service worker de la app pinta la notificación (así no sale repetida)
        msg = messaging.MulticastMessage(tokens=tokens[:500], data={"title": titulo, "body": texto, "url": "/"})
        messaging.send_each_for_multicast(msg)


def _json(obj, status=200):
    from firebase_functions import https_fn
    return https_fn.Response(json.dumps(obj, ensure_ascii=False), status=status,
                             mimetype="application/json", headers={"Cache-Control": "no-store"})


def handle(req, repo_factory=FirebaseFormRepo):
    from web_cors import cors_headers
    cab = cors_headers(req.headers.get("Origin", ""))
    if req.method == "OPTIONS":
        from firebase_functions import https_fn
        return https_fn.Response("", status=204 if cab else 403, headers=cab)
    r = _handle(req, repo_factory)
    for k, v in cab.items():
        r.headers[k] = v
    return r


def _handle(req, repo_factory):
    if req.method != "POST":
        return _json({"ok": False, "error": "Usa el formulario."}, 405)
    if (req.content_length or 0) > MAX_BODY_BYTES:
        return _json({"ok": False, "error": "Las fotos pesan demasiado. Prueba con menos fotos o " + MSG_WHATSAPP.lower()}, 413)
    body = req.get_json(silent=True)
    ip = (req.headers.get("X-Forwarded-For") or req.remote_addr or "").split(",")[0].strip()
    try:
        return _json(procesar(body, ip, repo_factory()))
    except FormError as e:
        return _json({"ok": False, "error": e.mensaje}, e.status)
    except Exception as e:  # noqa: BLE001
        print("solicitud_publica error:", repr(e))
        return _json({"ok": False, "error": "No se ha podido enviar. " + MSG_WHATSAPP}, 500)


try:
    from firebase_functions import https_fn, options

    @https_fn.on_request(region="europe-west1", memory=options.MemoryOption.MB_512,
                         timeout_sec=60, max_instances=3)
    def solicitud_publica(req: https_fn.Request) -> https_fn.Response:
        return handle(req)
except ImportError:  # pruebas locales sin firebase_functions
    pass
