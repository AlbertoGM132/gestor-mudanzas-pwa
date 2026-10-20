"""
Herramientas de analítica para el conector MCP de MudanzaPro (las usa Claude).

Lectura: resumen de todos los portales, comportamiento en la web, recorridos de visitas,
preguntas del chat, redes e informes semanales. Escritura (solo analítica): guardar
métricas de redes (puente con Metricool) y apuntar de dónde vino una solicitud.
"""
import json

import analitica as an

_RANGO = {
    "desde": {"type": "string", "description": "Fecha inicial YYYY-MM-DD (incluida). Por defecto, hace 28 días."},
    "hasta": {"type": "string", "description": "Fecha final YYYY-MM-DD (incluida). Por defecto, hoy."},
}
_LECTURA = {"readOnlyHint": True, "openWorldHint": False}
_ESCRITURA = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}

TOOLS = [
    {"name": "analitica_resumen", "title": "Analítica: resumen de todos los portales",
     "description": ("Resumen del negocio en un periodo, comparado con el periodo anterior de la misma duración: "
                     "visitas a la web por fuente (Instagram, Google, TikTok, Google Ads…), cuántas contactan, "
                     "calculadora (embudo por pasos), chat, páginas y secciones más vistas, scroll, clics; "
                     "solicitudes, trabajos e ingresos de MudanzaPro por origen; métricas de redes; "
                     "flujo entre portales (red → web → contacto → solicitud → trabajo → €) y preguntas del chat."),
     "inputSchema": {"type": "object", "properties": _RANGO, "additionalProperties": False}, "annotations": _LECTURA},
    {"name": "analitica_visitas", "title": "Analítica: recorridos de visitas",
     "description": ("Recorridos paso a paso de visitas concretas a la web (anónimas): de dónde llegan, qué ven, "
                     "qué pulsan, cuánto tiempo y si contactan. Útil para entender el comportamiento. "
                     "Por defecto, últimos 7 días."),
     "inputSchema": {"type": "object", "properties": {
         **_RANGO,
         "fuente": {"type": "string", "description": "Filtra por fuente: " + ", ".join(an.FUENTES)},
         "solo_contactos": {"type": "boolean", "description": "Solo las visitas que contactaron o enviaron solicitud."},
         "limite": {"type": "integer", "description": "Máximo de visitas (1-100, por defecto 30)."}},
         "additionalProperties": False}, "annotations": _LECTURA},
    {"name": "analitica_informes", "title": "Analítica: informes semanales",
     "description": "Los últimos informes semanales de la IA (titular, resumen, puntos por portal, ideas de contenido).",
     "inputSchema": {"type": "object", "properties": {"n": {"type": "integer", "description": "Cuántos (1-8)."}},
                     "additionalProperties": False}, "annotations": _LECTURA},
    {"name": "analitica_enlace", "title": "Analítica: crear enlace con etiqueta",
     "description": ("Crea un enlace a la web con etiquetas UTM para saber qué publicación, bio, historia o anuncio "
                     "trae cada visita. Ej.: fuente instagram, medio bio | historia | reel, campana octubre, contenido nevera."),
     "inputSchema": {"type": "object", "properties": {
         "url": {"type": "string", "description": "Página de la web: / , /calculadora/ , /contacto/ … (por defecto, /)"},
         "fuente": {"type": "string"}, "medio": {"type": "string"},
         "campana": {"type": "string"}, "contenido": {"type": "string"}},
         "required": ["fuente", "medio"], "additionalProperties": False}, "annotations": _LECTURA},
    {"name": "guardar_metricas_redes", "title": "Analítica: guardar métricas de redes",
     "description": ("Guarda en el panel las métricas diarias y por publicación de una red (por ejemplo, las que "
                     "devuelve Metricool). red: instagram | tiktok | facebook | google_perfil | google_ads | meta_ads. "
                     "dias: [{dia:'YYYY-MM-DD', metricas:{seguidores, alcance, visualizaciones, interacciones, "
                     "nuevos_seguidores, clics_web, publicaciones, ...}}]. publicaciones: [{id, fecha, tipo (reel|post|"
                     "historia|video), texto (inicio del texto), url, metricas:{visualizaciones, alcance, me_gusta, "
                     "comentarios, guardados, compartidos, interacciones}}]. Usa siempre estos nombres de métricas en "
                     "español. Es idempotente: volver a guardar el mismo día lo sustituye."),
     "inputSchema": {"type": "object", "properties": {
         "red": {"type": "string"}, "dias": {"type": "array", "items": {"type": "object"}},
         "publicaciones": {"type": "array", "items": {"type": "object"}},
         "fuente_datos": {"type": "string", "description": "De dónde salen (metricool, manual…)."}},
         "required": ["red"], "additionalProperties": False}, "annotations": _ESCRITURA},
    {"name": "asignar_origen_solicitud", "title": "Analítica: apuntar de dónde vino una solicitud",
     "description": ("Apunta en un trabajo de MudanzaPro de dónde vino el cliente, para medir qué portal trae "
                     "trabajos. origen: " + ", ".join(an.ORIGENES_MANUALES) + ". Enséñale a Alberto el cambio antes."),
     "inputSchema": {"type": "object", "properties": {
         "id": {"type": "string", "description": "Id del trabajo (sale en listar_mudanzas / listar_solicitudes)."},
         "origen": {"type": "string", "enum": an.ORIGENES_MANUALES}},
         "required": ["id", "origen"], "additionalProperties": False}, "annotations": _ESCRITURA},
]


class AnaliticaToolError(Exception):
    pass


def _repo(repo):
    if hasattr(repo, "sesiones"):
        return repo
    return an.FirebaseAnaliticaRepo(getattr(repo, "_db", None))


def _texto(obj):
    return {"type": "text", "text": json.dumps(obj, ensure_ascii=False, default=str)}


def _envolver(fn):
    def handler(repo, args):
        try:
            return [_texto(fn(_repo(repo), args or {}))]
        except ValueError as e:
            raise AnaliticaToolError(str(e))
    return handler


def _resumen(r, a):
    return an.compacto(an.resumen(r, a.get("desde"), a.get("hasta")))


def _informes(r, a):
    n = max(1, min(int(a.get("n") or 2), 8))
    return {"informes": [{k: v for k, v in i.items()} for i in r.informes(n)]}


def _asignar(r, a):
    if a.get("origen") not in an.ORIGENES_MANUALES:
        raise ValueError("Origen no válido.")
    r.asignar_origen(str(a.get("id") or ""), a["origen"], "Claude")
    return {"ok": True, "id": a.get("id"), "origen": a["origen"]}


HANDLERS = {
    "analitica_resumen": _envolver(_resumen),
    "analitica_visitas": _envolver(lambda r, a: an.sesiones_detalle(
        r, a.get("desde"), a.get("hasta"), a.get("fuente") or None, bool(a.get("solo_contactos")), a.get("limite") or 30)),
    "analitica_informes": _envolver(_informes),
    "analitica_enlace": _envolver(lambda r, a: {"url": an.enlace_utm(a.get("url") or "/", a.get("fuente"), a.get("medio"),
                                                                     a.get("campana"), a.get("contenido"))}),
    "guardar_metricas_redes": _envolver(lambda r, a: an.guardar_redes(a, r)),
    "asignar_origen_solicitud": _envolver(_asignar),
}
