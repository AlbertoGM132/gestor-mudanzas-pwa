"""
Lee con IA lo que el cliente escribe a mano (comentario y «otros muebles») y lo convierte en objetos
con su volumen fijo de la tabla del motor. Regla de Alberto: lo que se describe para llevar también se
presupuesta; lo que no aparece ni marcado ni descrito no se mueve.

La lectura se guarda en la propuesta (`motorProposal.lectura`) con la huella del texto: si el texto no
cambia, un recálculo la reutiliza y no vuelve a llamar a la IA (el precio no baila).
"""
import hashlib
import re

import motor

# Objetos que la IA puede devolver: clave del motor → cómo se llama (el volumen sale de motor.CONFIG["vol"])
OBJETOS = {
    "sofa": "sofá de 3 plazas o más", "sofa_pequeno": "sofá de 2 plazas", "sillon": "sillón o butaca",
    "chaise": "sofá con chaise longue", "cama": "cama de matrimonio (estructura)", "cama_individual": "cama individual",
    "canape": "canapé", "somier": "somier", "colchon": "colchón", "cuna": "cuna",
    "armario2": "armario de 2 puertas", "armario4": "armario de 3-4 puertas", "armario6": "armario de 5-6 puertas",
    "comoda": "cómoda o sinfonier", "cajonera": "cajonera", "mesita": "mesita de noche",
    "mesa": "mesa de comedor", "mesa_pequena": "mesa baja o de centro", "mesa_jardin": "mesa de jardín",
    "silla": "silla", "silla_jardin": "silla o tumbona de jardín", "jardin": "conjunto o mueble de jardín",
    "aparador": "aparador, vitrina o mueble de TV", "estanteria": "estantería o librería", "escritorio": "escritorio",
    "frigorifico": "frigorífico", "lavadora": "lavadora", "secadora": "secadora", "lavavajillas": "lavavajillas",
    "electro": "otro electrodoméstico grande (horno, microondas, aire acondicionado…)", "televisor": "televisor",
    "bici": "bicicleta o patinete", "barbacoa": "barbacoa", "planta": "planta o maceta grande",
    "caja": "caja de mudanza (también bolsas grandes, juguetes, ropa o cosas sueltas convertidas a cajas)",
    "maleta": "maleta", "otro": "cualquier otro bulto mediano",
}

SISTEMA = """Eres el ayudante de presupuestos de una empresa de mudanzas de Huelva.
El cliente ya ha MARCADO una lista de cosas. Además ha escrito un texto libre. Tu trabajo: sacar del texto
SOLO las cosas que hay que llevar y que NO estén ya en la lista marcada, con su cantidad.

Reglas:
- No repitas lo que ya está marcado. Si el texto describe cosas ya marcadas (por ejemplo «dentro hay lavadora,
  cama y sofá» y ya están en la lista), no las sumes. Ante la duda de si es lo mismo, NO lo sumes y ponlo en «dudas».
- No sumes lo que el texto dice que se queda, se tira, ya se ha llevado o no hay que mover.
- Ignora lo que no son objetos: accesos, escaleras, horarios, fechas, aparcamiento, quién embala.
- Cantidades vagas: «un par» = 2, «unos/unas/algunos/varios» = 3, «muchos» = 5. Si dice un número, úsalo.
- Bolsas grandes, juguetes, ropa, menaje u objetos sueltos: conviértelos a cajas (1 bolsa grande = 1 caja;
  «juguetes» o «cosas» sin número = 3 cajas).
- Usa solo estas claves de objeto: {claves}. Si no encaja en ninguna, usa «otro».
- Cantidad máxima por línea: 60.

Responde SOLO con JSON:
{{"objetos": [{{"clave": "comoda", "cantidad": 2, "texto": "un par de cómodas"}}],
  "dudas": ["frase corta sobre algo que no está claro si va o ya está marcado"]}}
Si no hay nada que sumar: {{"objetos": [], "dudas": []}}"""

# Líneas que la app escribe en las notas (no son el comentario del cliente)
_NOTA_APP = re.compile(r"^\s*(🏠|🛋|🔧|📦|📅|🧮|🌐|📷|🚚|⚠️|Carga:|Descarga:|Casa:|Muebles:)")


def huella(texto):
    return hashlib.sha1((texto or "").strip().encode()).hexdigest()[:16]


def texto_de_solicitud(job):
    """Lo escrito a mano por el cliente: comentario (o, en solicitudes antiguas, las notas que no
    escribió la app) + «otros muebles» del inventario."""
    job = job or {}
    keys = job.get("formKeys") if isinstance(job.get("formKeys"), dict) else {}
    inv = job.get("inventory") if isinstance(job.get("inventory"), dict) else {}
    partes = []
    com = keys.get("comentario")
    if isinstance(com, str) and com.strip():
        partes.append(com.strip())
    elif com:                                           # antes solo se guardaba si había comentario
        notas = [ln for ln in str(job.get("notes") or "").split("\n") if ln.strip() and not _NOTA_APP.match(ln)]
        if notas:
            partes.append("\n".join(notas))
    otros = str(inv.get("otros") or "").strip()
    if otros:
        partes.append("Otros muebles: " + otros)
    return "\n".join(partes).strip()


def _marcados_txt(items):
    return ", ".join(f"{n} × {OBJETOS.get(k, k)}" for k, n in items.items()) or "(nada)"


# Frases que añade la calculadora (no las escribe el cliente; lo que dicen ya está en la lista)
_AUTO = re.compile(r"^La IA vio \d+ cajas.*$", re.M)


def leer(texto, items_marcados, clave, gem=None, modelos=None):
    """Devuelve {"ok", "huella", "items": {clave: n}, "lineas": [...], "dudas": [...]}. Nunca lanza."""
    base = {"ok": False, "huella": huella(texto), "items": {}, "lineas": [], "dudas": []}
    texto = _AUTO.sub("", texto or "").strip()
    if not (texto or "").strip():
        return {**base, "ok": True}
    try:
        from web_ia import MODELOS_CHAT, _json_de_texto, gemini
        gem, modelos = gem or gemini, modelos or MODELOS_CHAT
        sistema = SISTEMA.format(claves=", ".join(OBJETOS))
        pregunta = f"Lista ya marcada: {_marcados_txt(items_marcados)}\n\nTexto del cliente:\n{texto[:2500]}"
        crudo = gem(modelos, [{"role": "user", "parts": [{"text": pregunta}]}], clave, system=sistema,
                    config={"temperature": 0, "responseMimeType": "application/json"}, timeout=20)
        data = _json_de_texto(crudo)
    except Exception as e:  # noqa: BLE001 (sin clave, IA caída, JSON roto)
        print("lectura_ia:", repr(e))
        return base
    items, lineas = {}, []
    for o in (data.get("objetos") or [])[:40]:
        if not isinstance(o, dict):
            continue
        k = o.get("clave") if o.get("clave") in OBJETOS else "otro"
        try:
            n = max(0, min(60, int(o.get("cantidad") or 0)))
        except (TypeError, ValueError):
            continue
        if n:
            items[k] = items.get(k, 0) + n
            lineas.append(f"{n} × {OBJETOS[k].split(' (')[0]}"
                          + (f" («{str(o.get('texto'))[:50]}»)" if o.get("texto") else ""))
    dudas = [str(d)[:140] for d in (data.get("dudas") or [])[:5] if str(d).strip()]
    return {**base, "ok": True, "items": items, "lineas": lineas, "dudas": dudas}


def m3(items, c=None):
    c = c or motor.CONFIG
    return round(sum(c["vol"].get(k, c["vol"]["otro"]) * n for k, n in (items or {}).items()), 1)
