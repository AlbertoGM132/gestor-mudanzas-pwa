import io, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "functions"))
import mcp_mudanzapro as m


class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_despertar_hace_sesion_mcp_real():
    vistos = []
    def abrir(req):
        vistos.append(req)
        st, body = m.handle_http("POST", "/", req.data, "clave", lambda: None, dict(req.header_items()))
        assert st == 200
        return Resp(body.encode())
    n = m.despertar(m.url_conector("proyecto"), "clave", abrir=abrir)
    assert n == len(m.TOOLS) > 0
    assert vistos[0].full_url == "https://europe-west1-proyecto.cloudfunctions.net/mudanzapro_mcp"


def test_despertar_reintenta_si_falla():
    llamadas = []
    def abrir(req):
        llamadas.append(1)
        if len(llamadas) < 3:
            raise TimeoutError("arranque en frío")
        st, body = m.handle_http("POST", "/", req.data, "clave", lambda: None, dict(req.header_items()))
        return Resp(body.encode())
    assert m.despertar("https://x", "clave", abrir=abrir) > 0 and len(llamadas) == 3


def test_despertar_con_clave_mala_devuelve_cero():
    def abrir(req):
        st, body = m.handle_http("POST", "/", req.data, "otra", lambda: None, dict(req.header_items()))
        return Resp((body or "").encode())
    assert m.despertar("https://x", "clave", abrir=abrir, intentos=2) == 0


def test_cron_cubre_las_tareas():
    minutos, horas = m.DESPERTAR_CRON.split()[:2]
    assert set(minutos.split(",")) == {"43", "49"} and horas == "6-20"
