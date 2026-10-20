"""
Analítica de Mudanzas del Sur: une la web, las redes y MudanzaPro en un solo sitio.

Qué hace
  1. Recoge lo que pasa en la web (mudanzasdelsur.es) SIN cookies ni datos personales:
     de dónde llega cada visita (Instagram, Google, TikTok…), qué páginas y secciones ve,
     hasta dónde baja, qué botones pulsa (WhatsApp, llamar, calculadora) y en qué paso
     de la calculadora se queda. Cada visita es una «sesión» con un id aleatorio que
     solo vive mientras la pestaña está abierta.
  2. Guarda el origen en cada solicitud que entra por la web, para saber qué portal
     trae clientes de verdad (visita → solicitud → trabajo → €).
  3. Junta las métricas de redes (Instagram, TikTok, Facebook, Google) que llegan
     por el puente de Metricool o a mano.
  4. Calcula resúmenes por periodo, comparados con el periodo anterior, para el
     panel, el informe semanal con IA y las herramientas de Claude.

Colecciones (todas cerradas al navegador; solo las tocan las funciones):
  analitica_sesiones/{sid}      una visita a la web con sus eventos
  analitica_preguntas/{auto}    lo que la gente pregunta al asistente «Sur» (sin teléfonos ni emails)
  redes_metricas/{red_dia}      métricas diarias de cada red
  redes_publicaciones/{red_id}  rendimiento de cada publicación
  analitica_informes/{fecha}    informes semanales de la IA

La lógica no depende de Firebase para poder probarla (ver tests/test_analitica.py).
"""
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import median
from urllib.parse import urlparse

try:
    from zoneinfo import ZoneInfo
    MADRID = ZoneInfo("Europe/Madrid")
except Exception:  # pragma: no cover
    MADRID = timezone(timedelta(hours=1))

# ── Límites y nombres ───────────────────────────────────────

MAX_EVENTOS_SESION = 300
MAX_EVENTOS_LOTE = 50
DIAS_CONSERVAR = 400        # algo más de un año, para comparar con el mismo mes del año pasado
MAX_RANGO_DIAS = 400

EVENTOS = {
    "vista",            # página vista            d: {titulo}
    "seccion",          # sección vista (≥ 40 %)   d: {id}
    "scroll",           # profundidad             d: {pct: 25|50|75|100}
    "clic",             # botón o enlace          d: {que, zona, texto}
    "salida",           # tiempo en la página     d: {seg}
    "calc_paso",        # paso de la calculadora  d: {paso, nombre}
    "calc_fotos",       # fotos analizadas        d: {n, muebles, ok}
    "calc_resultado",   # le salió precio         d: {min, max, m3}
    "calc_error",       # algo falló              d: {paso, motivo}
    "chat_abierto",
    "chat_mensaje",
    "form_inicio",      # empezó a rellenar el formulario de contacto
    "lead",             # envió la calculadora o el contacto  d: {tipo}
}
CLICS = {"whatsapp", "llamar", "email", "calculadora", "instagram", "tiktok", "facebook", "mapa", "otro"}
CONTACTO_DIRECTO = {"whatsapp", "llamar", "email"}

DOMINIOS_PROPIOS = ("mudanzasdelsur.es", "mudanzas-del-sur.web.app", "mudanzas-del-sur.firebaseapp.com",
                    "localhost", "127.0.0.1")

FUENTES = {
    "instagram": "Instagram", "tiktok": "TikTok", "facebook": "Facebook", "meta": "Meta (sin detalle)",
    "google_ads": "Google Ads", "google_perfil": "Perfil de Google", "google": "Google (búsqueda)",
    "buscadores": "Otros buscadores", "whatsapp": "WhatsApp", "email": "Email", "directo": "Directo",
    "otras_webs": "Otras webs", "presupuesto_app": "Formulario /presupuesto",
    "boca_a_boca": "Boca a boca", "repetidor": "Cliente que repite", "telefono": "Llamada",
    "offline": "Flyers, QR y vehículos", "web": "Web (sin detalle)", "sin_apuntar": "Sin apuntar",
}
# Lo que se puede asignar a mano a una solicitud (panel o Claude)
ORIGENES_MANUALES = ["instagram", "tiktok", "facebook", "google_ads", "google_perfil", "google", "whatsapp",
                     "boca_a_boca", "repetidor", "telefono", "offline", "otras_webs", "directo"]
REDES = {"instagram", "tiktok", "facebook", "google_perfil", "google_ads", "meta_ads"}

_UTM_ALIAS = {
    "ig": "instagram", "instagram": "instagram", "insta": "instagram",
    "tt": "tiktok", "tiktok": "tiktok",
    "fb": "facebook", "facebook": "facebook",
    "gbp": "google_perfil", "google_business": "google_perfil", "gmb": "google_perfil", "perfil": "google_perfil",
    "maps": "google_perfil", "google_maps": "google_perfil",
    "wa": "whatsapp", "whatsapp": "whatsapp",
    "email": "email", "correo": "email", "newsletter": "email",
    "google": "google", "bing": "buscadores",
    "flyer": "offline", "qr": "offline", "camion": "offline", "furgoneta": "offline", "tarjeta": "offline",
    "offline": "offline", "cartel": "offline",
}
_MEDIOS_PAGO = {"cpc", "ppc", "paid", "pmax", "ads", "paid_social", "anuncio", "anuncios"}

_BOT = re.compile(r"bot|crawl|spider|slurp|headless|lighthouse|pagespeed|preview|facebookexternalhit|"
                  r"embedly|quora link|whatsapp/|telegrambot|python-requests|curl/|wget|monitor|uptime", re.I)
_MOVIL = re.compile(r"mobi|android|iphone|ipod|windows phone", re.I)
_TABLET = re.compile(r"ipad|tablet", re.I)
_SID = re.compile(r"^[a-z0-9]{10,32}$")
_CLAVE = re.compile(r"^[a-z_]{1,20}$")
_TEL = re.compile(r"\+?\d(?:[\s.-]?\d){6,}")
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")


# ── Utilidades ─────────────────────────────────────────────

def hoy_madrid(ahora=None):
    return (ahora or datetime.now(timezone.utc)).astimezone(MADRID).date()


def dia_madrid(ts):
    """'YYYY-MM-DD' (hora de Madrid) de un datetime, un ISO o un Timestamp de Firestore."""
    if ts is None:
        return ""
    if isinstance(ts, str):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", ts):
            return ts
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return ""
    if isinstance(ts, date) and not isinstance(ts, datetime):
        return ts.isoformat()
    if not isinstance(ts, datetime):
        return ""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(MADRID).date().isoformat()


def rango(desde=None, hasta=None, por_defecto=28, ahora=None):
    """Valida un rango de fechas ('YYYY-MM-DD'). Por defecto, los últimos `por_defecto` días."""
    def parse(v, nombre):
        try:
            return datetime.strptime(str(v), "%Y-%m-%d").date()
        except ValueError:
            raise ValueError(f"'{nombre}' debe ser una fecha YYYY-MM-DD.")
    h = parse(hasta, "hasta") if hasta else hoy_madrid(ahora)
    d = parse(desde, "desde") if desde else h - timedelta(days=por_defecto - 1)
    if d > h:
        d, h = h, d
    if (h - d).days + 1 > MAX_RANGO_DIAS:
        d = h - timedelta(days=MAX_RANGO_DIAS - 1)
    return d, h


def periodo_anterior(d, h):
    n = (h - d).days + 1
    return d - timedelta(days=n), d - timedelta(days=1)


def _txt(v, n):
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def _num(v):
    try:
        x = float(v)
        return x if x == x and abs(x) < 1e12 else None
    except (TypeError, ValueError):
        return None


def precio(v):
    """'450', '450 €', '1.200,50' o 450 → número (0 si no se entiende)."""
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v or "").replace("€", "").replace(" ", "")
    if not s:
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", s)
    return float(m.group()) if m else 0.0


def host(url):
    try:
        h = (urlparse(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""
    return h[4:] if h.startswith("www.") else h


def es_bot(ua):
    return not ua or bool(_BOT.search(ua))


def dispositivo(ua, ancho=None):
    ua = ua or ""
    if _TABLET.search(ua):
        return "tablet"
    if _MOVIL.search(ua):
        return "movil"
    a = _num(ancho)
    if a and a < 760:
        return "movil"
    return "escritorio"


def app_de(ua):
    """Navegador dentro de una app (Instagram, Facebook, TikTok…): suelen quitar el referer."""
    ua = ua or ""
    if "Instagram" in ua:
        return "instagram"
    if re.search(r"FBAN|FBAV|FB_IAB", ua):
        return "facebook"
    if re.search(r"musical_ly|BytedanceWebview|TikTok", ua, re.I):
        return "tiktok"
    if "WhatsApp" in ua:
        return "whatsapp"
    return ""


def clasificar(ctx, ua=""):
    """De dónde llega una visita → (fuente, detalle). Prioridad: anuncios, UTM, referer, app."""
    ctx = ctx if isinstance(ctx, dict) else {}
    us = _txt(ctx.get("utm_source"), 40).lower()
    um = _txt(ctx.get("utm_medium"), 40).lower()
    clid = _txt(ctx.get("clid"), 12).lower()
    ref = host(ctx.get("ref"))
    app = app_de(ua)

    if clid in ("gclid", "gbraid", "wbraid") or (us in ("google", "googleads", "google_ads", "adwords") and um in _MEDIOS_PAGO):
        return "google_ads", us or clid
    if us:
        f = _UTM_ALIAS.get(us)
        if f == "google" and um in ("gbp", "perfil", "maps", "organic_gbp"):
            f = "google_perfil"
        if f:
            return f, um or us
        return "otras_webs", us
    if ref and not any(ref == p or ref.endswith("." + p) for p in DOMINIOS_PROPIOS):
        if "instagram" in ref:
            return "instagram", ref
        if "facebook" in ref or ref in ("fb.com", "fb.me", "m.me"):
            return "facebook", ref
        if "tiktok" in ref:
            return "tiktok", ref
        if ref in ("wa.me", "web.whatsapp.com") or "whatsapp" in ref:
            return "whatsapp", ref
        if re.match(r"^(.+\.)?google\.[a-z.]+$", ref) or ref == "com.google.android.googlequicksearchbox":
            return "google", ref
        if re.search(r"bing\.|duckduckgo|yahoo\.|ecosia|qwant|yandex|brave", ref):
            return "buscadores", ref
        if re.search(r"mail\.|outlook|gmail", ref):
            return "email", ref
        return "otras_webs", ref
    if app:
        return app, "navegador de la app"
    if clid == "fbclid":
        return "meta", "fbclid"
    if clid == "ttclid":
        return "tiktok", "ttclid"
    return "directo", ""


def limpiar_pregunta(texto):
    """Lo que la gente pregunta al chat, sin teléfonos ni emails."""
    t = _txt(texto, 300)
    t = _EMAIL.sub("[email]", t)
    return _TEL.sub("[teléfono]", t)


def _limpiar_datos(d):
    out = {}
    if not isinstance(d, dict):
        return out
    for k, v in list(d.items())[:8]:
        if not isinstance(k, str) or not _CLAVE.match(k):
            continue
        if isinstance(v, bool):
            out[k] = v
        elif isinstance(v, (int, float)):
            if _num(v) is not None:
                out[k] = round(float(v), 2)
        elif isinstance(v, str):
            out[k] = limpiar_pregunta(v)[:100]
    return out


def limpiar_eventos(lista):
    out = []
    for e in (lista if isinstance(lista, list) else [])[:MAX_EVENTOS_LOTE]:
        if not isinstance(e, dict) or e.get("n") not in EVENTOS:
            continue
        p = _txt(e.get("p"), 120) or "/"
        if not p.startswith("/"):
            p = "/"
        p = p.split("?")[0].split("#")[0] or "/"
        if len(p) > 1 and not p.endswith("/") and "." not in p.rsplit("/", 1)[-1]:
            p += "/"     # la web usa barra final: /calculadora y /calculadora/ son la misma página
        s = _num(e.get("s"))
        out.append({"n": e["n"], "p": p, "s": int(max(0, min(s or 0, 86_400_000))), "d": _limpiar_datos(e.get("d"))})
    return out


# ── Recogida de eventos (POST /evento desde la web) ───────

def ingerir(body, ua, repo, ahora=None):
    """Guarda un lote de eventos de una visita. Nunca falla hacia la web: responde ok."""
    ahora = ahora or datetime.now(timezone.utc)
    if not isinstance(body, dict) or es_bot(ua):
        return {"ok": True}
    sid = _txt(body.get("sid"), 40).lower()
    if not _SID.match(sid):
        return {"ok": True}
    eventos = limpiar_eventos(body.get("ev"))
    if not eventos:
        return {"ok": True}
    ses = repo.sesion(sid)
    if ses is None:
        ctx = body.get("ctx") if isinstance(body.get("ctx"), dict) else {}
        fuente, detalle = clasificar(ctx, ua)
        landing = limpiar_eventos([{"n": "vista", "p": ctx.get("landing") or eventos[0]["p"]}])
        ses = {
            "sid": sid, "dia": dia_madrid(ahora), "inicio": ahora, "fuente": fuente, "detalle": detalle,
            "medio": _txt(ctx.get("utm_medium"), 40).lower(), "campana": _txt(ctx.get("utm_campaign"), 60),
            "contenido": _txt(ctx.get("utm_content"), 60), "termino": _txt(ctx.get("utm_term"), 60),
            "landing": landing[0]["p"] if landing else "/", "disp": dispositivo(ua, ctx.get("ancho")),
            "app": app_de(ua), "eventos": [], "n": 0, "lead": None, "expira": ahora + timedelta(days=DIAS_CONSERVAR),
        }
    n = int(ses.get("n") or 0)
    if n >= MAX_EVENTOS_SESION:
        return {"ok": True}
    nuevos = eventos[:MAX_EVENTOS_SESION - n]
    ses["eventos"] = list(ses.get("eventos") or []) + nuevos
    ses["n"] = n + len(nuevos)
    ses["ultimo"] = ahora
    lead = next((e for e in nuevos if e["n"] == "lead"), None)
    if lead and not ses.get("lead"):
        ses["lead"] = {"tipo": lead["d"].get("tipo") or "web"}
    repo.guardar_sesion(sid, ses)
    return {"ok": True}


def atribucion(body):
    """El origen que la web manda con la calculadora o el contacto → campo 'attribution' del trabajo."""
    a = body.get("atribucion") if isinstance(body, dict) else None
    if not isinstance(a, dict):
        return None
    sid = _txt(a.get("sid"), 40).lower()
    ctx = {k: a.get(k) for k in ("utm_source", "utm_medium", "utm_campaign", "utm_content", "ref", "clid")}
    fuente, detalle = clasificar(ctx, _txt(a.get("ua"), 300))
    return {
        "sid": sid if _SID.match(sid) else "", "fuente": fuente, "detalle": detalle,
        "medio": _txt(a.get("utm_medium"), 40).lower(), "campana": _txt(a.get("utm_campaign"), 60),
        "contenido": _txt(a.get("utm_content"), 60), "landing": limpiar_eventos([{"n": "vista", "p": a.get("landing")}])[0]["p"],
    }


# ── Análisis de la web ──────────────────────────────────────

def _pct(a, b):
    return round(100 * a / b, 1) if b else 0.0


def _duracion(s):
    evs = s.get("eventos") or []
    if not evs:
        return 0
    seg = max(e.get("s", 0) for e in evs) / 1000
    for e in evs:
        if e["n"] == "salida":
            seg = max(seg, (e.get("s", 0) / 1000))
    return round(seg)


def _tiene(s, n, **d):
    return any(e["n"] == n and all(e.get("d", {}).get(k) == v for k, v in d.items()) for e in s.get("eventos") or [])


def _contactos(s):
    """¿La visita contactó? (lead o pulsó WhatsApp / llamar / email)."""
    return bool(s.get("lead")) or any(e["n"] == "clic" and e["d"].get("que") in CONTACTO_DIRECTO for e in s.get("eventos") or [])


def analizar_web(sesiones):
    total = len(sesiones)
    por_fuente = defaultdict(lambda: {"visitas": 0, "contactan": 0, "leads": 0, "calculadora": 0, "movil": 0})
    disp, landing, paginas, salidas, recorridos, clics, zonas = (Counter() for _ in range(7))
    vistas_pag = Counter()                       # visitas que vieron cada página (una vez por visita)
    secciones = defaultdict(Counter)              # pagina -> id -> visitas
    scroll = defaultdict(Counter)                 # pagina -> pct -> visitas que llegaron
    tiempo_pag = defaultdict(list)
    calc_max, calc_err, leads_tipo, campanas = Counter(), Counter(), Counter(), Counter()
    calc_vistas = calc_resultado = chat_ab = chat_msg = rebotes = form_inicio = 0
    duraciones = []
    nombres_paso = {}
    por_dia = defaultdict(lambda: {"visitas": 0, "contactan": 0, "leads": 0})

    for s in sesiones:
        evs = s.get("eventos") or []
        f = s.get("fuente") or "directo"
        pf = por_fuente[f]
        pf["visitas"] += 1
        pf["movil"] += s.get("disp") == "movil"
        disp[s.get("disp") or "escritorio"] += 1
        landing[s.get("landing") or "/"] += 1
        if s.get("campana"):
            campanas[f"{f} · {s['campana']}"] += 1
        vistas = [e["p"] for e in evs if e["n"] == "vista"]
        for p in vistas:
            paginas[p] += 1
        for p in set(vistas):
            vistas_pag[p] += 1
        seq = [p for i, p in enumerate(vistas) if i == 0 or p != vistas[i - 1]]
        if seq:
            salidas[seq[-1]] += 1
            recorridos[" → ".join(seq[:5]) + (" → …" if len(seq) > 5 else "")] += 1
        vistos_sec, vistos_scroll = set(), set()
        seg_pag = {}             # la web manda el tiempo acumulado: nos quedamos con el mayor
        paso_max = 0
        for e in evs:
            n, d, p = e["n"], e.get("d", {}), e["p"]
            if n == "seccion" and d.get("id") and (p, d["id"]) not in vistos_sec:
                vistos_sec.add((p, d["id"]))
                secciones[p][d["id"]] += 1
            elif n == "scroll" and d.get("pct") and (p, d["pct"]) not in vistos_scroll:
                vistos_scroll.add((p, d["pct"]))
                scroll[p][int(d["pct"])] += 1
            elif n == "clic":
                clics[d.get("que") or "otro"] += 1
                zonas[f"{d.get('que') or 'otro'} · {d.get('zona') or p}"] += 1
            elif n == "salida" and _num(d.get("seg")) is not None:
                seg_pag[p] = max(seg_pag.get(p, 0), min(float(d["seg"]), 3600))
            elif n == "calc_paso":
                paso = int(_num(d.get("paso")) or 0)
                paso_max = max(paso_max, paso)
                if d.get("nombre"):
                    nombres_paso[paso] = d["nombre"]
            elif n == "calc_error":
                calc_err[d.get("motivo") or "error"] += 1
            elif n == "chat_mensaje":
                chat_msg += 1
        for p_, sg in seg_pag.items():
            tiempo_pag[p_].append(sg)
        if "/calculadora/" in vistas or paso_max:
            calc_vistas += 1
            pf["calculadora"] += 1
            calc_max[paso_max or 1] += 1
        if any(e["n"] == "calc_resultado" for e in evs):
            calc_resultado += 1
        if any(e["n"] == "chat_abierto" for e in evs):
            chat_ab += 1
        if any(e["n"] == "form_inicio" for e in evs):
            form_inicio += 1
        if s.get("lead"):
            pf["leads"] += 1
            leads_tipo[s["lead"].get("tipo") or "web"] += 1
        if _contactos(s):
            pf["contactan"] += 1
        pd_ = por_dia[s.get("dia") or ""]
        pd_["visitas"] += 1
        pd_["contactan"] += _contactos(s)
        pd_["leads"] += bool(s.get("lead"))
        dur = _duracion(s)
        duraciones.append(dur)
        interactuo = any(e["n"] in ("clic", "calc_paso", "chat_abierto", "lead", "form_inicio") for e in evs)
        if len(set(vistas)) <= 1 and not interactuo and dur < 15:
            rebotes += 1

    # Embudo de la calculadora: cuántas visitas llegan AL MENOS a cada paso
    pasos = sorted(set(calc_max) | set(nombres_paso))
    embudo_calc = []
    for paso in pasos:
        llegan = sum(v for k, v in calc_max.items() if k >= paso)
        embudo_calc.append({"paso": paso, "nombre": nombres_paso.get(paso, f"Paso {paso}"), "visitas": llegan,
                            "pct": _pct(llegan, calc_vistas)})
    calc_leads = leads_tipo.get("calculadora", 0)
    fuentes = sorted(({"fuente": f, "nombre": FUENTES.get(f, f), **v,
                       "pct_contactan": _pct(v["contactan"], v["visitas"]), "pct_leads": _pct(v["leads"], v["visitas"])}
                      for f, v in por_fuente.items()), key=lambda x: -x["visitas"])
    secciones_out = {p: [{"id": i, "visitas": n, "pct": _pct(n, vistas_pag[p])} for i, n in c.most_common()]
                     for p, c in secciones.items()}
    scroll_out = {p: {str(k): _pct(c[k], vistas_pag[p]) for k in (25, 50, 75, 100)} for p, c in scroll.items()}
    return {
        "visitas": total,
        "paginas_vistas": sum(paginas.values()),
        "contactan": sum(v["contactan"] for v in por_fuente.values()),
        "leads": sum(leads_tipo.values()),
        "pct_contactan": _pct(sum(v["contactan"] for v in por_fuente.values()), total),
        "pct_rebote": _pct(rebotes, total),
        "duracion_mediana_seg": round(median(duraciones)) if duraciones else 0,
        "dispositivos": {k: _pct(v, total) for k, v in disp.most_common()},
        "fuentes": fuentes,
        "campanas": [{"campana": k, "visitas": v} for k, v in campanas.most_common(15)],
        "paginas": [{"pagina": p, "vistas": n, "visitas": vistas_pag[p],
                     "seg_mediana": round(median(tiempo_pag[p])) if tiempo_pag[p] else None,
                     "salidas": salidas[p]} for p, n in paginas.most_common(20)],
        "entradas": [{"pagina": p, "visitas": n} for p, n in landing.most_common(10)],
        "recorridos": [{"recorrido": r, "visitas": n} for r, n in recorridos.most_common(12)],
        "secciones": secciones_out,
        "scroll": scroll_out,
        "clics": dict(clics.most_common()),
        "clics_zona": [{"clic": k, "veces": v} for k, v in zonas.most_common(20)],
        "calculadora": {"visitas": calc_vistas, "con_precio": calc_resultado, "enviadas": calc_leads,
                        "pct_terminan": _pct(calc_leads, calc_vistas), "embudo": embudo_calc,
                        "errores": dict(calc_err.most_common(8))},
        "chat": {"visitas_que_lo_abren": chat_ab, "mensajes": chat_msg, "pct_abren": _pct(chat_ab, total)},
        "formulario": {"empezados": form_inicio, "enviados": leads_tipo.get("contacto", 0)},
        "leads_tipo": dict(leads_tipo),
        "por_dia": [{"dia": k, **v} for k, v in sorted(por_dia.items()) if k],
    }


# ── Análisis del negocio (MudanzaPro) ───────────────────────

def origen_trabajo(t):
    a = t.get("attribution") if isinstance(t.get("attribution"), dict) else {}
    if a.get("fuente"):
        return a["fuente"]
    if t.get("origin") in FUENTES:
        return t["origin"]
    if t.get("source") == "web":
        return "presupuesto_app" if (t.get("createdBy") or "") == "Formulario web" else "web"
    return "sin_apuntar"


def etapa(t):
    if t.get("status") == "completado":
        return "completado"
    if t.get("date"):
        return "programado"
    return t.get("stage") or "solicitud"


def analizar_negocio(trabajos, d, h, hoy=None):
    """trabajos: [(id, dict)]. Solicitudes nuevas (por fecha de creación) y trabajos hechos (por fecha del trabajo)."""
    hoy = hoy or date.today()
    ds, hs = d.isoformat(), h.isoformat()
    nuevas = defaultdict(lambda: Counter())
    hechos = defaultdict(lambda: {"trabajos": 0, "ingresos": 0.0})
    sin_origen, recientes = [], []
    agenda = 0
    for i, t in trabajos:
        o = origen_trabajo(t)
        creado = dia_madrid(t.get("createdAt"))
        st = etapa(t)
        if creado and ds <= creado <= hs:
            nuevas[o]["solicitudes"] += 1
            nuevas[o][st] += 1
            if st in ("presupuestado", "aceptado", "programado", "completado"):
                nuevas[o]["presupuestadas"] += 1
            if st in ("aceptado", "programado", "completado"):
                nuevas[o]["ganadas"] += 1
            recientes.append({"id": i, "cliente": _nombre_corto(t.get("clientName")), "poblacion": t.get("location") or "",
                              "creado": creado, "origen": o, "etapa": st,
                              "precio": precio(t.get("price") or (t.get("proposal") or {}).get("price"))})
            if o == "sin_apuntar":
                sin_origen.append(recientes[-1])
        fecha = t.get("date") or ""
        if st == "completado" and ds <= fecha <= hs:
            hechos[o]["trabajos"] += 1
            hechos[o]["ingresos"] += precio(t.get("price"))
        if st == "programado" and fecha >= hoy.isoformat():
            agenda += 1
    por_origen = []
    for o in set(nuevas) | set(hechos):
        c = nuevas[o]
        por_origen.append({"origen": o, "nombre": FUENTES.get(o, o), "solicitudes": c["solicitudes"],
                           "presupuestadas": c["presupuestadas"], "ganadas": c["ganadas"], "perdidas": c["perdido"],
                           "pct_ganadas": _pct(c["ganadas"], c["solicitudes"]),
                           "trabajos_hechos": hechos[o]["trabajos"], "ingresos": round(hechos[o]["ingresos"], 2)})
    por_origen.sort(key=lambda x: (-x["ingresos"], -x["solicitudes"]))
    tot = lambda k: sum(x[k] for x in por_origen)
    recientes.sort(key=lambda x: x["creado"], reverse=True)
    return {
        "solicitudes": tot("solicitudes"), "ganadas": tot("ganadas"), "perdidas": tot("perdidas"),
        "pct_ganadas": _pct(tot("ganadas"), tot("solicitudes")),
        "trabajos_hechos": tot("trabajos_hechos"), "ingresos": round(tot("ingresos"), 2),
        "ticket_medio": round(tot("ingresos") / tot("trabajos_hechos"), 2) if tot("trabajos_hechos") else 0,
        "programados_pendientes": agenda,
        "por_origen": por_origen, "sin_origen": sin_origen[:30], "recientes": recientes[:40],
    }


def _nombre_corto(n):
    """Solo el nombre de pila (privacidad)."""
    return (str(n or "").strip().split() or [""])[0][:30]


# ── Redes ───────────────────────────────────────────────────

ULTIMO_VALOR = {"seguidores"}   # el resto se suma día a día


def analizar_redes(dias, publicaciones):
    """dias: [{red, dia, m:{...}}]; publicaciones: [{red, id, fecha, tipo, texto, url, m:{...}}]."""
    por_red = defaultdict(lambda: {"metricas": Counter(), "ultimo": {}, "serie": []})
    for x in sorted(dias, key=lambda x: x.get("dia", "")):
        r = por_red[x.get("red")]
        m = x.get("m") or {}
        for k, v in m.items():
            v = _num(v)
            if v is None:
                continue
            if k in ULTIMO_VALOR:
                r["ultimo"][k] = v
            else:
                r["metricas"][k] += v
        r["serie"].append({"dia": x.get("dia"), **{k: _num(v) for k, v in m.items()}})
    redes = {}
    for red, r in por_red.items():
        primero = next((s.get("seguidores") for s in r["serie"] if s.get("seguidores") is not None), None)
        ult = r["ultimo"].get("seguidores")
        redes[red] = {"nombre": FUENTES.get(red, red), "totales": {k: round(v, 2) for k, v in r["metricas"].items()},
                      "seguidores": ult, "seguidores_cambio": (ult - primero) if (ult is not None and primero is not None) else None,
                      "dias_con_datos": len(r["serie"]), "serie": r["serie"][-120:]}
    def puntos(p):
        m = p.get("m") or {}
        return (_num(m.get("visualizaciones")) or 0) + 3 * (_num(m.get("interacciones")) or 0) + 5 * (_num(m.get("compartidos")) or 0)
    top = sorted(publicaciones, key=puntos, reverse=True)
    return {"redes": redes, "top_publicaciones": [{**p, "puntos": round(puntos(p))} for p in top[:15]]}


def limpiar_metricas(m):
    out = {}
    for k, v in (m.items() if isinstance(m, dict) else []):
        k = re.sub(r"[^a-z0-9_]", "_", str(k).lower())[:40]
        if k and _num(v) is not None:
            out[k] = _num(v)
    return out


def guardar_redes(args, repo, ahora=None):
    """Guarda métricas diarias y de publicaciones de una red (puente Metricool, Claude o a mano)."""
    red = _txt(args.get("red"), 30).lower()
    if red not in REDES:
        raise ValueError(f"'red' debe ser una de: {', '.join(sorted(REDES))}.")
    ahora = ahora or datetime.now(timezone.utc)
    n_d = n_p = 0
    for x in (args.get("dias") or [])[:400]:
        dia = _txt((x or {}).get("dia"), 10)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", dia):
            continue
        m = limpiar_metricas(x.get("metricas") or x.get("m"))
        if m:
            repo.guardar_red_dia(red, dia, {"red": red, "dia": dia, "m": m, "actualizado": ahora,
                                            "fuente_datos": _txt(args.get("fuente_datos") or "metricool", 30)})
            n_d += 1
    for p in (args.get("publicaciones") or [])[:200]:
        pid = re.sub(r"[^A-Za-z0-9_-]", "", str((p or {}).get("id") or ""))[:80]
        if not pid:
            continue
        repo.guardar_publicacion(red, pid, {
            "red": red, "id": pid, "fecha": _txt(p.get("fecha"), 10), "tipo": _txt(p.get("tipo"), 20),
            "texto": _txt(p.get("texto"), 220), "url": _txt(p.get("url"), 300) if str(p.get("url") or "").startswith("https://") else "",
            "m": limpiar_metricas(p.get("metricas") or p.get("m")), "actualizado": ahora})
        n_p += 1
    return {"ok": True, "red": red, "dias_guardados": n_d, "publicaciones_guardadas": n_p}


# ── Resumen completo ────────────────────────────────────────

def _delta(a, b):
    if not b:
        return None
    return round(100 * (a - b) / b, 1)


KPIS = [("visitas", "web"), ("contactan", "web"), ("leads", "web"), ("solicitudes", "negocio"),
        ("ganadas", "negocio"), ("trabajos_hechos", "negocio"), ("ingresos", "negocio")]


def flujo(web, negocio, redes):
    """Cómo se mueve la gente de un portal a otro: red → web → contacto → solicitud → trabajo → €."""
    filas = {}
    for f in web["fuentes"]:
        filas[f["fuente"]] = {"origen": f["fuente"], "nombre": f["nombre"], "visitas_web": f["visitas"],
                              "contactan": f["contactan"], "solicitudes": 0, "ganadas": 0, "ingresos": 0.0}
    for o in negocio["por_origen"]:
        x = filas.setdefault(o["origen"], {"origen": o["origen"], "nombre": o["nombre"], "visitas_web": 0,
                                           "contactan": 0, "solicitudes": 0, "ganadas": 0, "ingresos": 0.0})
        x["solicitudes"] += o["solicitudes"]
        x["ganadas"] += o["ganadas"]
        x["ingresos"] += o["ingresos"]
    for red, r in redes["redes"].items():
        if red in filas or r["totales"]:
            x = filas.setdefault(red, {"origen": red, "nombre": r["nombre"], "visitas_web": 0, "contactan": 0,
                                       "solicitudes": 0, "ganadas": 0, "ingresos": 0.0})
            t = r["totales"]
            x["alcance_red"] = t.get("alcance") or t.get("visualizaciones")
            x["clics_a_web_red"] = t.get("clics_web")
    out = sorted(filas.values(), key=lambda x: (-x["ingresos"], -x["solicitudes"], -x["visitas_web"]))
    for x in out:
        x["pct_visita_a_solicitud"] = _pct(x["solicitudes"], x["visitas_web"]) if x["visitas_web"] else None
    return out


def resumen(repo, desde=None, hasta=None, ahora=None, con_anterior=True):
    d, h = rango(desde, hasta, ahora=ahora)
    ses = repo.sesiones(d.isoformat(), h.isoformat())
    trabajos = repo.trabajos()
    web = analizar_web(ses)
    negocio = analizar_negocio(trabajos, d, h, hoy=hoy_madrid(ahora))
    redes = analizar_redes(repo.redes_dias(d.isoformat(), h.isoformat()),
                           repo.publicaciones(d.isoformat(), h.isoformat()))
    out = {"desde": d.isoformat(), "hasta": h.isoformat(), "dias": (h - d).days + 1,
           "web": web, "negocio": negocio, "redes": redes, "flujo": flujo(web, negocio, redes),
           "preguntas_chat": repo.preguntas(d.isoformat(), h.isoformat())[:60]}
    if con_anterior:
        pd, ph = periodo_anterior(d, h)
        w0 = analizar_web(repo.sesiones(pd.isoformat(), ph.isoformat()))
        n0 = analizar_negocio(trabajos, pd, ph, hoy=hoy_madrid(ahora))
        bloques = {"web": (web, w0), "negocio": (negocio, n0)}
        out["anterior"] = {"desde": pd.isoformat(), "hasta": ph.isoformat(),
                           "kpis": {k: {"ahora": bloques[b][0][k], "antes": bloques[b][1][k],
                                        "cambio_pct": _delta(bloques[b][0][k], bloques[b][1][k])} for k, b in KPIS}}
    return out


def compacto(r):
    """Versión corta del resumen para Claude y para la IA (sin series largas)."""
    w, n, rd = r["web"], r["negocio"], r["redes"]
    return {
        "periodo": f"{r['desde']} a {r['hasta']}", "comparado_con": r.get("anterior", {}).get("kpis"),
        "web": {k: w[k] for k in ("visitas", "paginas_vistas", "contactan", "pct_contactan", "leads", "pct_rebote",
                                  "duracion_mediana_seg", "dispositivos", "clics", "calculadora", "chat", "formulario")}
               | {"fuentes": w["fuentes"][:10], "paginas": w["paginas"][:10], "entradas": w["entradas"][:6],
                  "recorridos": w["recorridos"][:8], "secciones_inicio": (w["secciones"].get("/") or [])[:12],
                  "scroll": w["scroll"], "clics_zona": w["clics_zona"][:10], "campanas": w["campanas"][:8]},
        "negocio": {k: n[k] for k in ("solicitudes", "ganadas", "perdidas", "pct_ganadas", "trabajos_hechos",
                                      "ingresos", "ticket_medio", "programados_pendientes", "por_origen")}
                   | {"solicitudes_sin_origen": len(n["sin_origen"])},
        "redes": {red: {k: v for k, v in x.items() if k != "serie"} for red, x in rd["redes"].items()},
        "top_publicaciones": rd["top_publicaciones"][:8],
        "flujo_entre_portales": r["flujo"],
        "preguntas_chat": [p.get("texto") for p in r.get("preguntas_chat", [])][:40],
    }


def sesiones_detalle(repo, desde=None, hasta=None, fuente=None, solo_leads=False, limite=30, ahora=None):
    """Recorridos de visitas concretas (anónimas), para ver el comportamiento paso a paso."""
    d, h = rango(desde, hasta, por_defecto=7, ahora=ahora)
    out = []
    for s in sorted(repo.sesiones(d.isoformat(), h.isoformat()), key=lambda s: str(s.get("inicio")), reverse=True):
        if fuente and s.get("fuente") != fuente:
            continue
        if solo_leads and not _contactos(s):
            continue
        pasos = []
        for e in s.get("eventos") or []:
            if e["n"] in ("scroll",):
                continue
            det = e.get("d") or {}
            txt = {"vista": f"ve {e['p']}", "seccion": f"mira «{det.get('id')}»", "clic": f"pulsa {det.get('que')} ({det.get('zona') or e['p']})",
                   "salida": f"{int(det.get('seg') or 0)} s en {e['p']}", "calc_paso": f"calculadora paso {det.get('paso')} {det.get('nombre') or ''}".strip(),
                   "calc_fotos": f"sube {det.get('n')} fotos", "calc_resultado": f"le sale {det.get('min')}–{det.get('max')} €",
                   "calc_error": f"error en calculadora: {det.get('motivo')}", "chat_abierto": "abre el chat",
                   "chat_mensaje": "escribe al chat", "form_inicio": "empieza el formulario", "lead": f"ENVÍA {det.get('tipo')}"}.get(e["n"], e["n"])
            pasos.append(f"{round(e.get('s', 0) / 1000)}s {txt}")
        out.append({"dia": s.get("dia"), "fuente": s.get("fuente"), "detalle": s.get("detalle"), "campana": s.get("campana"),
                    "disp": s.get("disp"), "duracion_seg": _duracion(s), "lead": (s.get("lead") or {}).get("tipo"),
                    "pasos": pasos[:60]})
        if len(out) >= max(1, min(int(limite or 30), 100)):
            break
    return {"desde": d.isoformat(), "hasta": h.isoformat(), "visitas": out}


# ── Informe semanal con IA ──────────────────────────────────

PROMPT_INFORME = """Eres el analista de marketing de Mudanzas del Sur, una empresa de mudanzas pequeña de Huelva (España)
que capta clientes por su web (con calculadora de presupuesto con IA y chat), Instagram, TikTok, Facebook,
el Perfil de Google y Google Ads. El objetivo es que cada portal traiga más solicitudes y que se ayuden entre sí.

Te paso los datos del periodo (JSON) comparados con el periodo anterior. Escribe un informe en español de España,
directo y práctico, para el dueño (no es analista). Reglas:
- Usa SOLO los datos que te paso. Si un dato falta o hay pocos datos, dilo y no lo inventes.
- Cifras concretas («de 40 visitas de Instagram, 3 pidieron presupuesto»), sin jerga.
- Las recomendaciones tienen que poder hacerse esta semana y decir en qué portal y qué cambiar exactamente.
- Fíjate en el paso de la calculadora donde más gente se va, en qué secciones de la web se miran o no,
  qué fuente trae visitas que contactan y cuál trae visitas que se van, y qué preguntan en el chat
  (eso son ideas de contenido para redes y para las preguntas frecuentes de la web).
- No des consejos genéricos de marketing.

Devuelve EXCLUSIVAMENTE un JSON válido, sin texto alrededor, con esta forma:
{"titular": "una frase con lo más importante", "resumen": "3-4 frases",
 "puntos": [{"portal": "web|instagram|tiktok|facebook|google|mudanzapro|general", "tipo": "bien|mal|accion", "texto": "..."}],
 "ideas_contenido": ["idea de reel o post concreta", "..."],
 "experimento": "un cambio para probar la semana que viene y cómo sabremos si funciona"}
Entre 6 y 12 puntos, al menos 4 de tipo "accion"."""


def _json_de_texto(texto):
    t = (texto or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    i, j = t.find("{"), t.rfind("}")
    return json.loads(t[i:j + 1]) if i >= 0 and j > i else None


def generar_informe(repo, gem, clave, modelos, desde=None, hasta=None, ahora=None):
    """Genera y guarda el informe del periodo (por defecto, los últimos 7 días)."""
    ahora = ahora or datetime.now(timezone.utc)
    h = datetime.strptime(hasta, "%Y-%m-%d").date() if hasta else hoy_madrid(ahora) - timedelta(days=1)
    d = datetime.strptime(desde, "%Y-%m-%d").date() if desde else h - timedelta(days=6)
    r = resumen(repo, d.isoformat(), h.isoformat(), ahora=ahora)
    datos = compacto(r)
    informe = None
    motivo = ""
    if clave:
        try:
            texto = gem(modelos, [{"role": "user", "parts": [{"text": json.dumps(datos, ensure_ascii=False, default=str)}]}],
                        clave, system=PROMPT_INFORME,
                        config={"temperature": 0.4, "maxOutputTokens": 8192, "responseMimeType": "application/json",
                                "thinkingConfig": {"thinkingLevel": "low"}}, timeout=80)
            informe = _json_de_texto(texto)
        except Exception as e:  # noqa: BLE001
            motivo = repr(e)[:200]
    if not isinstance(informe, dict):
        informe = informe_sin_ia(datos)
        informe["sin_ia"] = motivo or "La IA no respondió; informe automático con las cifras."
    doc = {"desde": r["desde"], "hasta": r["hasta"], "creado": ahora, "informe": informe,
           "kpis": r.get("anterior", {}).get("kpis")}
    repo.guardar_informe(r["hasta"], doc)
    return doc


def informe_sin_ia(datos):
    """Si la IA falla, un informe básico con las cifras (mejor que nada)."""
    w, n = datos["web"], datos["negocio"]
    puntos = []
    if w["fuentes"]:
        f = w["fuentes"][0]
        puntos.append({"portal": "web", "tipo": "bien", "texto": f"La fuente que más visitas trae es {f['nombre']} ({f['visitas']})."})
    emb = w["calculadora"]["embudo"]
    if len(emb) > 1:
        caida = max(range(1, len(emb)), key=lambda i: emb[i - 1]["visitas"] - emb[i]["visitas"])
        puntos.append({"portal": "web", "tipo": "mal",
                       "texto": f"En la calculadora, donde más gente se va es al pasar de «{emb[caida - 1]['nombre']}» a «{emb[caida]['nombre']}»."})
    if n["solicitudes_sin_origen"]:
        puntos.append({"portal": "mudanzapro", "tipo": "accion",
                       "texto": f"Apunta de dónde vinieron {n['solicitudes_sin_origen']} solicitudes sin origen para medir bien cada portal."})
    return {"titular": f"{w['visitas']} visitas a la web, {n['solicitudes']} solicitudes y {n['trabajos_hechos']} trabajos hechos.",
            "resumen": "", "puntos": puntos, "ideas_contenido": [], "experimento": ""}


# ── Enlaces con etiqueta (UTM) ──────────────────────────────

def enlace_utm(url, fuente, medio, campana="", contenido=""):
    base = url if str(url).startswith("http") else "https://mudanzasdelsur.es" + ("/" + str(url).lstrip("/") if url else "/")
    limpio = lambda s: re.sub(r"[^a-z0-9_-]+", "-", str(s or "").lower()).strip("-")[:40]
    params = [("utm_source", limpio(fuente)), ("utm_medium", limpio(medio)),
              ("utm_campaign", limpio(campana)), ("utm_content", limpio(contenido))]
    q = "&".join(f"{k}={v}" for k, v in params if v)
    return base + ("&" if "?" in base else "?") + q


# ── Firebase ────────────────────────────────────────────────

class FirebaseAnaliticaRepo:
    def __init__(self, db=None):
        if db is None:
            from firebase_admin import firestore
            db = firestore.client()
        self._db = db

    def sesion(self, sid):
        snap = self._db.collection("analitica_sesiones").document(sid).get()
        return snap.to_dict() if snap.exists else None

    def guardar_sesion(self, sid, data):
        self._db.collection("analitica_sesiones").document(sid).set(data)

    def marcar_lead(self, sid, tipo, trabajo_id):
        if not sid:
            return
        ref = self._db.collection("analitica_sesiones").document(sid)
        try:
            if ref.get().exists:
                ref.update({"lead": {"tipo": tipo, "id": trabajo_id}})
        except Exception:
            pass

    def sesiones(self, desde, hasta):
        q = (self._db.collection("analitica_sesiones").where("dia", ">=", desde).where("dia", "<=", hasta))
        return [d.to_dict() or {} for d in q.stream()]

    def trabajos(self):
        return [(d.id, d.to_dict() or {}) for d in self._db.collection("trabajos").stream()]

    def redes_dias(self, desde, hasta):
        q = self._db.collection("redes_metricas").where("dia", ">=", desde).where("dia", "<=", hasta)
        return [d.to_dict() or {} for d in q.stream()]

    def publicaciones(self, desde, hasta):
        q = self._db.collection("redes_publicaciones").where("fecha", ">=", desde).where("fecha", "<=", hasta)
        return [d.to_dict() or {} for d in q.stream()]

    def guardar_red_dia(self, red, dia, data):
        self._db.collection("redes_metricas").document(f"{red}_{dia}").set(data)

    def guardar_publicacion(self, red, pid, data):
        self._db.collection("redes_publicaciones").document(f"{red}_{pid}").set(data)

    def guardar_pregunta(self, data):
        self._db.collection("analitica_preguntas").add(data)

    def preguntas(self, desde, hasta):
        q = self._db.collection("analitica_preguntas").where("dia", ">=", desde).where("dia", "<=", hasta)
        out = [d.to_dict() or {} for d in q.stream()]
        out.sort(key=lambda x: str(x.get("at")), reverse=True)
        return [{"dia": x.get("dia"), "texto": x.get("texto"), "pagina": x.get("pagina")} for x in out]

    def guardar_informe(self, clave, data):
        self._db.collection("analitica_informes").document(clave).set(data)

    def informes(self, n=8):
        from firebase_admin import firestore
        q = self._db.collection("analitica_informes").order_by("creado", direction=firestore.Query.DESCENDING).limit(n)
        return [d.to_dict() or {} for d in q.stream()]

    def asignar_origen(self, trabajo_id, origen, quien):
        ref = self._db.collection("trabajos").document(trabajo_id)
        if not ref.get().exists:
            raise ValueError("No existe ese trabajo.")
        ref.update({"origin": origen, "originBy": quien, "updatedAt": datetime.now(timezone.utc)})
