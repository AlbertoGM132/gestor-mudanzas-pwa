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
    assert e["embalaje"] == "todo" and e["cajas_respuesta"] == "60"
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
