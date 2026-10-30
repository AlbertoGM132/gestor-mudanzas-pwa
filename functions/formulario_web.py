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
           "somieres": ("somier o base con patas", "somieres o bases con patas"), "colchones": ("colchón suelto", "colchones sueltos"),
           "armario2": ("armario de 2 puertas", "armarios de 2 puertas"), "armario4": ("armario de 4 puertas", "armarios de 4 puertas"),
           "armario6": ("armario de 6 puertas o esquinero", "armarios de 6 puertas o esquineros"),
           "comodas": ("cómoda, mesita o estantería", "cómodas, mesitas o estanterías"),
           "sofas": ("sofá", "sofás"), "sillones": ("sillón o butaca", "sillones o butacas"),
           "mesas": ("mesa", "mesas"), "mesascentro": ("mesa de centro o auxiliar", "mesas de centro o auxiliares"),
           "sillas": ("silla", "sillas"), "muebletv": ("mueble de TV, aparador o vitrina", "muebles de TV, aparadores o vitrinas"),
           "tv": ("televisor", "televisores"),
           "frigorifico": ("frigorífico", "frigoríficos"), "lavadora": ("lavadora/secadora", "lavadoras/secadoras"),
           "electro": ("otro electrodoméstico", "otros electrodomésticos"),
           "jardin": ("mueble de jardín o terraza", "muebles de jardín o terraza"),
           "escritorios": ("escritorio", "escritorios"), "bicis": ("bicicleta", "bicicletas")}
DESMONTAJE = {"si": "desmontar y montar (lo hacemos nosotros)", "desmontar": "solo desmontar",
              "no": "no hace falta", "nose": "no lo sabe"}
EMBALAJE = {"todo": "lo embalamos nosotros (todo)", "fragil": "nosotros solo lo frágil", "yo": "lo embala el cliente",
            "nada": "no hay nada que embalar (solo muebles)"}
ENTREGA = {"mismo": "el mismo día de la recogida", "espera": "puede esperar unos días"}
DUPLICADO_HORAS = 72                    # otra solicitud con el mismo teléfono en este plazo = posible repetida
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
        crudos = d.get("detalles") if isinstance(d.get("detalles"), dict) else {}
        detalles = {k: _txt(crudos.get(k), 200) for k in muebles if _txt(crudos.get(k), 200)}
        inv["muebles"] = {nombre(k, n): n for k, n in muebles.items()}
        if detalles:
            inv["detalles"] = {nombre(k, muebles[k]): t for k, t in detalles.items()}
        lineas.append("🛋 Muebles: " + ", ".join(
            f"{n} {nombre(k, n)}" + (f" ({detalles[k]})" if k in detalles else "") for k, n in muebles.items()))
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


def claves_formulario(body, raw_inv, comentario):
    """Lo marcado en el formulario con sus claves internas (para el motor de presupuestos).
    Las etiquetas de `inventory` son para leer; esto es para calcular."""
    muebles = {}
    for k, v in (raw_inv.get("muebles") or {}).items() if isinstance(raw_inv.get("muebles"), dict) else []:
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if k in MUEBLES and 0 < n <= 30:
            muebles[k] = n
    lado = lambda x: x.get("piso") if isinstance(x, dict) and x.get("piso") in PISOS else None
    elegido = lambda campo, tabla: raw_inv.get(campo) if raw_inv.get(campo) in tabla else None
    return {"casa": elegido("casa", CASAS), "muebles": muebles,
            "desmontaje": elegido("desmontaje", DESMONTAJE), "embalaje": elegido("embalaje", EMBALAJE),
            "cajas": elegido("cajas", CAJAS),
            "especiales": [x for x in (raw_inv.get("especiales") or []) if x in ESPECIALES],
            "origin_piso": lado(body.get("origen")), "destin_piso": lado(body.get("destino")),
            "comentario": bool(comentario), "entrega": body.get("entrega") if body.get("entrega") in ENTREGA else None}


def huella_ip(ip, dia):
    """No guardamos la IP: solo un resumen que cambia cada día."""
    return hashlib.sha256(f"mds-form|{dia}|{ip}".encode()).hexdigest()[:20]


def procesar(body, ip, repo, ahora=None, extra=None):
    """Valida y guarda una solicitud del formulario. Devuelve {'ok': True, ...}.

    `extra` (lo usa la calculadora de la web): {"notas": [...], "origen_txt": "...",
    "createdBy": "...", "data": {...campos añadidos a la solicitud}}.
    """
    extra = extra or {}
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
    entrega = ENTREGA.get(body.get("entrega"), "")

    inv, lineas_inv = inventario(body.get("inventario"))
    raw_inv = body.get("inventario") if isinstance(body.get("inventario"), dict) else {}
    # Lo que marca en desmontaje/embalaje también cuenta como servicio pedido
    deducidos = []
    if raw_inv.get("desmontaje") in ("si", "desmontar"):
        deducidos.append(SERVICIOS["montaje"])
    if raw_inv.get("embalaje") == "todo":
        deducidos.append(SERVICIOS["embalaje"])
    if raw_inv.get("embalaje") in ("todo", "fragil"):
        deducidos.append(SERVICIOS["fragil"])
    servicios += [x for x in deducidos if x not in servicios]

    notas = list(lineas_inv)
    if comentario:
        notas.append(comentario)
    if cuando_txt:
        notas.append(f"📅 Fecha que le viene bien: {cuando_txt}")
    if entrega:
        notas.append(f"🚚 Entrega: {entrega}")
    if body.get("fotos_whatsapp"):
        notas.append("📷 Dice que mandará las fotos por WhatsApp")
    notas += [str(x) for x in extra.get("notas") or []]
    notas.append(extra.get("origen_txt") or "🌐 Llegó por el formulario web")

    data = {
        "clientName": nombre, "phone": tel, "email": _txt(body.get("email"), 120),
        "location": o_pob or d_pob, "services": servicios,
        "originAddress": o_dir, "originFloor": o_piso, "originElevator": o_asc, "originAccess": o_acc,
        "destinAddress": d_dir, "destinFloor": d_piso, "destinElevator": d_asc, "destinAccess": d_acc,
        "notes": "\n".join(notas), "desiredDate": fecha,
        "desiredWhen": "" if fecha else (cuando if cuando in CUANDO else ""),
        "inventory": {**inv, **({"entrega": entrega} if entrega else {})},
        "stage": "solicitud", "date": "", "days": 1, "startTime": "08:00", "status": "pendiente",
        "crew": [], "vehicles": [], "materials": [], "photos": [], "price": "",
        "source": "web", "createdBy": extra.get("createdBy") or "Formulario web",
        "updatedBy": extra.get("createdBy") or "Formulario web",
        "formKeys": claves_formulario(body, raw_inv, comentario),
    }
    data.update(extra.get("data") or {})

    # 5) Fotos: las que fallen se saltan, no tiramos la solicitud por una foto
    # Cada foto puede llegar sola (data URL) o con lo que el cliente dice que sale en ella: {"data", "nota"}
    sello = ahora.strftime("%Y%m%d_%H%M%S")
    fallidas, pies = 0, []
    for i, f in enumerate((body.get("fotos") or [])[:MAX_FOTOS]):
        nota = _txt(f.get("nota"), 300) if isinstance(f, dict) else ""
        try:
            jpeg = foto_jpeg(f.get("data") if isinstance(f, dict) else f)
            ruta = f"trabajos/web/{sello}_{uuid.uuid4().hex[:6]}_{i + 1}.jpg"
            foto = {"url": repo.subir_foto(ruta, jpeg), "storagePath": ruta}
            if nota:
                foto["caption"] = nota
                pies.append(f"{len(data['photos']) + 1}) {nota}")
            data["photos"].append(foto)
        except Exception:
            fallidas += 1
    if pies:
        data["notes"] += "\n📷 Lo que sale en las fotos: " + " · ".join(pies)
    if fallidas:
        data["notes"] += f"\n⚠️ {fallidas} foto(s) no se pudieron guardar"

    # Misma persona que ya pidió presupuesto hace poco: casi siempre es una corrección de la anterior
    buscar = getattr(repo, "reciente_mismo_telefono", None)
    if buscar:
        try:
            previa = buscar(tel, ahora - timedelta(hours=DUPLICADO_HORAS))
        except Exception:
            previa = None
        if previa:
            data["possibleDuplicateOf"] = previa["id"]
            cuando_prev = previa.get("fecha") or "hace poco"
            data["notes"] = (f"⚠️ PUEDE ESTAR REPETIDA: el mismo teléfono ya pidió presupuesto {cuando_prev} "
                             f"({previa.get('nombre') or 'sin nombre'}). Compara las dos y quédate con una.\n" + data["notes"])

    doc_id = repo.crear(data)

    # 6) Aviso al equipo (solo nombre y población)
    try:
        lugar = f" ({data['location']})" if data["location"] else ""
        qué = f" · {', '.join(servicios)}" if servicios else ""
        repo.avisar("📥 Nueva solicitud", f"{nombre}{lugar}{qué} · {len(data['photos'])} fotos")
    except Exception:
        pass
    return {"ok": True, "id": doc_id, "fotos": len(data["photos"]), "fotos_fallidas": fallidas}


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

    def subir_foto(self, ruta, jpeg):
        token = str(uuid.uuid4())
        blob = self._bucket.blob(ruta)
        blob.metadata = {"firebaseStorageDownloadTokens": token}
        blob.upload_from_string(jpeg, content_type="image/jpeg")
        return (f"https://firebasestorage.googleapis.com/v0/b/{self._bucket.name}/o/"
                f"{quote(ruta, safe='')}?alt=media&token={token}")

    def reciente_mismo_telefono(self, tel, desde):
        """La solicitud más reciente con este teléfono creada después de `desde`, o None."""
        hit = None
        for d in self._db.collection("trabajos").where("phone", "==", tel).limit(20).stream():
            x = d.to_dict() or {}
            creado = x.get("createdAt")
            if creado is None or creado < desde or x.get("status") == "completado":
                continue
            if hit is None or creado > hit["_c"]:
                from zoneinfo import ZoneInfo
                local = creado.astimezone(ZoneInfo("Europe/Madrid"))
                hit = {"id": d.id, "nombre": x.get("clientName", ""), "fecha": f"el {local:%d/%m}", "_c": creado}
        return hit

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
