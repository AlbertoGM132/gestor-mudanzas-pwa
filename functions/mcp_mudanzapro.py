"""
Conector MCP de MudanzaPro para Claude (lectura + escritura limitada a solicitudes).

Expone los trabajos de la colección 'trabajos' y sus fotos como herramientas
MCP sobre HTTP (transporte "Streamable HTTP", modo sin estado).

URL del conector (la que se pega en Claude → Ajustes → Conectores):
  https://europe-west1-<PROYECTO>.cloudfunctions.net/mudanzapro_mcp
con la cabecera de solicitud  Authorization: Bearer <MCP_KEY>
(también se acepta X-API-Key: <MCP_KEY>, o la clave al final de la URL).

La clave MCP_KEY es un secreto de Firebase:
  firebase functions:secrets:set MCP_KEY
Cualquiera que tenga la clave puede leer los trabajos y crear solicitudes, así que no la compartas. Para revocarla, cambia el secreto y vuelve a desplegar.

Por privacidad, el conector NO devuelve teléfono (solo si existe), email ni el resultado
económico de los trabajos cerrados. Escribe solo solicitudes y presupuestos (ver mcp_escritura.py).
"""
import base64
import hmac
import io
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from firebase_functions import https_fn, options
from firebase_functions.params import SecretParam

import mcp_escritura as esc

MCP_KEY = SecretParam("MCP_KEY")

SERVER_INFO = {"name": "mudanzapro", "version": "1.0.0"}
DEFAULT_PROTOCOL = "2025-06-18"
MAX_RANGE_DAYS = 92
MAX_FOTOS = 8
FOTO_MAX_PX = 1024

# Campos del trabajo que se exponen (nada de teléfono, email ni dinero).
CAMPOS_PUBLICOS = [
    "date", "days", "startTime", "endTime", "status", "clientName", "location", "services",
    "originAddress", "originFloor", "originElevator",
    "destinAddress", "destinFloor", "destinElevator",
    "vehicles", "crew", "vehicle", "team", "materials", "notes",
    "stage", "originAccess", "destinAccess", "price",
    "desiredDate", "desiredWhen", "source", "inventory", "webEstimate",
]
VEHICULOS = {"crafter": "Furgoneta VW Crafter", "iveco": "Camión Iveco Daily 20 m³"}
MAX_DIAS = 31

STATUS_LABEL = {"completado": "completado", "en_curso": "en curso"}

TOOLS = [
    {
        "name": "listar_mudanzas",
        "title": "Listar mudanzas",
        "description": (
            "Lista los trabajos de MudanzaPro (mudanzas, portes, montajes) que caen entre dos "
            "fechas, ordenados por fecha y hora; incluye los de varios días que empezaron antes "
            "(date = primer día, days = nº de días, ultimo_dia). Devuelve cliente, población, "
            "servicios, horario, estado, origen y destino (piso y ascensor: true/false; si falta, "
            "no se sabe), vehículos, equipo (crew), materiales, notas, cuántas fotos tiene, si hay "
            "teléfono y 'faltan' (datos importantes sin apuntar). Por defecto, de hoy a 14 días."
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


TOOLS += esc.TOOLS


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


def _dias(data):
    try:
        return min(MAX_DIAS, max(1, int(data.get("days") or 1)))
    except (TypeError, ValueError):
        return 1


def _tiene_telefono(data):
    digitos = "".join(ch for ch in str(data.get("phone") or "") if ch.isdigit())
    return len(digitos) >= 9


def faltan(data):
    """Datos importantes sin apuntar (misma regla que la app)."""
    if data.get("status") == "completado":
        return []
    f = []
    servicios = data.get("services") or []
    if not _tiene_telefono(data):
        f.append("teléfono")
    if not data.get("originAddress") and not data.get("location"):
        f.append("origen")
    if not data.get("destinAddress") and any(s in ("Mudanza completa", "Porte") for s in servicios):
        f.append("destino")
    if not data.get("price"):
        f.append("precio")
    if not data.get("vehicles") and not data.get("vehicle"):
        f.append("vehículo")
    if not data.get("crew") and not data.get("team"):
        f.append("equipo")
    return f


def resumen_trabajo(doc_id, data):
    out = {"id": doc_id}
    for campo in CAMPOS_PUBLICOS:
        if data.get(campo) not in (None, "", []):
            out[campo] = _limpiar(data[campo])
    # Trabajos antiguos (sin "days"): el ascensor venía desmarcado por defecto, así que es desconocido
    for k in ("originElevator", "destinElevator"):
        if "days" not in data and data.get(k) is False:
            out.pop(k, None)
    if isinstance(out.get("vehicles"), list):
        out["vehicles"] = [f"{VEHICULOS.get(v.get('type'), v.get('type'))} ({v.get('plan')} km/día)"
                           for v in out["vehicles"] if isinstance(v, dict)]
    n = _dias(data)
    out["days"] = n
    if n > 1 and data.get("date"):
        inicio = datetime.strptime(data["date"], "%Y-%m-%d").date()
        out["ultimo_dia"] = (inicio + timedelta(days=n - 1)).isoformat()
    out["status"] = STATUS_LABEL.get(data.get("status"), "pendiente")
    if out["status"] == "completado":
        out.pop("price", None)          # lo económico de trabajos cerrados no se expone
    est = data.get("estimate") or {}
    if isinstance(est.get("result"), dict):
        out["presupuesto_calculado"] = {k: est["result"].get(k) for k in ("cost", "price")}
    prop = data.get("proposal") or {}
    if isinstance(prop, dict) and prop.get("price") is not None:
        pe, pr = prop.get("estimate") or {}, prop.get("result") or {}
        out["propuesta_claude"] = {
            "precio": prop.get("price"), "fecha": prop.get("at"), "confianza": prop.get("confidence"),
            "por": prop.get("by") or "Claude",
            "supuestos": prop.get("notes"), "m3": pe.get("m3") or None,
            "vehiculos": [f"{VEHICULOS.get(v.get('type'), v.get('type'))} ({v.get('plan')} km/día, {v.get('km')} km)"
                          for v in pe.get("vehicles") or [] if isinstance(v, dict)],
            "horas": pe.get("hours"), "trabajadores": pe.get("workers"), "socios": pe.get("partners"),
            "coste": pr.get("cost"), "gasoil": pr.get("fuel")}
    # Lo que Alberto acabó poniendo (para comparar con la propuesta y afinar)
    if "presupuesto_calculado" in out and est.get("hours") is not None:
        out["presupuesto_calculado"].update({
            "m3": est.get("m3") or None, "horas": est.get("hours"),
            "trabajadores": est.get("workers"), "socios": est.get("partners"),
            "vehiculos": [f"{VEHICULOS.get(v.get('type'), v.get('type'))} ({v.get('plan')} km/día, {v.get('km')} km)"
                          for v in est.get("vehicles") or [] if isinstance(v, dict)]})
    out["etapa"] = "completado" if out["status"] == "completado" else ("programado" if data.get("date") else (data.get("stage") or "solicitud"))
    out["tiene_telefono"] = _tiene_telefono(data)
    out["faltan"] = faltan(data)
    out["num_fotos"] = len(data.get("photos") or [])
    return out


def _texto(obj):
    # default: fechas de Firestore (y cualquier otro tipo raro) como texto, para que nunca falle
    return {"type": "text", "text": json.dumps(obj, ensure_ascii=False, indent=1,
                                               default=lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o))}


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

    # ── escritura (solo solicitudes y presupuestos) ──
    def tarifas(self):
        snap = self._db.collection("config").document("tarifas").get()
        return snap.to_dict() if snap.exists else {}

    def solicitudes(self, etapas):
        q = self._db.collection("trabajos").where("stage", "in", list(etapas))
        return [(d.id, d.to_dict() or {}) for d in q.stream()]

    def crear(self, data):
        ref = self._db.collection("trabajos").document()
        ref.set(data)
        return ref.id

    def actualizar(self, doc_id, data):
        self._db.collection("trabajos").document(doc_id).set(data, merge=True)

    def ahora(self):
        from firebase_admin import firestore
        return firestore.SERVER_TIMESTAMP


# ── Herramientas ───────────────────────────────────────────

def tool_listar(repo, args, hoy=None):
    hoy = hoy or _hoy_madrid()
    desde = _parse_fecha(args["desde"], "desde") if args.get("desde") else hoy
    hasta = _parse_fecha(args["hasta"], "hasta") if args.get("hasta") else desde + timedelta(days=14)
    if hasta < desde:
        raise ToolError("'hasta' no puede ser anterior a 'desde'.")
    if (hasta - desde).days > MAX_RANGE_DAYS:
        raise ToolError(f"El rango máximo es de {MAX_RANGE_DAYS} días.")
    # Se buscan también los que empezaron antes y siguen en curso (trabajos de varios días)
    candidatos = repo.trabajos_entre((desde - timedelta(days=MAX_DIAS - 1)).isoformat(), hasta.isoformat())
    filas = []
    for i, d in candidatos:
        try:
            inicio = datetime.strptime(d.get("date", ""), "%Y-%m-%d").date()
        except ValueError:
            continue
        if inicio + timedelta(days=_dias(d) - 1) >= desde:
            filas.append(resumen_trabajo(i, d))
    # Vehículo y equipo se comparten entre los trabajos del mismo día: no se avisa si otro ya los tiene
    for campo, claves in (("vehículo", ("vehicles", "vehicle")), ("equipo", ("crew", "team"))):
        dias_con = {t.get("date") for t in filas if any(t.get(k) for k in claves)}
        for t in filas:
            if campo in t["faltan"] and t.get("date") in dias_con:
                t["faltan"].remove(campo)
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


def _dias_desde(ts):
    if not ts:
        return None
    try:
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - ts).days)
    except Exception:
        return None


def _escritura(fn, con_hora=False, lectura=False):
    def handler(repo, args):
        try:
            if lectura:
                out = fn(repo, args)
            elif con_hora:
                out = fn(repo, args, repo.ahora())
            else:
                out = fn(repo, args)
        except esc.WriteError as e:
            raise ToolError(str(e))
        return [_texto(out)]
    return handler


HANDLERS = {
    "listar_mudanzas": tool_listar, "ver_mudanza": tool_ver, "ver_fotos_mudanza": tool_fotos,
    "leer_tarifas": _escritura(esc.tool_leer_tarifas, lectura=True),
    "calcular_presupuesto": _escritura(esc.tool_calcular, lectura=True),
    "listar_solicitudes": _escritura(lambda r, a: esc.tool_listar_solicitudes(r, a, resumen_trabajo, _dias_desde), lectura=True),
    "crear_solicitud": _escritura(esc.tool_crear, con_hora=True),
    "actualizar_solicitud": _escritura(esc.tool_actualizar, con_hora=True),
    "guardar_presupuesto": _escritura(esc.tool_guardar_presupuesto, con_hora=True),
    "proponer_presupuesto": _escritura(esc.tool_proponer, con_hora=True),
}


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
                "MudanzaPro, la app de gestión de trabajos de Mudanzas del Sur (Huelva). "
                "Lectura de trabajos, fotos y solicitudes; escritura limitada a crear/editar "
                "solicitudes y presupuestos y programar fechas (nunca borra ni cierra trabajos). "
                "Antes de crear o modificar algo, enséñale a Alberto lo que vas a guardar y espera su OK. "
                "Precios sin IVA. Fechas YYYY-MM-DD, hora de Madrid."
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
