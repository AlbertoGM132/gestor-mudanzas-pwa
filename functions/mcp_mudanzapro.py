"""
Conector MCP de MudanzaPro (solo lectura) para Claude.

Expone los trabajos de la colección 'trabajos' y sus fotos como herramientas
MCP sobre HTTP (transporte "Streamable HTTP", modo sin estado).

URL del conector (la que se pega en Claude → Ajustes → Conectores):
  https://europe-west1-<PROYECTO>.cloudfunctions.net/mudanzapro_mcp
con la cabecera de solicitud  Authorization: Bearer <MCP_KEY>
(también se acepta X-API-Key: <MCP_KEY>, o la clave al final de la URL).

La clave MCP_KEY es un secreto de Firebase:
  firebase functions:secrets:set MCP_KEY
Cualquiera que tenga la clave puede LEER los trabajos, así que no la compartas. Para revocarla, cambia el secreto y vuelve a desplegar.

Por privacidad, el conector NO devuelve teléfono, email ni datos económicos.
"""
import base64
import hmac
import io
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from firebase_functions import https_fn, options
from firebase_functions.params import SecretParam

MCP_KEY = SecretParam("MCP_KEY")

SERVER_INFO = {"name": "mudanzapro", "version": "1.0.0"}
DEFAULT_PROTOCOL = "2025-06-18"
MAX_RANGE_DAYS = 92
MAX_FOTOS = 8
FOTO_MAX_PX = 1024

# Campos del trabajo que se exponen (nada de teléfono, email ni dinero).
CAMPOS_PUBLICOS = [
    "date", "startTime", "endTime", "status", "clientName",
    "originAddress", "originFloor", "originElevator",
    "destinAddress", "destinFloor", "destinElevator",
    "vehicle", "team", "materials", "notes",
]

STATUS_LABEL = {"completado": "completado", "en_curso": "en curso"}

TOOLS = [
    {
        "name": "listar_mudanzas",
        "title": "Listar mudanzas",
        "description": (
            "Lista los trabajos de MudanzaPro (mudanzas, portes, montajes) entre dos "
            "fechas, ordenados por fecha y hora. Devuelve id, fecha, horario, estado, "
            "cliente, origen y destino (con piso y ascensor), vehículo, equipo, "
            "materiales, notas y cuántas fotos tiene. Por defecto, de hoy a 14 días."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "desde": {"type": "string", "description": "Fecha inicial YYYY-MM-DD (incluida). Por defecto, hoy."},
                "hasta": {"type": "string", "description": "Fecha final YYYY-MM-DD (incluida). Por defecto, desde + 14 días."},
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "ver_mudanza",
        "title": "Ver mudanza",
        "description": "Devuelve todos los datos de un trabajo de MudanzaPro a partir de su id (sale en listar_mudanzas).",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "Id del trabajo."}},
            "required": ["id"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "ver_fotos_mudanza",
        "title": "Ver fotos de una mudanza",
        "description": (
            f"Devuelve las fotos de un trabajo de MudanzaPro como imágenes (máximo {MAX_FOTOS} "
            "por llamada, reducidas para verlas rápido). Úsalo para ver los muebles, "
            "accesos y volumen del trabajo."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Id del trabajo."},
                "max_fotos": {"type": "integer", "minimum": 1, "maximum": MAX_FOTOS, "description": f"Cuántas fotos devolver (1-{MAX_FOTOS}). Por defecto, {MAX_FOTOS}."},
                "desde_foto": {"type": "integer", "minimum": 0, "description": "Índice de la primera foto, para paginar. Por defecto, 0."},
            },
            "required": ["id"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
]


class ToolError(Exception):
    """Error que se devuelve a Claude como resultado con isError=true."""


# ── Utilidades ─────────────────────────────────────────────

def _hoy_madrid():
    """Fecha de hoy en Madrid. En Windows sin el paquete tzdata, aproxima con UTC+1."""
    try:
        return datetime.now(ZoneInfo("Europe/Madrid")).date()
    except ZoneInfoNotFoundError:
        return (datetime.now(timezone.utc) + timedelta(hours=1)).date()


def _parse_fecha(valor, nombre):
    try:
        return datetime.strptime(valor, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise ToolError(f"'{nombre}' debe tener formato YYYY-MM-DD (recibido: {valor!r}).")


def _limpiar(valor):
    """Convierte valores de Firestore (timestamps, etc.) a algo serializable."""
    if isinstance(valor, dict):
        return {k: _limpiar(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_limpiar(v) for v in valor]
    if hasattr(valor, "isoformat"):
        return valor.isoformat()
    return valor


def resumen_trabajo(doc_id, data):
    out = {"id": doc_id}
    for campo in CAMPOS_PUBLICOS:
        if data.get(campo) not in (None, "", []):
            out[campo] = _limpiar(data[campo])
    out["status"] = STATUS_LABEL.get(data.get("status"), "pendiente")
    out["num_fotos"] = len(data.get("photos") or [])
    return out


def _texto(obj):
    return {"type": "text", "text": json.dumps(obj, ensure_ascii=False, indent=1)}


def _reducir_imagen(raw):
    from PIL import Image, ImageOps  # import perezoso: solo se carga al pedir fotos

    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((FOTO_MAX_PX, FOTO_MAX_PX))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


# ── Acceso a datos (separado para poder probarlo sin Firebase) ──

class FirebaseRepo:
    def __init__(self):
        from firebase_admin import firestore, storage
        self._db = firestore.client()
        self._bucket = storage.bucket()

    def trabajos_entre(self, desde, hasta):
        q = (self._db.collection("trabajos")
             .where("date", ">=", desde)
             .where("date", "<=", hasta))
        return [(d.id, d.to_dict() or {}) for d in q.stream()]

    def trabajo(self, doc_id):
        snap = self._db.collection("trabajos").document(doc_id).get()
        return snap.to_dict() if snap.exists else None

    def foto(self, storage_path):
        return self._bucket.blob(storage_path).download_as_bytes()


# ── Herramientas ───────────────────────────────────────────

def tool_listar(repo, args, hoy=None):
    hoy = hoy or _hoy_madrid()
    desde = _parse_fecha(args["desde"], "desde") if args.get("desde") else hoy
    hasta = _parse_fecha(args["hasta"], "hasta") if args.get("hasta") else desde + timedelta(days=14)
    if hasta < desde:
        raise ToolError("'hasta' no puede ser anterior a 'desde'.")
    if (hasta - desde).days > MAX_RANGE_DAYS:
        raise ToolError(f"El rango máximo es de {MAX_RANGE_DAYS} días.")
    filas = [resumen_trabajo(i, d) for i, d in repo.trabajos_entre(desde.isoformat(), hasta.isoformat())]
    filas.sort(key=lambda t: (t.get("date", ""), t.get("startTime", "")))
    return [_texto({"desde": desde.isoformat(), "hasta": hasta.isoformat(), "total": len(filas), "trabajos": filas})]


def tool_ver(repo, args):
    doc_id = (args.get("id") or "").strip()
    if not doc_id:
        raise ToolError("Falta el 'id' del trabajo.")
    data = repo.trabajo(doc_id)
    if data is None:
        raise ToolError(f"No existe ningún trabajo con id {doc_id!r}.")
    return [_texto(resumen_trabajo(doc_id, data))]


def tool_fotos(repo, args):
    doc_id = (args.get("id") or "").strip()
    if not doc_id:
        raise ToolError("Falta el 'id' del trabajo.")
    data = repo.trabajo(doc_id)
    if data is None:
        raise ToolError(f"No existe ningún trabajo con id {doc_id!r}.")
    fotos = data.get("photos") or []
    inicio = max(0, int(args.get("desde_foto") or 0))
    n = min(MAX_FOTOS, max(1, int(args.get("max_fotos") or MAX_FOTOS)))
    tramo = fotos[inicio:inicio + n]
    contenido = [{"type": "text", "text": (
        f"Fotos {inicio + 1}-{inicio + len(tramo)} de {len(fotos)} del trabajo "
        f"{data.get('clientName', doc_id)} ({data.get('date', '')})."
        if tramo else f"El trabajo {doc_id} no tiene fotos en ese tramo (tiene {len(fotos)}).")}]
    fallidas = 0
    for foto in tramo:
        path = foto.get("storagePath") if isinstance(foto, dict) else None
        if not path:
            fallidas += 1
            continue
        try:
            contenido.append({"type": "image", "mimeType": "image/jpeg", "data": _reducir_imagen(repo.foto(path))})
        except Exception:
            fallidas += 1
    if fallidas:
        contenido.append({"type": "text", "text": f"{fallidas} foto(s) no se pudieron cargar."})
    return contenido


HANDLERS = {"listar_mudanzas": tool_listar, "ver_mudanza": tool_ver, "ver_fotos_mudanza": tool_fotos}


# ── JSON-RPC / MCP ─────────────────────────────────────────

def _ok(msg_id, result):
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _err(msg_id, code, message):
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def handle_message(msg, repo_factory):
    """Procesa un mensaje JSON-RPC. Devuelve la respuesta, o None si es una notificación."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
        return _err(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid Request")
    method, msg_id, params = msg["method"], msg.get("id"), msg.get("params") or {}
    if "id" not in msg:  # notificación (p. ej. notifications/initialized)
        return None
    if method == "initialize":
        return _ok(msg_id, {
            "protocolVersion": params.get("protocolVersion") or DEFAULT_PROTOCOL,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": (
                "Datos de solo lectura de MudanzaPro, la app de gestión de trabajos de "
                "Mudanzas del Sur (Huelva). Fechas en formato YYYY-MM-DD, hora de Madrid."
            ),
        })
    if method == "ping":
        return _ok(msg_id, {})
    if method == "tools/list":
        return _ok(msg_id, {"tools": TOOLS})
    if method == "tools/call":
        handler = HANDLERS.get(params.get("name"))
        if handler is None:
            return _err(msg_id, -32602, f"Herramienta desconocida: {params.get('name')}")
        try:
            content = handler(repo_factory(), params.get("arguments") or {})
            return _ok(msg_id, {"content": content, "isError": False})
        except ToolError as e:
            return _ok(msg_id, {"content": [{"type": "text", "text": str(e)}], "isError": True})
        except Exception as e:  # error inesperado: se informa sin tumbar la sesión
            return _ok(msg_id, {"content": [{"type": "text", "text": f"Error interno: {e}"}], "isError": True})
    return _err(msg_id, -32601, f"Método no soportado: {method}")


def _clave_valida(key, path, headers):
    """La clave puede ir en la cabecera Authorization: Bearer <clave>, en
    X-API-Key, o (compatibilidad) como último tramo de la URL."""
    if not key:
        return False
    auth = headers.get("Authorization", "") or ""
    candidatos = [
        auth[7:].strip() if auth.lower().startswith("bearer ") else "",
        (headers.get("X-API-Key") or "").strip(),
        path.strip("/").split("/")[-1] if path else "",
    ]
    return any(c and hmac.compare_digest(c.encode(), key.encode()) for c in candidatos)


def handle_http(method, path, body_bytes, key, repo_factory, headers=None):
    """Lógica HTTP pura. Devuelve (status, body_str|None)."""
    if not _clave_valida(key, path, headers or {}):
        return 404, None  # 404 y no 401: no revelamos que aquí hay algo
    if method == "GET":
        return 405, None  # sin canal SSE: modo sin estado
    if method == "DELETE":
        return 204, None
    if method != "POST":
        return 405, None
    try:
        payload = json.loads(body_bytes or b"null")
    except ValueError:
        return 400, json.dumps(_err(None, -32700, "Parse error"))
    if isinstance(payload, list):
        respuestas = [r for r in (handle_message(m, repo_factory) for m in payload) if r is not None]
        return (200, json.dumps(respuestas, ensure_ascii=False)) if respuestas else (202, None)
    respuesta = handle_message(payload, repo_factory)
    return (200, json.dumps(respuesta, ensure_ascii=False)) if respuesta else (202, None)


_repo = None


def _repo_factory():
    global _repo
    if _repo is None:
        _repo = FirebaseRepo()
    return _repo


@https_fn.on_request(
    region="europe-west1",
    memory=options.MemoryOption.MB_512,
    timeout_sec=60,
    max_instances=3,
    secrets=[MCP_KEY],
)
def mudanzapro_mcp(req: https_fn.Request) -> https_fn.Response:
    status, body = handle_http(req.method, req.path, req.get_data(), MCP_KEY.value, _repo_factory, req.headers)
    return https_fn.Response(body or "", status=status, mimetype="application/json")
