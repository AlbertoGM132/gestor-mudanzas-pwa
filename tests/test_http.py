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
