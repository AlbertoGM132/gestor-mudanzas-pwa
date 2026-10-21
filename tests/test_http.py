import json, sys
import os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "functions"))
import web_ia as w
from test_web_ia import Repo

class Req:
    def __init__(s, method="POST", path="/chat", origin="https://mudanzasdelsur.es", body=None):
        s.method, s.path, s._b = method, path, body or {}
        s.headers = {"Origin": origin, "X-Forwarded-For": "1.2.3.4"}
        s.content_length = len(json.dumps(s._b)); s.remote_addr = "1.2.3.4"
    def get_json(s, silent=True): return s._b

def call(**k):
    r = w.handle(Req(**k), repo_factory=Repo, clave="")
    return r.status_code, json.loads(r.get_data() or b"{}"), r.headers

def test_preflight_y_origen():
    st, _, h = call(method="OPTIONS")
    assert st == 204 and h["Access-Control-Allow-Origin"] == "https://mudanzasdelsur.es"
    st, b, h = call(origin="https://evil.com")
    assert st == 403 and "Access-Control-Allow-Origin" not in h

def test_chat_sin_clave():
    st, b, _ = call(body={"message": "hola"})
    assert st == 200 and b["ok"] is False and "WhatsApp" in b["reply"]

def test_ruta_desconocida():
    assert call(path="/borrar")[0] == 404

def test_limite():
    class R(Repo):
        def limitar(s, *a): return False
    r = w.handle(Req(), repo_factory=R, clave="")
    assert r.status_code == 429 and "WhatsApp" in json.loads(r.get_data())["error"]

def test_error_validacion_es_400():
    st, b, _ = call(path="/estimar", body={"nombre": "x"})
    assert st == 400 and "privacidad" in b["error"]

def test_main_importa():
    import importlib, os
    os.chdir(os.path.join(os.path.dirname(__file__), "..", "functions"))
    src = open("main.py").read()
    assert "from web_ia import web_api" in src


class ReqTexto(Req):
    """sendBeacon manda el JSON como text/plain."""
    def __init__(s, texto, ua="Mozilla/5.0 (iPhone) Mobile Instagram 300", **k):
        super().__init__(path="/evento", **k)
        s._t = texto; s.headers["User-Agent"] = ua; s.content_length = len(texto)
    def get_data(s, as_text=False): return s._t


def test_evento_guarda_sesion_y_nunca_falla():
    guardadas = {}
    class R(Repo):
        def sesion(s, sid): return guardadas.get(sid)
        def guardar_sesion(s, sid, d): guardadas[sid] = d
    body = json.dumps({"sid": "abcdefghij12", "ctx": {"landing": "/"}, "ev": [{"n": "vista", "p": "/", "s": 0}]})
    r = w.handle(ReqTexto(body), repo_factory=R, clave="")
    assert r.status_code == 200 and guardadas["abcdefghij12"]["fuente"] == "instagram"
    assert w.handle(ReqTexto("{roto"), repo_factory=R, clave="").status_code == 200
    assert w.handle(ReqTexto(body, origin="https://evil.com"), repo_factory=R, clave="").status_code == 403


def test_contacto_guarda_origen_y_enlaza_visita():
    marcadas, preguntas = [], []
    class R(Repo):
        def marcar_lead(s, sid, tipo, i): marcadas.append((sid, tipo, i))
        def guardar_pregunta(s, d): preguntas.append(d)
    repo = R()
    st, b, _ = (lambda r: (r.status_code, json.loads(r.get_data()), None))(w.handle(
        Req(path="/contacto", body={"nombre": "Lucía", "telefono": "612345678", "t": 9000,
                                    "atribucion": {"sid": "abcdefghij12", "utm_source": "tiktok", "landing": "/contacto"}}),
        repo_factory=lambda: repo, clave=""))
    assert st == 200 and b["ok"]
    assert repo.creados[0]["attribution"]["fuente"] == "tiktok" and repo.creados[0]["attribution"]["landing"] == "/contacto/"
    assert marcadas == [("abcdefghij12", "contacto", "ID1")]
    w.handle(Req(path="/chat", body={"message": "¿cuánto cuesta? mi tel 612 345 678", "sid": "abcdefghij12"}),
             repo_factory=lambda: repo, clave="")
    assert preguntas and "612" not in preguntas[0]["texto"]


def test_contacto_guarda_gclid_de_google_ads():
    class R(Repo):
        def marcar_lead(s, *a): pass
    repo = R()
    w.handle(Req(path="/contacto", body={"nombre": "Ana", "telefono": "612345678", "t": 9000,
             "atribucion": {"sid": "abcdefghij12", "clid": "gclid", "clid_id": "Cj0KCQ<script>abc-_1"}}),
             repo_factory=lambda: repo, clave="")
    at = repo.creados[0]["attribution"]
    assert at["fuente"] == "google_ads" and at["gclid"] == "Cj0KCQscriptabc-_1"
