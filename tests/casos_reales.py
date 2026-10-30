"""Casos reales de Mudanzas del Sur para calibrar el motor (octubre 2026).
Cada caso es la solicitud tal como la habría rellenado el cliente en el formulario, los tramos
por carretera (km, min) Huelva→carga, carga→descarga, descarga→Huelva, y lo que cobró Alberto."""

def sol(casa=None, muebles=None, desmontaje="no", embalaje="yo", cajas=None, especiales=None,
        o_piso="bajo", o_asc=None, o_park="puerta", d_piso="bajo", d_asc=None, d_park="puerta", servicios=None, **extra):
    fk = {"casa": casa, "muebles": muebles or {}, "desmontaje": desmontaje, "embalaje": embalaje,
          "cajas": cajas, "especiales": especiales or [], "origin_piso": o_piso, "destin_piso": d_piso}
    job = {"formKeys": fk, "services": servicios or (["Mudanza completa"] if casa else ["Porte"]),
           "originElevator": o_asc, "destinElevator": d_asc,
           "originAccess": {"parking": o_park}, "destinAccess": {"parking": d_park}, "inventory": {}}
    job.update(extra)
    return job

# (nombre, solicitud, tramos, provincia, precio de Alberto, plan de Alberto, ¿cuenta para el precio?)
CASOS = [
    ("Francisco Javier", sol(muebles={"mesas": 1, "sillas": 6, "muebletv": 2, "comodas": 2}, embalaje="todo", cajas="30",
                             o_piso="1", o_asc=False, d_piso="1", d_asc=False),
     [(4.5, 6), (56.6, 41), (52.7, 42)], True, 400, "furgoneta, 3 personas", True),
    ("Tomás", sol(muebles={"frigorifico": 1, "armario4": 1, "muebletv": 1, "comodas": 1, "camas": 1}, desmontaje="si",
                  cajas="30", o_piso="2", o_asc=False, o_park="30", d_park="30"),
     [(48.3, 40), (2.0, 5), (47.4, 39)], True, 400, "furgoneta, 2 socios", True),
    ("Eugenio", sol(muebles={"armario2": 2, "armario4": 1, "comodas": 3, "mesascentro": 1, "sofas": 1, "camas": 1,
                             "colchones": 1, "bicis": 3}, cajas="30", d_piso="3", d_asc=False),
     [(255.8, 180), (256.6, 181), (3.0, 6)], False, 890, "camión, 3 personas", True),
    ("Juan", sol(casa="4", muebles={"sofas": 2, "mesascentro": 3, "muebletv": 3, "mesas": 1, "sillas": 10, "sillones": 1,
                                    "comodas": 13, "armario2": 2, "camas": 9, "escritorios": 2, "frigorifico": 1,
                                    "electro": 1, "tv": 2}, desmontaje="si", embalaje="todo", cajas="mas"),
     [(38.1, 38), (3.0, 6), (37.5, 37)], True, 1830, "2 días, 5 personas, un camión", True),
    ("Enrique (plan del presupuesto)", sol(muebles={"sofas": 1, "sillones": 4, "sillas": 7, "muebletv": 3, "comodas": 5,
                                                    "mesas": 2, "mesascentro": 4, "camas": 3, "colchones": 3, "jardin": 4},
                                           desmontaje="desmontar", cajas="30"),
     [(315.8, 220), (316.5, 222), (0.0, 0)], False, 1360, "camión + furgoneta, 3 personas", True),
    ("Manuel", sol(muebles={"comodas": 2, "sillas": 2, "mesascentro": 2, "electro": 12}, embalaje="todo", cajas="60",
                   o_piso="2", o_asc=False, o_park="30"),
     [(99.8, 94), (147.5, 125), (52.7, 42)], True, 920, "camión, 2 socios + 1 trabajador", True),
    ("Virginia", sol(muebles={"sofas": 5, "sillones": 2, "mesas": 1, "mesascentro": 1, "somieres": 5, "jardin": 1},
                     d_piso="3", d_asc=True),
     [(18.3, 21), (645.5, 425), (624.5, 405)], False, 1200, "furgoneta, socio + trabajador, 2 días", False),
    ("María Jesús", sol(casa="2", muebles={"sofas": 1, "canapes": 1, "colchones": 1, "mesas": 1, "sillas": 4, "muebletv": 1,
                                           "comodas": 7, "frigorifico": 1, "lavadora": 2, "electro": 1}, desmontaje="si",
                        cajas="30", especiales=["plantas"]),
     [(44.6, 40), (236.2, 173), (198.4, 149)], False, 710, "camión, 3 personas", False),
]
