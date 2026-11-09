import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "functions"))
import app_ia as a

UID = "uidAlberto1"
TOK = {"uid": UID, "email": "albertogmez99@gmail.com"}

class Req:
    def __init__(s, body=None, token="ok", method="POST"):
        s.method, s._b = method, body or {}
        s.headers = {"Authorization": f"Bearer {token}"} if token else {}
    def get_json(s, silent=True): return s._b

def verificar(t):
    if t == "ok": return TOK
    if t == "otro": return {"uid": "x", "email": "alguien@gmail.com"}
    raise ValueError("token")

def gem_ok(modelos, contents, clave, **k):
    partes = contents[0]["parts"]
    assert partes[0]["inline_data"]["mime_type"] == "image/jpeg" and partes[1]["text"].startswith("Eres")
    return json.dumps({"es_ticket": True, "importe": "45,30", "tipo": "gasoil", "comercio": "Repsol Huelva Norte", "fecha": "2026-11-03"})

def call(body, token="ok", gem=gem_ok, leer=lambda p: (b"img", "image/jpeg")):
    r = a.handle(Req(body, token), verificar=verificar, leer_bytes=leer, gem=gem, clave="k", modelos=["m1"])
    return r.status_code, json.loads(r.get_data())

def ruta(): return f"trabajos/{UID}/gastos/job1_123.jpg"

def test_lee_ticket():
    st, b = call({"accion": "leer_ticket", "path": ruta()})
    assert st == 200 and b == {"ok": True, "es_ticket": True, "importe": 45.3, "tipo": "gasoil",
                               "comercio": "Repsol Huelva Norte", "fecha": "2026-11-03"}

def test_solo_equipo():
    assert call({"accion": "leer_ticket", "path": ruta()}, token=None)[0] == 401
    assert call({"accion": "leer_ticket", "path": ruta()}, token="otro")[0] == 401
    assert call({"accion": "leer_ticket", "path": ruta()}, token="malo")[0] == 401

def test_ruta_de_otro_usuario_o_rara():
    assert call({"accion": "leer_ticket", "path": "trabajos/otro/gastos/x.jpg"})[0] == 400
    assert call({"accion": "leer_ticket", "path": f"trabajos/{UID}/../x.jpg"})[0] == 400
    assert call({"accion": "leer_ticket", "path": "presupuestos/x.pdf"})[0] == 400

def test_ia_caida_da_503_con_mensaje():
    from web_ia import WebError
    def gem_mal(*x, **k): raise WebError(503, "ia no disponible")
    st, b = call({"accion": "leer_ticket", "path": ruta()}, gem=gem_mal)
    assert st == 503 and "a mano" in b["error"]

def test_json_raro_se_limpia():
    def gem(*x, **k): return '```json\n{"importe": 99999, "tipo": "coche", "comercio": "x", "fecha": "3/11/26"}\n```'
    st, b = call({"accion": "leer_ticket", "path": ruta()}, gem=gem)
    assert st == 200 and b["importe"] is None and b["tipo"] == "otros" and b["fecha"] is None and b["es_ticket"] is False

def test_accion_desconocida():
    assert call({"accion": "borrar"})[0] == 404

def test_main_registra_app_api():
    src = open(os.path.join(os.path.dirname(__file__), "..", "functions", "main.py")).read()
    assert "from app_ia import app_api" in src
