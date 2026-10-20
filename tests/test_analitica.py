import json, os, sys
from datetime import date, datetime, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "functions"))
import analitica as an
import mcp_analitica as ma
import panel

UA_MOVIL = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
UA_IG = UA_MOVIL + " Instagram 300.0.0.0"
AHORA = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)


class Repo:
    def __init__(s):
        s.ses, s.trab, s.dias, s.pubs, s.preg, s.inf, s.origenes = {}, [], [], [], [], {}, {}
    def sesion(s, sid): return s.ses.get(sid)
    def guardar_sesion(s, sid, d): s.ses[sid] = d
    def marcar_lead(s, sid, tipo, i): s.ses[sid]["lead"] = {"tipo": tipo, "id": i}
    def sesiones(s, a, b): return [x for x in s.ses.values() if a <= x["dia"] <= b]
    def trabajos(s): return s.trab
    def redes_dias(s, a, b): return [x for x in s.dias if a <= x["dia"] <= b]
    def publicaciones(s, a, b): return [x for x in s.pubs if a <= x.get("fecha", "") <= b]
    def guardar_red_dia(s, red, dia, d): s.dias = [x for x in s.dias if not (x["red"] == red and x["dia"] == dia)] + [d]
    def guardar_publicacion(s, red, pid, d): s.pubs = [x for x in s.pubs if x["id"] != pid] + [d]
    def preguntas(s, a, b): return [p for p in s.preg if a <= p["dia"] <= b]
    def guardar_pregunta(s, d): s.preg.append(d)
    def guardar_informe(s, k, d): s.inf[k] = d
    def informes(s, n=8): return list(s.inf.values())[-n:]
    def asignar_origen(s, i, o, q): s.origenes[i] = o


def test_clasificar():
    assert an.clasificar({"utm_source": "ig", "utm_medium": "bio"})[0] == "instagram"
    assert an.clasificar({"clid": "gclid"})[0] == "google_ads"
    assert an.clasificar({"utm_source": "google", "utm_medium": "cpc"})[0] == "google_ads"
    assert an.clasificar({"utm_source": "gbp"})[0] == "google_perfil"
    assert an.clasificar({"ref": "https://www.google.es/"})[0] == "google"
    assert an.clasificar({"ref": "https://l.instagram.com/?u=x"})[0] == "instagram"
    assert an.clasificar({"ref": "https://mudanzasdelsur.es/blog/"})[0] == "directo"
    assert an.clasificar({}, UA_IG)[0] == "instagram"          # navegador de Instagram sin referer
    assert an.clasificar({"ref": "https://foro.ejemplo.com/x"}) == ("otras_webs", "foro.ejemplo.com")
    assert an.clasificar({"clid": "fbclid"})[0] == "meta"
    assert an.clasificar({})[0] == "directo"


def test_limpieza_y_privacidad():
    assert an.limpiar_pregunta("llámame al 659 71 52 71 o pepe@x.com") == "llámame al [teléfono] o [email]"
    evs = an.limpiar_eventos([{"n": "vista", "p": "/calculadora?x=1"}, {"n": "hack", "p": "/"},
                              {"n": "clic", "p": "javascript:x", "d": {"que": "whatsapp", "MAL": 1, "texto": "tel 600123123"}}])
    assert [e["n"] for e in evs] == ["vista", "clic"]
    assert evs[0]["p"] == "/calculadora/" and evs[1]["p"] == "/"
    assert "MAL" not in evs[1]["d"] and "600123123" not in evs[1]["d"]["texto"]
    assert an.precio("1.200,50 €") == 1200.5 and an.precio("450") == 450 and an.precio("") == 0


def _visita(repo, sid, ctx, eventos, ua=UA_MOVIL, ahora=AHORA):
    an.ingerir({"sid": sid, "ctx": ctx, "ev": eventos}, ua, repo, ahora=ahora)


def test_ingerir_y_analizar_web():
    r = Repo()
    # 1) Instagram → calculadora hasta el paso 3 → WhatsApp
    _visita(r, "aaaaaaaaaa01", {"utm_source": "instagram", "utm_medium": "bio", "landing": "/"}, [
        {"n": "vista", "p": "/", "s": 0}, {"n": "seccion", "p": "/", "s": 2000, "d": {"id": "ventajas"}},
        {"n": "scroll", "p": "/", "s": 3000, "d": {"pct": 50}}, {"n": "clic", "p": "/", "s": 5000, "d": {"que": "calculadora", "zona": "hero"}},
        {"n": "vista", "p": "/calculadora/", "s": 6000}, {"n": "calc_paso", "p": "/calculadora/", "s": 7000, "d": {"paso": 1, "nombre": "Qué mudas"}},
        {"n": "calc_paso", "p": "/calculadora/", "s": 9000, "d": {"paso": 2, "nombre": "Fotos"}},
        {"n": "calc_paso", "p": "/calculadora/", "s": 20000, "d": {"paso": 3, "nombre": "Direcciones"}},
        {"n": "clic", "p": "/calculadora/", "s": 40000, "d": {"que": "whatsapp", "zona": "fab"}}])
    # segundo lote de la misma visita: se añade, no se duplica la sesión
    _visita(r, "aaaaaaaaaa01", {}, [{"n": "salida", "p": "/calculadora/", "s": 50000, "d": {"seg": 44}}])
    # 2) Google → rebota
    _visita(r, "bbbbbbbbbb02", {"ref": "https://www.google.com/"}, [{"n": "vista", "p": "/", "s": 0}],
            ua="Mozilla/5.0 (Windows NT 10.0) Chrome/120")
    # 3) Directo → calculadora completa → lead
    _visita(r, "cccccccccc03", {}, [{"n": "vista", "p": "/calculadora/", "s": 0}] +
            [{"n": "calc_paso", "p": "/calculadora/", "s": i * 1000, "d": {"paso": i, "nombre": f"P{i}"}} for i in range(1, 7)] +
            [{"n": "calc_resultado", "p": "/calculadora/", "s": 9000, "d": {"min": 300, "max": 380}},
             {"n": "lead", "p": "/calculadora/", "s": 9500, "d": {"tipo": "calculadora"}}])
    # bots fuera
    _visita(r, "dddddddddd04", {}, [{"n": "vista", "p": "/"}], ua="Googlebot/2.1")
    assert set(r.ses) == {"aaaaaaaaaa01", "bbbbbbbbbb02", "cccccccccc03"}
    assert r.ses["aaaaaaaaaa01"]["n"] == 10 and r.ses["aaaaaaaaaa01"]["fuente"] == "instagram"

    w = an.analizar_web(list(r.ses.values()))
    assert w["visitas"] == 3 and w["leads"] == 1 and w["contactan"] == 2
    f = {x["fuente"]: x for x in w["fuentes"]}
    assert f["instagram"]["contactan"] == 1 and f["google"]["visitas"] == 1 and f["directo"]["leads"] == 1
    assert w["pct_rebote"] == 33.3
    emb = {e["paso"]: e["visitas"] for e in w["calculadora"]["embudo"]}
    assert emb[1] == 2 and emb[3] == 2 and emb[4] == 1 and emb[6] == 1
    assert w["calculadora"]["enviadas"] == 1 and w["calculadora"]["pct_terminan"] == 50.0
    assert w["secciones"]["/"][0] == {"id": "ventajas", "visitas": 1, "pct": 50.0}
    assert w["clics"]["whatsapp"] == 1
    assert w["recorridos"][0]["visitas"] == 1


def test_negocio_y_flujo():
    r = Repo()
    _visita(r, "aaaaaaaaaa01", {"utm_source": "instagram"}, [{"n": "vista", "p": "/"}])
    r.trab = [
        ("T1", {"createdAt": datetime(2026, 10, 10, 9, tzinfo=timezone.utc), "source": "web", "attribution": {"fuente": "instagram"},
                "status": "completado", "date": "2026-10-15", "price": "450", "clientName": "Lucía Pérez"}),
        ("T2", {"createdAt": datetime(2026, 10, 12, tzinfo=timezone.utc), "stage": "perdido", "clientName": "Ana"}),
        ("T3", {"createdAt": datetime(2026, 10, 14, tzinfo=timezone.utc), "origin": "boca_a_boca", "date": "2026-10-30", "price": "300"}),
        ("T4", {"createdAt": datetime(2026, 8, 1, tzinfo=timezone.utc), "status": "completado", "date": "2026-10-02", "price": 200}),
    ]
    res = an.resumen(r, "2026-09-23", "2026-10-20", ahora=AHORA)
    n = res["negocio"]
    assert n["solicitudes"] == 3 and n["ganadas"] == 2 and n["perdidas"] == 1
    assert n["trabajos_hechos"] == 2 and n["ingresos"] == 650 and n["programados_pendientes"] == 1
    assert [x["id"] for x in n["sin_origen"]] == ["T2"]
    assert n["recientes"][-1]["cliente"] == "Lucía"            # solo el nombre de pila
    fl = {x["origen"]: x for x in res["flujo"]}
    assert fl["instagram"]["visitas_web"] == 1 and fl["instagram"]["ingresos"] == 450
    assert res["anterior"]["kpis"]["solicitudes"]["antes"] == 0
    json.dumps(an.compacto(res), default=str)                   # se puede mandar a Claude / a la IA


def test_redes_e_mcp():
    r = Repo()
    out = ma.HANDLERS["guardar_metricas_redes"](r, {"red": "instagram", "dias": [
        {"dia": "2026-10-18", "metricas": {"seguidores": 243, "alcance": 100, "Visualizaciones": 400}},
        {"dia": "2026-10-19", "metricas": {"seguidores": 244, "alcance": 50}},
        {"dia": "malo", "metricas": {"alcance": 1}}],
        "publicaciones": [{"id": "abc", "fecha": "2026-10-18", "tipo": "reel", "texto": "Nevera por las escaleras",
                           "url": "https://instagram.com/p/abc", "metricas": {"visualizaciones": 900, "interacciones": 40}}]})
    assert json.loads(out[0]["text"])["dias_guardados"] == 2
    rd = an.analizar_redes(r.redes_dias("2026-10-01", "2026-10-31"), r.publicaciones("2026-10-01", "2026-10-31"))
    ig = rd["redes"]["instagram"]
    assert ig["seguidores"] == 244 and ig["seguidores_cambio"] == 1 and ig["totales"]["alcance"] == 150
    assert ig["totales"]["visualizaciones"] == 400 and rd["top_publicaciones"][0]["id"] == "abc"
    try:
        ma.HANDLERS["guardar_metricas_redes"](r, {"red": "myspace"})
        assert False
    except ma.AnaliticaToolError:
        pass
    ma.HANDLERS["asignar_origen_solicitud"](r, {"id": "T2", "origen": "instagram"})
    assert r.origenes == {"T2": "instagram"}
    url = json.loads(ma.HANDLERS["analitica_enlace"](r, {"url": "/calculadora/", "fuente": "Instagram", "medio": "historia",
                                                          "contenido": "Nevera Isla Cristina"})[0]["text"])["url"]
    assert url == "https://mudanzasdelsur.es/calculadora/?utm_source=instagram&utm_medium=historia&utm_content=nevera-isla-cristina"
    ma.HANDLERS["analitica_resumen"](r, {"desde": "2026-10-01", "hasta": "2026-10-20"})


def test_informe_con_y_sin_ia():
    r = Repo()
    _visita(r, "aaaaaaaaaa01", {}, [{"n": "vista", "p": "/", "s": 0}], ahora=datetime(2026, 10, 16, tzinfo=timezone.utc))
    visto = {}
    def gem(modelos, contents, clave, system=None, config=None, **k):
        visto["datos"] = json.loads(contents[0]["parts"][0]["text"])
        return '```json\n{"titular": "Bien", "resumen": "x", "puntos": [], "ideas_contenido": ["reel"], "experimento": ""}\n```'
    doc = an.generar_informe(r, gem, "K", ["m"], ahora=AHORA)
    assert doc["informe"]["titular"] == "Bien" and doc["desde"] == "2026-10-13" and doc["hasta"] == "2026-10-19"
    assert visto["datos"]["web"]["visitas"] == 1
    def roto(*a, **k): raise RuntimeError("caída")
    doc = an.generar_informe(r, roto, "K", ["m"], ahora=AHORA)
    assert doc["informe"]["sin_ia"] and "visitas" in doc["informe"]["titular"]


class Req:
    def __init__(s, body, token="ok", method="POST"):
        s.method, s._b = method, body
        s.headers = {"Authorization": f"Bearer {token}"} if token else {}
    def get_json(s, silent=True): return s._b


def test_panel_auth_y_acciones():
    r = Repo()
    verif = lambda t: {"email": "albertogmez99@gmail.com"} if t == "ok" else {"email": "otro@gmail.com"}
    assert panel.usuario(Req({}), verif) == "albertogmez99@gmail.com"
    assert panel.usuario(Req({}, token="x"), verif) is None
    assert panel.usuario(Req({}, token=None), verif) is None
    out = panel.accion({"accion": "resumen", "desde": "2026-10-01", "hasta": "2026-10-20"}, "a", r)
    assert out["web"]["visitas"] == 0
    panel.accion({"accion": "asignar_origen", "id": "T9", "origen": "tiktok"}, "a", r)
    assert r.origenes["T9"] == "tiktok"
    for malo in ({"accion": "asignar_origen", "id": "T9", "origen": "x"}, {"accion": "nada"},
                 {"accion": "resumen", "desde": "ayer"}):
        try:
            panel.accion(malo, "a", r)
            assert False, malo
        except panel.PanelError:
            pass
