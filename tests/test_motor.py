import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "functions"))
sys.path.insert(0, os.path.dirname(__file__))
import motor
import motor_app
from casos_reales import CASOS, sol

T = {"partnerHour": 20, "rent_furgoneta_200": 75}       # tarifas de la app en octubre 2026


def calc(job, legs, prov=False, **kw):
    e, _ = motor.entrada_desde_solicitud(job)
    return e, motor.calcular_presupuesto(e, legs, T, prov, **kw)


# ── Calibración con trabajos reales ──────────────────────────

def test_casos_reales_dentro_de_tolerancia():
    """Los casos que cuentan para el precio: ninguno a más del 15 % y la mayoría a menos del 10 %."""
    dentro, cuentan = 0, 0
    for nombre, job, legs, prov, precio, _plan, cuenta in CASOS:
        if not cuenta:
            continue
        _, r = calc(job, legs, prov)
        dif = abs(r["price"] / precio - 1)
        assert dif <= 0.15, f"{nombre}: motor {r['price']} € frente a {precio} €"
        cuentan += 1
        dentro += dif <= 0.10
    assert dentro >= cuentan - 1


def test_casos_reales_vehiculo_y_dias():
    esperado = {"Francisco Javier": ([("crafter", 1)], 1), "Tomás": ([("crafter", 1)], 1),
                "Eugenio": ([("iveco", 1)], 1), "Manuel": ([("iveco", 1)], 1),
                "Enrique (plan del presupuesto)": ([("iveco", 1), ("crafter", 1)], 1),
                "Juan": ([("iveco", 3)], 2), "Virginia": ([("iveco", 1)], 2)}
    for nombre, job, legs, prov, *_ in CASOS:
        if nombre in esperado:
            _, r = calc(job, legs, prov)
            assert (r["vehiculos"], r["dias"]) == esperado[nombre], nombre


def test_virginia_furgoneta_justa_y_dos_personas():
    nombre, job, legs, prov, *_ = next(c for c in CASOS if c[0] == "Virginia")
    _, r = calc(job, legs, prov)
    assert r["personas"] == 2 and r["noches"] == 1
    tipos = {a["tipo"]: a for a in r["alternativas"]}
    assert tipos["furgoneta_justa"]["price"] < r["price"] and tipos["un_socio"]["price"] < r["price"]


def test_juan_casa_grande_dos_jornadas():
    _, job, legs, prov, *_ = next(c for c in CASOS if c[0] == "Juan")
    _, r = calc(job, legs, prov)
    assert r["casa_grande"] and r["horas"] == 18 and r["personas"] == 5 and r["noches"] == 0


# ── Reglas sueltas ───────────────────────────────────────────

def test_determinista():
    _, job, legs, prov, *_ = CASOS[0]
    a = json.dumps(calc(job, legs, prov)[1], sort_keys=True)
    b = json.dumps(calc(job, legs, prov)[1], sort_keys=True)
    assert a == b


def test_plan_de_km_el_mas_barato():
    t = {**motor.DEFAULT_TARIFAS, **T}
    assert motor._plan_barato(t, "camion", 226, 1) == 200        # 133 + 26·0,22 < 150
    assert motor._plan_barato(t, "camion", 300, 1) == 400


def test_noche_por_habitacion_y_comida():
    job = sol(muebles={"sofas": 2})
    _, r = calc(job, [(18, 21), (640, 425), (620, 405)])
    assert r["noches"] == 1 and r["noche_eur"] == 80 + 35 * r["personas"]


def test_un_dia_fuera_de_provincia_si_es_sobre_todo_conduccion():
    c = motor.cfg()
    assert motor._dias({}, 4.5, 8.5, False, c) == 1          # 13 h, 8,5 de conducción: como Enrique
    assert motor._dias({}, 4.5, 8.5, True, c) == 2           # dentro de la provincia, máximo 12 h
    assert motor._dias({}, 3, 12, False, c) == 2             # 12 h solo de conducción: como Virginia


def test_aprovechando_salida_sale_mas_barato():
    job = sol(muebles={"lavadora": 1})
    _, r = calc(job, [(3, 6), (3, 6), (3, 6)], True, otro_trabajo_ese_dia=True)
    alt = next(a for a in r["alternativas"] if a["tipo"] == "aprovechando_salida")
    assert alt["price"] < r["price"]


def test_margen_de_la_furgoneta():
    c = motor.cfg()
    porte = {"tipo": "porte"}
    assert motor.vehiculos(porte, 8.5, 50, c) == [("crafter", 1)]
    assert motor.vehiculos(porte, 10, 50, c) == [("iveco", 1)]                 # más del 75 % de 12 m³
    assert motor.vehiculos(porte, 10, 50, c, forzar_furgoneta=True) == [("crafter", 1)]
    assert motor.vehiculos({"tipo": "casa"}, 42, 3, c) == [("iveco", 3)]        # mismo pueblo: un camión, varios viajes


def test_parametros_desde_tarifas():
    e, r1 = calc(sol(muebles={"sofas": 2}), [(10, 12), (20, 20), (15, 15)])
    r2 = motor.calcular_presupuesto(e, [(10, 12), (20, 20), (15, 15)], {**T, "motor": {"vol": {"sofa": 3.0}}})
    assert r2["m3"] > r1["m3"]


# ── Entrada y etiqueta ───────────────────────────────────────

def test_lee_solicitudes_antiguas_por_etiquetas():
    job = {"services": ["Mudanza completa"], "originFloor": "3º", "originElevator": False,
           "destinFloor": "Bajo / casa", "originAccess": {"parking": "100"},
           "inventory": {"casa": "2 dormitorios", "muebles": {"sofás": 2, "armario de 4 puertas": 1},
                         "embalaje": "lo embalamos nosotros (todo)", "cajas": "30 a 60",
                         "detalles": {"sofás": "de 3 plazas"}}}
    e, _ = motor.entrada_desde_solicitud(job)
    assert e["tipo"] == "casa" and e["casa"] == "2" and e["items"] == {"sofa": 2, "armario4": 1}
    assert e["embalaje"] == "todo" and e["cajas_respuesta"] == "45"        # tramo antiguo «30 a 60»
    assert e["origen"]["piso"] == 3 and e["origen"]["ascensor"] is False and e["origen"]["aparcamiento"] == "100"
    assert e["destino"]["piso"] == 0


def test_etiquetas():
    c = motor.cfg()
    legs = [(10, 12), (20, 20), (15, 15)]
    completa = sol(muebles={"sofas": 1, "camas": 1}, o_piso="2", o_asc=True, d_piso="bajo")
    e, r = calc(completa, legs)
    assert motor.revisar(e, legs, r, c)[0] == "lista"
    sin_piso = sol(muebles={"sofas": 1}, o_piso=None)
    sin_piso["originFloor"] = ""
    e, r = calc(sin_piso, legs)
    et, motivos, _ = motor.revisar(e, legs, r, c)
    assert et == "revisar" and any("piso" in m for m in motivos)
    e, r = calc(sol(muebles={"sofas": 1}, especiales=["piano"]), legs)
    assert motor.revisar(e, legs, r, c)[0] == "a_mano"
    e, _ = motor.entrada_desde_solicitud(sol())
    assert motor.revisar(e, legs, None, c)[0] == "a_mano"
    e, r = calc(sol(muebles={"sofas": 1}), [(18, 21), (645, 425), (624, 405)])
    assert motor.revisar(e, legs, r, c)[0] == "a_mano"        # más de 700 km


class RutasFalsas:
    def __init__(self):
        self.llamadas = 0

    def geocodificar(self, texto):
        self.llamadas += 1
        return {"Ayamonte": [37.2158, -7.406], "Huelva": [37.27, -6.95]}.get(texto.split(", ")[-1])

    def tramos(self, puntos):
        self.llamadas += 1
        return [(5, 7), (55, 42), (52, 42)]


def test_proponer_guarda_rutas_y_no_las_repite():
    job = sol(muebles={"mesas": 1, "sillas": 6}, originAddress="Río de la Plata 6, Huelva", destinAddress="Cuesta San Diego, Ayamonte")
    rutas = RutasFalsas()
    p1 = motor.proponer(job, T, rutas)
    assert p1["etiqueta"] == "lista" and p1["price"] > 0 and p1["rutas"]["legs"]
    n = rutas.llamadas
    p2 = motor.proponer({**job, "motorProposal": p1}, T, rutas)
    assert rutas.llamadas == n and p2["price"] == p1["price"]


def test_proponer_sin_direccion_va_a_mano():
    p = motor.proponer(sol(muebles={"sofas": 1}), T, RutasFalsas())
    assert p["etiqueta"] == "a_mano" and "price" not in p and any("dirección" in m for m in p["motivos"])


# ── Disparador (modo sombra) ─────────────────────────────────

def test_cuando_calcular():
    nueva = {"stage": "solicitud", "price": "", "date": ""}
    assert motor_app.debe_calcular(None, nueva)
    assert not motor_app.debe_calcular(nueva, {**nueva, "notes": "x"})              # su propia escritura u otro cambio
    assert motor_app.debe_calcular(nueva, {**nueva, "motorRecalc": "2026-10-30T20:00"})
    assert not motor_app.debe_calcular(None, {**nueva, "price": "300"})
    assert not motor_app.debe_calcular(None, {**nueva, "date": "2026-11-02"})
    assert not motor_app.debe_calcular(None, {**nueva, "stage": "aceptado"})


class RepoFalso:
    def __init__(self):
        self.guardado = {}

    def tarifas(self):
        return {**motor.DEFAULT_TARIFAS, **T}

    def hay_trabajo_con_vehiculo(self, fecha, excepto):
        return fecha == "2026-11-02"

    def guardar(self, doc_id, prop):
        self.guardado[doc_id] = prop


def test_procesar_no_toca_precio_ni_propuesta_de_claude():
    repo = RepoFalso()
    job = sol(muebles={"lavadora": 1}, originAddress="A, Huelva", destinAddress="B, Huelva",
              desiredDate="2026-11-02", stage="solicitud", price="", proposal={"price": 99})
    prop = motor_app.procesar("x1", None, job, repo, RutasFalsas())
    assert repo.guardado["x1"] is prop and set(repo.guardado) == {"x1"}
    assert any(a["tipo"] == "aprovechando_salida" for a in prop["alternativas"])


def test_calle_que_no_existe_calcula_desde_el_pueblo():
    class SoloPueblos(RutasFalsas):
        def geocodificar(self, texto):
            self.llamadas += 1
            return {"Huelva": [37.27, -6.95], "Aljaraque": [37.27, -7.02]}.get(texto)
    job = sol(muebles={"sofas": 1}, originAddress="Huelva", destinAddress="Avenida Inventada 5, Aljaraque")
    p = motor.proponer(job, T, SoloPueblos())
    assert p["etiqueta"] == "revisar" and p["price"] > 0
    assert any("centro de Aljaraque" in m for m in p["motivos"]) and not any(m.startswith("Sin ruta") for m in p["motivos"])


def _sin_listas_anidadas(x, dentro_de_lista=False):
    if isinstance(x, (list, tuple)):
        assert not dentro_de_lista, "Firestore no admite listas dentro de listas"
        return all(_sin_listas_anidadas(v, True) for v in x)
    if isinstance(x, dict):
        return all(_sin_listas_anidadas(v, False) for v in x.values())
    return True


def test_lo_que_se_guarda_cabe_en_firestore():
    """Firestore rechaza listas dentro de listas: así falló el primer recálculo real."""
    for nombre, job, legs, prov, *_ in CASOS:
        job = {**job, "originAddress": "A, Huelva", "destinAddress": "B, Ayamonte"}
        p = motor.proponer(job, T, RutasFalsas(), otro_trabajo_ese_dia=True)
        assert _sin_listas_anidadas(json.loads(json.dumps(p))), nombre
        p2 = motor.proponer({**job, "motorProposal": p}, T, RutasFalsas())
        assert p2.get("price") == p.get("price"), nombre


# ── Ajustes del banco de pruebas (30/10) ─────────────────────

def test_el_equipo_sale_de_lo_marcado_no_del_tamano_de_casa():
    """10/11: Alberto quita el mínimo de 6 personas por chalet; manda el volumen que hay que mover."""
    e, r = calc(sol(casa="chalet", muebles={"sofas": 3, "camas": 4, "armario4": 2}), [(30, 30), (20, 20), (30, 30)], True)
    e2, r2 = calc(sol(casa="2", muebles={"sofas": 3, "camas": 4, "armario4": 2}), [(30, 30), (20, 20), (30, 30)], True)
    assert r["personas"] == r2["personas"] < 6


def test_solo_tamano_de_casa_va_a_mano():
    p = motor.proponer(sol(casa="2", originAddress="A, Huelva", destinAddress="B, Ayamonte"), T, RutasFalsas())
    assert p["etiqueta"] == "a_mano" and "referencia" in p


def test_si_faltan_datos_sube_el_margen():
    base = sol(muebles={"sofas": 1, "camas": 1}, o_piso="2", o_asc=True, originAddress="A, Huelva", destinAddress="B, Ayamonte")
    sin_park = {**base, "originAccess": {}}
    p1 = motor.proponer(base, T, RutasFalsas())
    p2 = motor.proponer(sin_park, T, RutasFalsas())
    assert p1["etiqueta"] == "lista" and p2["etiqueta"] == "revisar"
    assert p2["result"]["business"] > p1["result"]["business"] and any("margen" in m for m in p2["motivos"])


def test_porte_pequeno_ofrece_precio_juntandolo():
    e, r = calc(sol(muebles={"lavadora": 1}), [(40, 40), (25, 20), (45, 40)], True)
    alt = next(a for a in r["alternativas"] if a["tipo"] == "aprovechando_salida")
    assert alt["price"] < r["price"] / 1.5


# ── Solo se presupuesta lo marcado (10/11) ───────────────────

def test_casa_solo_cuenta_lo_marcado():
    """Chalet con 11 m³ marcados: se presupuestan 11 m³, no los 42 de un chalet típico."""
    e = {"tipo": "casa", "casa": "chalet", "items": {"sofa": 2, "cama": 2, "armario4": 1, "mesa": 1, "silla": 6,
                                                    "frigorifico": 1, "lavadora": 1}}
    m3 = motor.volumen(e, motor.CONFIG)
    assert m3 == round(2 * 1.5 + 2 * 1.5 + 2.0 + 0.8 + 6 * 0.2 + 1.0 + 0.5, 1)


def test_casa_sin_nada_marcado_usa_el_tamano_solo_como_referencia():
    e = {"tipo": "casa", "casa": "3", "items": {}}
    assert motor.volumen(e, motor.CONFIG) == 28
    p = motor.proponer(sol(casa="3", originAddress="A, Huelva", destinAddress="B, Ayamonte"), T, RutasFalsas())
    assert p["etiqueta"] == "a_mano" and "price" not in p


# ── Lo que el cliente escribe a mano también se presupuesta (10/11) ─────

import lectura_ia  # noqa: E402
import motor_app  # noqa: E402


def _gem_falso(respuesta, llamadas=None):
    def gem(modelos, contents, clave, **kw):
        if llamadas is not None:
            llamadas.append(contents[0]["parts"][0]["text"])
        return respuesta
    return gem


def test_lectura_suma_lo_descrito_con_volumen_fijo():
    resp = ('{"objetos": [{"clave": "comoda", "cantidad": 2, "texto": "un par de cómodas"},'
            '{"clave": "cajonera", "cantidad": 3, "texto": "algunas cajoneras"},'
            '{"clave": "mesa_jardin", "cantidad": 1}, {"clave": "silla_jardin", "cantidad": 4},'
            '{"clave": "inventada", "cantidad": 2}], "dudas": ["¿la lavadora es la misma que la marcada?"]}')
    llamadas = []
    lec = lectura_ia.leer("un par de cómodas, algunas cajoneras…", {"sofa": 1}, "k", gem=_gem_falso(resp, llamadas),
                          modelos=["m"])
    assert lec["ok"] and lec["items"] == {"comoda": 2, "cajonera": 3, "mesa_jardin": 1, "silla_jardin": 4, "otro": 2}
    assert "sofá" in llamadas[0]                                   # la IA sabe lo que ya está marcado
    e = {"tipo": "casa", "casa": "chalet", "items": {"sofa": 1}}
    e2 = motor.con_lectura(e, lec)
    assert motor.volumen(e2, motor.CONFIG) == round(1.5 + 2 * 0.5 + 3 * 0.4 + 0.6 + 4 * 0.15 + 2 * 0.4, 1)


def test_lectura_rota_no_suma_y_avisa():
    lec = lectura_ia.leer("cosas", {}, "k", gem=_gem_falso("no es json"), modelos=["m"])
    assert lec["ok"] is False and lec["items"] == {}
    e = {"tipo": "porte", "items": {"sofa": 1}}
    assert motor.con_lectura(e, lec) == e


def test_texto_de_solicitud_antigua_sale_de_las_notas():
    job = {"formKeys": {"comentario": True}, "inventory": {"otros": "20 Caja"},
           "notes": "🏠 Casa: Chalet\n🛋 Muebles: 1 sofá\nfuera hay un par de cómodas y plantas\n📅 Fecha: 14/11\n"
                    "🌐 Llegó por la calculadora de la web"}
    assert lectura_ia.texto_de_solicitud(job) == "fuera hay un par de cómodas y plantas\nOtros muebles: 20 Caja"


def test_recalculo_reutiliza_la_lectura_si_el_texto_no_cambia():
    job = {"formKeys": {"comentario": "un par de cómodas"}, "inventory": {}}
    texto = lectura_ia.texto_de_solicitud(job)
    guardada = {"ok": True, "huella": lectura_ia.huella(texto), "items": {"comoda": 2}, "lineas": [], "dudas": []}
    llamadas = []
    leer = lambda t, i: llamadas.append(t) or {"ok": True, "items": {}}  # noqa: E731
    assert motor_app.lectura_para({**job, "motorProposal": {"lectura": guardada}}, leer) == guardada and not llamadas
    motor_app.lectura_para({**job, "formKeys": {"comentario": "tres cómodas"}, "motorProposal": {"lectura": guardada}}, leer)
    assert llamadas == ["tres cómodas"]


def test_propuesta_guarda_lo_leido_y_lo_explica():
    lec = {"ok": True, "huella": "x", "items": {"comoda": 2}, "lineas": ["2 × cómoda («un par de cómodas»)"], "dudas": []}
    p = motor.proponer(sol(muebles={"sofas": 1}, originAddress="A, Huelva", destinAddress="B, Ayamonte"), T,
                       RutasFalsas(), lectura=lec)
    assert p["lectura"]["items"] == {"comoda": 2}
    assert any(m.startswith("Sumado de lo que escribió el cliente (+1.0 m³)") for m in p["motivos"])


# ── Día de alquiler de más que sale casi gratis (11/11) ─────────────

def test_dia_de_alquiler_de_mas_si_sale_casi_igual():
    t = {**motor.DEFAULT_TARIFAS, "rent_furgoneta_200": 73, "rent_furgoneta_400": 88.3,
         "rent_camion_200": 133, "rent_camion_400": 150, "extraKm": 0.22}
    # Virginia: 2 días, ~1.300 km → 3 días por 0,30 € más (el 3.º queda libre)
    assert motor._alquiler(t, "furgoneta", 1300, 2, 5) == (400, 3, 0.3)
    assert motor._alquiler(t, "furgoneta", 1000, 2, 5)[:2] == (400, 2)       # +66 €: no compensa
    assert motor._alquiler(t, "camion", 1300, 2, 5)[:2] == (400, 2)          # el camión nunca compensa
    assert motor._alquiler(t, "furgoneta", 300, 1, 5)[:2] == (400, 1)        # sin km de más, nada


def test_vehiculo_libre_por_dia_de_alquiler_de_mas():
    virginia = ("v", {"date": "2026-11-09", "days": 2, "vehicles": [{"type": "crafter", "plan": 400}],
                      "estimate": {"vehicles": [{"type": "crafter", "plan": 400, "days": 3}]}})
    otro = ("o", {"date": "2026-11-12", "days": 1, "vehicles": [{"type": "iveco", "plan": 200}]})
    assert motor_app.vehiculo_ese_dia([virginia], "2026-11-10") == "trabajo"
    assert motor_app.vehiculo_ese_dia([virginia], "2026-11-11") == "alquiler"
    assert motor_app.vehiculo_ese_dia([virginia], "2026-11-12") is False
    assert motor_app.vehiculo_ese_dia([virginia, otro], "2026-11-12") == "trabajo"
    assert motor_app.vehiculo_ese_dia([virginia], "2026-11-11", excepto="v") is False


def test_alternativa_explica_el_vehiculo_libre():
    e, r = calc(sol(muebles={"sofas": 1}, originAddress="A, Huelva", destinAddress="B, Aljaraque"),
                [(10, 12), (12, 15), (14, 16)], True)
    r2 = motor.calcular_presupuesto(e, [(10, 12), (12, 15), (14, 16)], T, True, otro_trabajo_ese_dia="alquiler")
    alt = [a for a in r2["alternativas"] if a["tipo"] == "aprovechando_salida"][0]
    assert "vehículo alquilado libre" in alt["texto"]
