"""
API de la app MudanzaPro (solo el equipo).

  POST /api/app   {accion, ...}   con el token de sesión de alguien del equipo
     leer_ticket   {path}   lee con IA la foto de un ticket ya subida a Storage
                            (trabajos/<uid>/gastos/...) y devuelve importe, tipo, comercio y fecha

La clave de Gemini vive en Secret Manager (GEMINI_KEY); nunca llega al navegador.
"""
import base64
import json
import os
import re

# Los mismos correos que EQUIPO en main.py y en firestore.rules
EQUIPO = {"albertogmez99@gmail.com", "contactomudanzasdelsur@gmail.com"}
TIPOS = ["vehiculo", "gasoil", "material", "comida", "peaje", "alojamiento", "otros"]
MAX_BYTES = 10 * 1024 * 1024
RUTA = re.compile(r"^trabajos/([A-Za-z0-9_-]{1,128})/gastos/[A-Za-z0-9_.-]{1,160}$")
FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")

PROMPT_TICKET = """Eres el ayudante de una empresa de mudanzas. Te paso la foto de un ticket o factura de un gasto.
Devuelve SOLO un JSON con estas claves:
- "es_ticket": true si es un ticket, factura o recibo legible; false si no.
- "importe": el TOTAL pagado en euros (número, con IVA incluido si lo lleva). Si hay varios importes, el total final.
- "tipo": uno de "vehiculo" (alquiler de furgoneta o camión, km extra), "gasoil" (gasolinera, combustible),
  "material" (cajas, film, cinta, embalaje, ferretería), "comida" (bar, restaurante, supermercado para comer),
  "peaje" (peaje, aparcamiento, parking), "alojamiento" (hotel, hostal) u "otros".
- "comercio": nombre del establecimiento, corto (máx. 40 caracteres).
- "fecha": fecha del ticket en formato AAAA-MM-DD, o null si no se lee.
No inventes: si no se lee el importe, pon null."""


class AppError(Exception):
    def __init__(self, status, mensaje):
        super().__init__(mensaje)
        self.status, self.mensaje = status, mensaje


def token_equipo(req, verificar=None):
    """(uid, email) si la petición trae el token de alguien del equipo; si no, None."""
    cab = req.headers.get("Authorization", "")
    if not cab.startswith("Bearer "):
        return None
    try:
        if verificar is None:
            from firebase_admin import auth as fb_auth
            verificar = fb_auth.verify_id_token
        tok = verificar(cab[7:].strip())
    except Exception:
        return None
    email = (tok.get("email") or "").lower()
    return (tok.get("uid"), email) if email in EQUIPO and tok.get("uid") else None


def limpiar_ticket(d):
    """Deja solo valores válidos de lo que devuelve la IA."""
    d = d if isinstance(d, dict) else {}
    try:
        importe = float(str(d.get("importe")).replace(",", "."))
        importe = round(importe, 2) if 0 < importe < 10000 else None
    except (TypeError, ValueError):
        importe = None
    tipo = d.get("tipo") if d.get("tipo") in TIPOS else "otros"
    comercio = re.sub(r"\s+", " ", str(d.get("comercio") or "")).strip()[:40]
    fecha = d.get("fecha") if isinstance(d.get("fecha"), str) and FECHA.match(d.get("fecha")) else None
    return {"es_ticket": bool(d.get("es_ticket", importe is not None)), "importe": importe,
            "tipo": tipo, "comercio": comercio, "fecha": fecha}


def leer_ticket(imagen, mime, clave, gem=None, modelos=None):
    if gem is None or modelos is None:
        from web_ia import gemini, MODELOS_FOTOS
        gem, modelos = gem or gemini, modelos or MODELOS_FOTOS
    from web_ia import _json_de_texto, WebError
    partes = [{"inline_data": {"mime_type": mime if mime.startswith("image/") else "image/jpeg",
                               "data": base64.b64encode(imagen).decode()}},
              {"text": PROMPT_TICKET}]
    motivos = []
    for modelo in modelos:
        try:
            texto = gem([modelo], [{"role": "user", "parts": partes}], clave, motivos=motivos, timeout=45,
                        config={"temperature": 0, "maxOutputTokens": 1024, "responseMimeType": "application/json",
                                "thinkingConfig": {"thinkingLevel": "low"}})
            return limpiar_ticket(_json_de_texto(texto))
        except WebError:
            continue
        except ValueError:
            motivos.append(f"{modelo}: JSON no válido")
    print("leer_ticket fallo:", " | ".join(motivos))
    raise AppError(503, "No he podido leer el ticket. Pon el importe a mano.")


def accion(body, uid, leer_bytes, clave, gem=None, modelos=None):
    body = body if isinstance(body, dict) else {}
    if body.get("accion") == "leer_ticket":
        path = str(body.get("path") or "")
        m = RUTA.match(path)
        if not m or m.group(1) != uid:
            raise AppError(400, "Foto no válida.")
        datos, mime = leer_bytes(path)
        if not datos or len(datos) > MAX_BYTES:
            raise AppError(400, "La foto no se puede leer.")
        return {"ok": True, **leer_ticket(datos, mime or "image/jpeg", clave, gem, modelos)}
    raise AppError(404, "Acción desconocida.")


def _leer_storage(path):
    from firebase_admin import storage
    blob = storage.bucket().blob(path)
    datos = blob.download_as_bytes()
    return datos, blob.content_type or "image/jpeg"


def handle(req, verificar=None, leer_bytes=None, gem=None, clave=None, modelos=None):
    from firebase_functions import https_fn

    def resp(obj, status=200):
        return https_fn.Response(json.dumps(obj, ensure_ascii=False), status=status,
                                 mimetype="application/json", headers={"Cache-Control": "no-store"})

    if req.method != "POST":
        return resp({"ok": False, "error": "No permitido."}, 405)
    t = token_equipo(req, verificar)
    if not t:
        return resp({"ok": False, "error": "Inicia sesión con una cuenta del equipo."}, 401)
    try:
        clave = clave if clave is not None else os.environ.get("GEMINI_KEY", "").strip()
        return resp(accion(req.get_json(silent=True), t[0], leer_bytes or _leer_storage, clave, gem, modelos))
    except AppError as e:
        return resp({"ok": False, "error": e.mensaje}, e.status)
    except Exception as e:  # noqa: BLE001
        print("app_api error:", repr(e))
        return resp({"ok": False, "error": "Algo ha fallado. Pon el importe a mano."}, 500)


try:
    from firebase_functions import https_fn, options

    @https_fn.on_request(region="europe-west1", memory=options.MemoryOption.MB_512, timeout_sec=60,
                         max_instances=2, secrets=["GEMINI_KEY"])
    def app_api(req: https_fn.Request) -> https_fn.Response:
        return handle(req)
except ImportError:  # pruebas locales sin firebase_functions
    pass
