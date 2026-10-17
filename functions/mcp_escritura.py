"""
Herramientas de ESCRITURA del conector MCP de MudanzaPro.

Solo permiten crear y editar solicitudes (trabajos sin fecha) y presupuestos, y
programar la fecha. No borran nada, no cierran trabajos y no tocan Finanzas.
El cálculo del presupuesto replica `computeEstimate` de public/app.js.
"""
import math
import re
from datetime import datetime

DEFAULT_TARIFAS = {
    "workerHour": 10, "partnerHour": 22, "businessPct": 10, "roundTo": 5, "extraKm": 0.22,
    "rent_furgoneta_200": 73, "rent_furgoneta_400": 88, "rent_camion_200": 133, "rent_camion_400": 150,
    "fuelPrice": 2, "consumo_crafter": 10, "consumo_iveco": 14,   # €/L y L/100 km
}
VEHICLE_KIND = {"crafter": "furgoneta", "iveco": "camion"}
REUSABLE = {"Mantas de protección", "Fajas de carga", "Traspaleta", "Escalera", "Carretilla"}
CONSUMIBLES = ["Cajas pequeñas", "Cajas grandes", "Papel burbuja", "Papel de embalaje",
               "Cinta adhesiva", "Plástico film", "Esquineros"]
SERVICIOS = ["Mudanza completa", "Porte", "Desmontaje y montaje", "Embalaje", "Vajilla / frágil", "Otro"]
ETAPAS = ["solicitud", "presupuestado", "aceptado", "perdido"]
STAGE_AT = {"presupuestado": "quotedAt", "aceptado": "acceptedAt", "programado": "scheduledAt", "perdido": "lostAt"}
PARKING = {"puerta": "puerta", "30": "30", "100": "100", "mas": "mas"}


class WriteError(Exception):
    pass


def _r2(x):
    return round(x + 1e-9, 2)


def gasoil_auto(vehicles, t):
    """Litros y € de gasoil: km de cada vehículo × su consumo (L/100 km) × precio del litro."""
    litros = sum(float(v.get("km") or 0) * float(t.get(f"consumo_{v.get('type')}", 0)) / 100 for v in vehicles or [])
    return round(litros + 1e-9, 1), _r2(litros * float(t.get("fuelPrice", 0)))


def _gasoil_manual(x):
    """Importe puesto a mano, o None si está vacío (entonces se usa el automático)."""
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def calcular(est, t):
    """Mismo cálculo que la app: coste real + % para el negocio, redondeado hacia arriba."""
    rent = extra = 0.0
    for v in est.get("vehicles") or []:
        kind = VEHICLE_KIND.get(v.get("type"), "furgoneta")
        plan = int(v.get("plan") or 200)
        dias = max(1, int(v.get("days") or 1))
        rent += float(t.get(f"rent_{kind}_{plan}", 0)) * dias
        extra += max(0.0, float(v.get("km") or 0) - plan * dias) * float(t.get("extraKm", 0))
    horas = float(est.get("hours") or 0)
    labor = horas * float(est.get("workers") or 0) * float(t.get("workerHour", 0))
    socios = horas * float(est.get("partners") or 0) * float(t.get("partnerHour", 0))
    material = sum(float(q or 0) * float(t.get(m, 0)) for m, q in (est.get("matQty") or {}).items() if m not in REUSABLE)
    litros, fuel_auto = gasoil_auto(est.get("vehicles"), t)
    manual = _gasoil_manual(est.get("fuel"))
    fuel = _r2(fuel_auto if manual is None else manual)
    extras = float(est.get("extras") or 0)
    coste = _r2(rent + extra + labor + socios + material + fuel + extras)
    negocio = _r2(coste * float(t.get("businessPct", 0)) / 100)
    paso = float(t.get("roundTo") or 0)
    bruto = coste + negocio
    precio = math.ceil(round(bruto / paso, 6)) * paso if paso > 0 else _r2(bruto)
    precio = int(precio) if float(precio).is_integer() else _r2(precio)
    return {"rent": _r2(rent), "extraKm": _r2(extra), "labor": _r2(labor), "partners": _r2(socios),
            "materials": _r2(material), "fuel": fuel, "fuelAuto": fuel_auto, "fuelLiters": litros,
            "fuelManual": manual is not None, "extras": extras, "cost": coste,
            "business": negocio, "price": precio, "businessReal": _r2(precio - coste)}


# ── Conversión de argumentos (español, para Claude) → campos de la app ──

def _estimacion(a):
    vehs = []
    for v in a.get("vehiculos") or []:
        tipo = v.get("tipo")
        if tipo not in VEHICLE_KIND:
            raise WriteError("vehiculos[].tipo debe ser 'crafter' (furgoneta) o 'iveco' (camión 20 m³).")
        plan = int(v.get("km_plan") or 200)
        if plan not in (200, 400):
            raise WriteError("vehiculos[].km_plan debe ser 200 o 400.")
        vehs.append({"type": tipo, "plan": plan, "days": max(1, int(v.get("dias") or 1)), "km": float(v.get("km") or 0)})
    mat = {}
    for m, q in (a.get("material") or {}).items():
        if m not in CONSUMIBLES:
            raise WriteError(f"Material desconocido: {m!r}. Usa: {', '.join(CONSUMIBLES)}.")
        mat[m] = float(q or 0)
    return {"vehicles": vehs, "hours": float(a.get("horas") or 0), "workers": int(a.get("trabajadores") or 0),
            "partners": int(a.get("socios") or 0), "matQty": mat,
            "fuel": _gasoil_manual(a.get("gasoil")), "extras": float(a.get("otros") or 0),
            "m3": float(a.get("volumen_m3") or 0) or ""}


def _acceso(d):
    if not d:
        return None
    a = {}
    if d.get("aparcamiento") is not None:
        if d["aparcamiento"] not in PARKING:
            raise WriteError("aparcamiento debe ser 'puerta', '30' (<30 m), '100' (30-100 m) o 'mas' (>100 m).")
        a["parking"] = d["aparcamiento"]
    if d.get("tramos_escalera") is not None:
        a["steps"] = max(0, min(3, int(d["tramos_escalera"])))
    for src, dst in (("ascensor_pequeno", "smallElevator"), ("calle_estrecha", "narrowStreet"), ("permiso_carga", "permit")):
        if d.get(src) is not None:
            a[dst] = bool(d[src])
    return a


def _campos_lado(prefijo, d, out):
    if not d:
        return
    if d.get("direccion") is not None:
        out[f"{prefijo}Address"] = str(d["direccion"]).strip()
    if d.get("piso") is not None:
        out[f"{prefijo}Floor"] = str(d["piso"]).strip()
    if "ascensor" in d:
        out[f"{prefijo}Elevator"] = d["ascensor"] if d["ascensor"] in (True, False) else None
    acc = _acceso(d)
    if acc:
        out[f"{prefijo}Access"] = acc


def _campos(a):
    out = {}
    for src, dst in (("cliente", "clientName"), ("telefono", "phone"), ("poblacion", "location"), ("notas", "notes"), ("email", "email")):
        if a.get(src) is not None:
            out[dst] = str(a[src]).strip()
    if a.get("servicios") is not None:
        malos = [s for s in a["servicios"] if s not in SERVICIOS]
        if malos:
            raise WriteError(f"Servicios desconocidos: {malos}. Usa: {', '.join(SERVICIOS)}.")
        out["services"] = list(a["servicios"])
    _campos_lado("origin", a.get("origen"), out)
    _campos_lado("destin", a.get("destino"), out)
    if a.get("precio") is not None:
        out["price"] = str(a["precio"])
    return out


# ── Herramientas ──

LADO = {
    "type": "object",
    "properties": {
        "direccion": {"type": "string"},
        "piso": {"type": "string", "description": "Piso/puerta o tipo: '3º B', 'bajo', 'chalet'…"},
        "ascensor": {"type": ["boolean", "null"], "description": "true/false; null si no se sabe."},
        "aparcamiento": {"type": "string", "enum": list(PARKING), "description": "Dónde para el camión: puerta, 30 (<30 m), 100 (30-100 m), mas (>100 m)."},
        "tramos_escalera": {"type": "integer", "minimum": 0, "maximum": 3, "description": "Tramos de escalera hasta el portal (3 = 3 o más)."},
        "ascensor_pequeno": {"type": "boolean"},
        "calle_estrecha": {"type": "boolean"},
        "permiso_carga": {"type": "boolean"},
    },
    "additionalProperties": False,
}
ESTIMACION = {
    "vehiculos": {"type": "array", "items": {"type": "object", "properties": {
        "tipo": {"type": "string", "enum": ["crafter", "iveco"]},
        "km_plan": {"type": "integer", "enum": [200, 400]},
        "dias": {"type": "integer", "minimum": 1},
        "km": {"type": "number", "description": "Km totales estimados (ida y vuelta, todos los días). Sirven para el gasoil y los km extra."}}, "required": ["tipo"]}},
    "horas": {"type": "number", "description": "Horas estimadas de trabajo (incluido viaje) para todo el equipo."},
    "trabajadores": {"type": "integer", "description": "Nº de trabajadores (no socios) a €/h."},
    "socios": {"type": "integer", "minimum": 0, "maximum": 2, "description": "Cuántos socios van (Alberto, Cristian)."},
    "material": {"type": "object", "description": f"Unidades de material que se gasta. Claves: {', '.join(CONSUMIBLES)}."},
    "gasoil": {"type": "number", "description": "Solo si se quiere fijar a mano. Si se omite, se calcula con los km de cada vehículo × su consumo × precio del gasoil (tarifas)."},
    "otros": {"type": "number", "description": "Peajes, parking, etc."},
    "volumen_m3": {"type": "number", "description": "Volumen aproximado en m³ (sale en el mensaje de WhatsApp del presupuesto)."},
}
DATOS = {
    "cliente": {"type": "string"}, "telefono": {"type": "string"}, "poblacion": {"type": "string"},
    "servicios": {"type": "array", "items": {"type": "string", "enum": SERVICIOS}},
    "origen": LADO, "destino": LADO,
    "notas": {"type": "string", "description": "Inventario, muebles a desmontar, detalles útiles."},
}

TOOLS = [
    {"name": "leer_tarifas", "title": "Leer tarifas",
     "description": "Devuelve las tarifas actuales de la app (alquiler de vehículos por día y plan de km, €/km extra, €/h trabajador, €/h socio, % de beneficio del negocio, redondeo, precio del gasoil (€/L), consumo de cada vehículo (L/100 km) y precio de cada material).",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "calcular_presupuesto", "title": "Calcular presupuesto",
     "description": "Calcula un presupuesto con las tarifas de la app SIN guardar nada: coste (vehículos, km extra, trabajadores, socios, material, gasoil, otros) + % del negocio, redondeado. Úsalo para proponer el precio a Alberto antes de guardarlo.",
     "inputSchema": {"type": "object", "properties": ESTIMACION, "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "listar_solicitudes", "title": "Listar solicitudes",
     "description": "Lista las solicitudes sin fecha del embudo (solicitud, presupuestado, aceptado), con días en esa etapa, precio y lo que falta. Opcional: filtrar por etapa.",
     "inputSchema": {"type": "object", "properties": {"etapa": {"type": "string", "enum": ["solicitud", "presupuestado", "aceptado", "perdido"]}}, "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "crear_solicitud", "title": "Crear solicitud",
     "description": "Crea en MudanzaPro una solicitud nueva (sin fecha) con los datos del cliente, servicios, origen/destino con accesos y notas. Si se pasa 'presupuesto', lo calcula y la deja como 'presupuestado'. Pide confirmación a Alberto antes de crear.",
     "inputSchema": {"type": "object", "properties": {**DATOS, "presupuesto": {"type": "object", "properties": ESTIMACION, "additionalProperties": False}},
                     "required": ["cliente"], "additionalProperties": False},
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}},
    {"name": "actualizar_solicitud", "title": "Actualizar solicitud",
     "description": "Completa o corrige datos de un trabajo NO completado (cliente, teléfono, población, servicios, origen/destino, notas) y opcionalmente cambia la etapa (solicitud, presupuestado, aceptado, perdido) o lo programa con 'fecha' (YYYY-MM-DD) y 'dias'. No borra nada.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, **DATOS,
                     "etapa": {"type": "string", "enum": ETAPAS},
                     "fecha": {"type": "string", "description": "YYYY-MM-DD: programa el trabajo en el calendario."},
                     "dias": {"type": "integer", "minimum": 1, "maximum": 31},
                     "hora_inicio": {"type": "string", "description": "HH:MM"}},
                     "required": ["id"], "additionalProperties": False},
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}},
    {"name": "proponer_presupuesto", "title": "Proponer presupuesto",
     "description": "Deja en la solicitud una PROPUESTA de presupuesto para que Alberto la revise en la app (botones «Usar propuesta» / «Ajustar»). No cambia el precio ni la etapa ni avisa al cliente. Usa 'supuestos' para explicar en 2-5 líneas qué has estimado (m³, km, horas, personas) y qué falta por confirmar.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, **ESTIMACION,
                     "supuestos": {"type": "string", "description": "Qué has supuesto y por qué (se le enseña a Alberto)."},
                     "confianza": {"type": "string", "enum": ["alta", "media", "baja"], "description": "Alta: hay fotos/inventario suficientes. Baja: faltan datos clave."}},
                     "required": ["id", "supuestos"], "additionalProperties": False},
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}},
    {"name": "guardar_presupuesto", "title": "Guardar presupuesto",
     "description": "Calcula y guarda el presupuesto de un trabajo existente (no completado): guarda el desglose y el precio, y si no tiene fecha pasa a 'presupuestado'. 'precio_final' permite fijar un precio distinto al calculado.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, **ESTIMACION, "precio_final": {"type": "number"}},
                     "required": ["id"], "additionalProperties": False},
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}},
]


def _tarifas(repo):
    return {**DEFAULT_TARIFAS, **(repo.tarifas() or {})}


def _get_editable(repo, doc_id):
    doc_id = (doc_id or "").strip()
    data = repo.trabajo(doc_id) if doc_id else None
    if data is None:
        raise WriteError(f"No existe ningún trabajo con id {doc_id!r}.")
    if data.get("status") == "completado":
        raise WriteError("Ese trabajo ya está completado y cerrado: no se puede modificar desde aquí.")
    return doc_id, data


def tool_leer_tarifas(repo, args):
    # Sin metadatos de guardado (updatedAt…) ni la plantilla larga del mensaje
    return {k: v for k, v in _tarifas(repo).items() if k not in ("updatedAt", "createdAt", "quoteMsg")}


def tool_calcular(repo, args):
    est = _estimacion(args)
    return {"entrada": est, "resultado": calcular(est, _tarifas(repo))}


def tool_listar_solicitudes(repo, args, resumen, dias_desde):
    etapa = args.get("etapa")
    filas = []
    for doc_id, d in repo.solicitudes([etapa] if etapa else ["solicitud", "presupuestado", "aceptado"]):
        if d.get("date"):
            continue
        r = resumen(doc_id, d)
        st = d.get("stage") or "solicitud"
        r["etapa"] = st
        r["dias_en_etapa"] = dias_desde(d.get(STAGE_AT.get(st, "")) or d.get("updatedAt") or d.get("createdAt"))
        filas.append(r)
    filas.sort(key=lambda r: -(r["dias_en_etapa"] or 0))
    return {"total": len(filas), "solicitudes": filas}


def tool_crear(repo, args, now):
    data = _campos(args)
    if not data.get("clientName"):
        raise WriteError("Falta 'cliente'.")
    data.update({"stage": "solicitud", "date": "", "days": 1, "startTime": "08:00", "status": "pendiente",
                 "photos": [], "crew": [], "vehicles": [], "materials": [],
                 "createdBy": "Claude", "createdAt": now, "updatedBy": "Claude", "updatedAt": now})
    res = None
    if args.get("presupuesto"):
        est = _estimacion(args["presupuesto"])
        res = calcular(est, _tarifas(repo))
        data.update({"estimate": {**est, "result": res, "at": datetime.utcnow().isoformat() + "Z", "by": "Claude"},
                     "price": str(res["price"]), "stage": "presupuestado", "quotedAt": now})
    doc_id = repo.crear(data)
    return {"id": doc_id, "etapa": data["stage"], "presupuesto": res}


def tool_actualizar(repo, args, now):
    doc_id, actual = _get_editable(repo, args.get("id"))
    data = _campos({k: v for k, v in args.items() if k != "precio"})
    if args.get("hora_inicio") is not None:
        if not re.fullmatch(r"\d{2}:\d{2}", args["hora_inicio"]):
            raise WriteError("hora_inicio debe ser HH:MM.")
        data["startTime"] = args["hora_inicio"]
    if args.get("dias") is not None:
        data["days"] = max(1, min(31, int(args["dias"])))
    nueva = None
    if args.get("fecha"):
        try:
            datetime.strptime(args["fecha"], "%Y-%m-%d")
        except ValueError:
            raise WriteError("fecha debe ser YYYY-MM-DD.")
        data["date"] = args["fecha"]
        nueva = "programado"
    elif args.get("etapa"):
        if actual.get("date"):
            raise WriteError("Ese trabajo ya tiene fecha (está programado); la etapa solo se cambia en solicitudes sin fecha.")
        nueva = args["etapa"]
    if nueva:
        data["stage"] = nueva
        if nueva in STAGE_AT and (actual.get("stage") != nueva):
            data[STAGE_AT[nueva]] = now
    if not data:
        raise WriteError("No hay nada que actualizar.")
    data.update({"updatedBy": "Claude", "updatedAt": now})
    repo.actualizar(doc_id, data)
    return {"id": doc_id, "actualizado": sorted(k for k in data if not k.endswith("At") and k != "updatedBy")}


def tool_proponer(repo, args, now):
    doc_id, actual = _get_editable(repo, args.get("id"))
    est = _estimacion(args)
    res = calcular(est, _tarifas(repo))
    confianza = args.get("confianza") if args.get("confianza") in ("alta", "media", "baja") else "media"
    prop = {"estimate": est, "result": res, "price": res["price"], "notes": str(args.get("supuestos") or "").strip()[:1500],
            "confidence": confianza, "at": datetime.utcnow().isoformat() + "Z", "by": "Claude"}
    repo.actualizar(doc_id, {"proposal": prop, "updatedAt": now})
    aviso = "Ya tenía precio; la propuesta queda solo como referencia." if actual.get("price") else None
    return {"id": doc_id, "propuesta": res["price"], "calculado": res, "aviso": aviso}


def tool_guardar_presupuesto(repo, args, now):
    doc_id, actual = _get_editable(repo, args.get("id"))
    est = _estimacion(args)
    res = calcular(est, _tarifas(repo))
    precio = args.get("precio_final")
    precio = res["price"] if precio is None else (int(precio) if float(precio).is_integer() else round(float(precio), 2))
    data = {"estimate": {**est, "result": res, "at": datetime.utcnow().isoformat() + "Z", "by": "Claude"},
            "price": str(precio), "updatedBy": "Claude", "updatedAt": now}
    if not actual.get("date") and (actual.get("stage") or "solicitud") == "solicitud":
        data.update({"stage": "presupuestado", "quotedAt": now})
    repo.actualizar(doc_id, data)
    return {"id": doc_id, "precio": precio, "calculado": res, "etapa": data.get("stage", actual.get("stage") or "programado")}
