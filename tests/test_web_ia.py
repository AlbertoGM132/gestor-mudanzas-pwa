import base64, io, json, sys
import os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "functions"))
from PIL import Image
import web_ia as w, formulario_web as fw

def jpeg_b64():
    b = io.BytesIO(); Image.new("RGB", (2000, 1500), (200, 100, 50)).save(b, "JPEG"); return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()

class Repo:
    def __init__(s): s.creados=[]; s.fotos=[]; s.avisos=[]
    def contar_envio(s,*a): return True
    def subir_foto(s, ruta, jpeg): s.fotos.append(ruta); return "https://x/"+ruta
    def crear(s, data): s.creados.append(data); return "ID1"
    def avisar(s,t,x): s.avisos.append((t,x))
    def tarifas(s): return {}
    def limitar(s,*a): return True

def test_origenes():
    assert w.origen_permitido("https://mudanzasdelsur.es")
    assert w.origen_permitido("https://mudanzas-del-sur--prueba-ab12cd.web.app")
    assert not w.origen_permitido("https://evil.com")
    assert not w.origen_permitido("https://mudanzas-del-sur--x.web.app.evil.com")
    assert not w.origen_permitido("")

def test_chat_sin_clave_fallback():
    r = w.chat({"message": "hola"}, "")
    assert r["ok"] is False and "WhatsApp" in r["reply"]

def test_chat_historial():
    vistos = {}
    def gem(models, contents, clave, system=None, config=None, **k):
        vistos["c"] = contents; vistos["s"] = system; return "¡Hola! Usa la calculadora."
    r = w.chat({"message": "cuánto cuesta", "history": [{"role":"model","text":"hola"},{"role":"user","text":"a"},{"role":"model","text":"b"}]}, "K", gem=gem)
    assert r["ok"] and r["reply"].startswith("¡Hola")
    assert vistos["c"][0]["role"] == "user" and vistos["c"][-1]["parts"][0]["text"] == "cuánto cuesta"
    assert "NUNCA des precios" in vistos["s"]

def test_gemini_cae_al_siguiente_modelo():
    import urllib.error
    llamadas = []
    def post(url, body, headers, timeout):
        llamadas.append(url)
        if "m1" in url: raise urllib.error.HTTPError(url, 404, "x", {}, None)
        assert headers["x-goog-api-key"] == "K"
        return {"candidates": [{"content": {"parts": [{"text": "pensando", "thought": True}, {"text": "ok"}]}}]}
    assert w.gemini(["m1", "m2"], [], "K", post=post) == "ok"
    assert len(llamadas) == 2

def test_gemini_reintenta_sin_thinking():
    import urllib.error
    cuerpos = []
    def post(url, body, headers, timeout):
        cuerpos.append(json.loads(json.dumps(body)))
        if "thinkingConfig" in body["generationConfig"]: raise urllib.error.HTTPError(url, 400, "x", {}, None)
        return {"candidates": [{"content": {"parts": [{"text": "vale"}]}}]}
    assert w.gemini(["m"], [], "K", config={"thinkingConfig": {"thinkingLevel": "minimal"}}, post=post) == "vale"
    assert len(cuerpos) == 2

def test_fotos_valida_salida_ia():
    salida = json.dumps({"items": [{"nombre": "sofá 3 plazas", "categoria": "sofa", "cantidad": 1},
                                   {"nombre": "cosa rara", "categoria": "nave", "cantidad": 99},
                                   {"nombre": "", "categoria": "cama"}],
                         "cajas": "12", "fragil": True, "especiales": ["piano", "ovni"]})
    gem = lambda *a, **k: "```json\n" + salida + "\n```"
    r = w.fotos({"fotos": [jpeg_b64()]}, "K", gem=gem)
    assert r["ok"] and r["fotos"] == 1
    assert r["items"][0]["categoria"] == "sofa"
    assert r["items"][1]["categoria"] == "otro" and r["items"][1]["cantidad"] == 30
    assert len(r["items"]) == 2 and r["cajas"] == 12 and r["especiales"] == ["piano"]

def test_fotos_ia_caida():
    def gem(*a, **k): raise w.WebError(503, "x")
    r = w.fotos({"fotos": [jpeg_b64()]}, "K", gem=gem)
    assert r["ok"] is False and r["fallback"]

def base():
    return {"nombre": "Lucía", "telefono": "600 111 222", "email": "lucia@example.com", "consentimiento": True, "t": 90000,
            "tipo": "casa", "casa": "2", "items": [{"categoria": "sofa", "nombre": "sofá", "cantidad": 1}, {"categoria": "armario4", "nombre": "armario 4p", "cantidad": 2}, {"categoria": "bicicleta", "nombre": "bici", "cantidad": 1}],
            "origen": {"calle": "C/ Concepción 1", "poblacion": "Huelva", "lat": 37.257, "lng": -6.95, "piso": "3", "ascensor": "no", "camion_m": 60},
            "destino": {"calle": "Av. Andalucía 5", "poblacion": "Aljaraque", "lat": 37.27, "lng": -7.02, "piso": "bajo", "ascensor": "", "camion_m": 5},
            "desmontaje": "si", "embalaje": "fragil", "fotos": [jpeg_b64()]}

def test_estimar_guarda_solicitud_y_rango():
    repo = Repo()
    r = w.estimar(base(), "1.2.3.4", repo, {}, ruta=lambda p: [3.0, 12.0, 10.0])
    assert r["ok"] and r["id"] == "ID1"
    e = r["estudio"]; assert e["min"] < e["max"] and "camión" in e["vehiculo"]
    assert "supuestos" not in e and "resultado" not in json.dumps(e)   # nada interno al cliente
    d = repo.creados[0]
    assert d["source"] == "web" and d["createdBy"] == "Calculadora web" and d["stage"] == "solicitud"
    assert d["proposal"]["by"] == "Calculadora web" and d["proposal"]["price"] >= e["min"]
    assert d["webEstimate"]["min"] == e["min"]
    assert d["originAccess"] == {"parking": "100"} and d["destinAccess"] == {"parking": "puerta"}
    assert d["inventory"]["muebles"] == {"sofá": 1, "armarios de 4 puertas": 2, "bicicleta": 1}   # la bici ya tiene contador propio
    assert "bici" not in d["inventory"].get("otros", "")
    assert "🧮 Calculadora web" in d["notes"] and "calculadora de la web" in d["notes"]
    assert d["email"] == "lucia@example.com" and len(d["photos"]) == 1
    assert "Desmontaje y montaje" in d["services"]

def test_estimar_km_aprox_si_falla_ruta():
    repo = Repo()
    def ruta(p): raise OSError("sin red")
    r = w.estimar(base(), "1.2.3.4", repo, {}, ruta=ruta)
    assert r["ok"] and "Km aproximados" in repo.creados[0]["notes"]

def test_estimar_validaciones():
    repo = Repo()
    for cambio, txt in (({"consentimiento": False}, "privacidad"), ({"email": "x"}, "email"),
                        ({"origen": {"calle": "x"}}, "mapa"), ({"telefono": "12"}, "teléfono")):
        try:
            w.estimar({**base(), **cambio}, "1", repo, {}, ruta=lambda p: [1, 1, 1]); assert False, cambio
        except w.WebError as e:
            assert txt in e.mensaje, (cambio, e.mensaje)
    assert repo.creados == []

def test_estimar_bot():
    repo = Repo()
    assert w.estimar({**base(), "web": "spam"}, "1", repo, {}, ruta=lambda p: [1, 1, 1]) == {"ok": True}
    r = w.estimar({**base(), "t": 100}, "1", repo, {}, ruta=lambda p: [1, 1, 1])
    assert r == {"ok": True} and repo.creados == []

def test_estimar_lejos_sin_precio():
    repo = Repo()
    r = w.estimar(base(), "1", repo, {}, ruta=lambda p: [3.0, 620.0, 630.0])
    assert r["estudio"]["sin_precio"] and "min" not in r["estudio"]
    assert "sin precio" in repo.creados[0]["notes"]

def test_contacto():
    repo = Repo()
    r = w.contacto({"nombre": "Pepe", "telefono": "655443322", "mensaje": "Hola", "ruta": "Huelva - Sevilla", "t": 9000}, "1", repo)
    assert r["ok"] and "Ruta: Huelva - Sevilla" in repo.creados[0]["notes"] and "contacto de la web" in repo.creados[0]["notes"]

def test_formulario_sigue_igual():
    repo = Repo()
    fw.procesar({"nombre": "Ana", "telefono": "600000000", "t": 9000}, "1", repo)
    assert repo.creados[0]["createdBy"] == "Formulario web" and "formulario web" in repo.creados[0]["notes"]

def test_fotos_prueba_siguiente_modelo_si_json_roto():
    llamadas = []
    def gem(modelos, *a, **k):
        llamadas.append(modelos[0])
        return '{"items": [{"nombre": "sofá"' if len(llamadas) == 1 else '{"items": [{"nombre": "sofá", "categoria": "sofa", "cantidad": 1}]}'
    r = w.fotos({"fotos": [jpeg_b64()]}, "K", gem=gem)
    assert r["ok"] and len(llamadas) == 2 and r["items"][0]["categoria"] == "sofa"

def test_gemini_guarda_motivos():
    import urllib.error
    motivos = []
    def post(url, body, headers, timeout):
        if "m1" in url: raise urllib.error.HTTPError(url, 429, "x", {}, None)
        return {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": []}}]}
    try:
        w.gemini(["m1", "m2"], [], "K", post=post, motivos=motivos); assert False
    except w.WebError:
        pass
    assert motivos[0].startswith("m1: HTTP 429") and "MAX_TOKENS" in motivos[1]

def test_asistente_sin_nombres():
    from web_conocimiento import CONOCIMIENTO
    for n in ("Alberto", "Cristian"):
        assert n not in CONOCIMIENTO


def test_formulario_detalles_pies_de_foto_y_entrega():
    """El caso de Virginia: somieres, medidas de los sofás, qué sale en cada foto y entrega que puede esperar."""
    repo = Repo()
    body = {"nombre": "Virginia", "telefono": "600000000", "t": 9000, "servicios": ["porte"],
            "origen": {"poblacion": "Nuevo Portil", "piso": "bajo", "aparcamiento": "puerta"},
            "destino": {"poblacion": "Madrid", "piso": "3", "ascensor": "si"},
            "inventario": {"muebles": {"sofas": 5, "somieres": 5, "jardin": 4},
                           "detalles": {"sofas": "3 de 160 cm y 2 de 120 cm", "somieres": "90 × 190, sin colchón", "camas": "no marcado"}},
            "entrega": "espera",
            "fotos": [{"data": jpeg_b64(), "nota": "los 3 sofás del salón"}, jpeg_b64()]}
    r = fw.procesar(body, "1", repo)
    d = repo.creados[0]
    assert r["ok"] and r["fotos"] == 2
    assert d["inventory"]["muebles"] == {"sofás": 5, "somieres o bases con patas": 5, "muebles de jardín o terraza": 4}
    assert d["inventory"]["detalles"] == {"sofás": "3 de 160 cm y 2 de 120 cm", "somieres o bases con patas": "90 × 190, sin colchón"}
    assert "5 sofás (3 de 160 cm y 2 de 120 cm)" in d["notes"]
    assert "🚚 Entrega: puede esperar unos días" in d["notes"] and d["inventory"]["entrega"] == "puede esperar unos días"
    assert d["photos"][0]["caption"] == "los 3 sofás del salón" and "caption" not in d["photos"][1]
    assert "1) los 3 sofás del salón" in d["notes"]
    assert "possibleDuplicateOf" not in d


def test_formulario_avisa_de_posible_repetida():
    class R(Repo):
        def reciente_mismo_telefono(s, tel, desde):
            assert tel == "600 000 000"
            return {"id": "PREV", "nombre": "Virginia", "fecha": "el 21/10"}
    repo = R()
    fw.procesar({"nombre": "Virginia", "telefono": "600000000", "t": 9000}, "1", repo)
    d = repo.creados[0]
    assert d["possibleDuplicateOf"] == "PREV" and d["notes"].startswith("⚠️ PUEDE ESTAR REPETIDA") and "el 21/10" in d["notes"]


def test_formulario_sigue_si_falla_buscar_repetidas():
    class R(Repo):
        def reciente_mismo_telefono(s, *a): raise RuntimeError("sin red")
    repo = R()
    assert fw.procesar({"nombre": "Ana", "telefono": "600000000", "t": 9000}, "1", repo)["ok"]
    assert "possibleDuplicateOf" not in repo.creados[0]
