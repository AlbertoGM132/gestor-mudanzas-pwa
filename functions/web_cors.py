"""Qué webs pueden llamar a las funciones públicas (asistente, calculadora, solicitudes)."""
import re

_PERMITIDOS = [
    r"https://(www\.)?mudanzasdelsur\.es",
    r"https://presupuesto\.mudanzasdelsur\.es",
    r"https://mudanzas-del-sur(--[a-z0-9-]+)?\.(web\.app|firebaseapp\.com)",    # web y sus enlaces de prueba
    r"https://smartsonubalogictis(--[a-z0-9-]+)?\.(web\.app|firebaseapp\.com)",
    r"http://localhost(:\d+)?", r"http://127\.0\.0\.1(:\d+)?",
]
_RE = re.compile("^(" + "|".join(_PERMITIDOS) + ")$")


def origen_permitido(origin):
    return bool(origin) and bool(_RE.match(origin))


def cors_headers(origin):
    if not origen_permitido(origin):
        return {}
    return {"Access-Control-Allow-Origin": origin, "Vary": "Origin",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "3600"}
