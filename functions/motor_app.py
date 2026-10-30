"""
El motor de presupuestos dentro de la app (modo sombra).

Cada vez que entra una solicitud nueva (o Alberto pulsa «Recalcular con el motor»), calcula la
propuesta y la guarda en `motorProposal`. No toca el precio, la etapa ni la propuesta de Claude
(`proposal`): las dos se ven juntas en la app hasta que el motor acierte seguido.

Distancias: con la variable GOOGLE_MAPS_KEY usa Google (Geocoding + Routes); sin ella, OpenStreetMap
(Nominatim + OSRM, que es gratis pero sin garantías). Los tramos se guardan en la solicitud y un
recálculo los reutiliza, así el precio no cambia si nadie cambia los datos.
"""
import os
from datetime import datetime, timezone

import motor
from mcp_escritura import DEFAULT_TARIFAS


def debe_calcular(antes, despues):
    """True si toca calcular: solicitud nueva sin fecha ni precio, o recálculo pedido desde la app."""
    if not despues or despues.get("date") or despues.get("price"):
        return False
    if (despues.get("stage") or "solicitud") != "solicitud":
        return False
    if antes is None:
        return True
    return (despues.get("motorRecalc") or "") != (antes.get("motorRecalc") or "")


class FirebaseMotorRepo:
    def __init__(self):
        from firebase_admin import firestore
        self._db = firestore.client()

    def tarifas(self):
        snap = self._db.collection("config").document("tarifas").get()
        return {**DEFAULT_TARIFAS, **(snap.to_dict() or {})} if snap.exists else dict(DEFAULT_TARIFAS)

    def hay_trabajo_con_vehiculo(self, fecha, excepto):
        if not fecha:
            return False
        for d in self._db.collection("trabajos").where("date", "==", fecha).limit(10).stream():
            j = d.to_dict() or {}
            if d.id != excepto and (j.get("vehicles") or j.get("vehicle")):
                return True
        return False

    def guardar(self, doc_id, prop):
        self._db.collection("trabajos").document(doc_id).set({"motorProposal": prop}, merge=True)


def procesar(doc_id, antes, despues, repo, rutas, ahora=None):
    if not debe_calcular(antes, despues):
        return None
    recalcular = antes is not None
    job = dict(despues)
    if recalcular:                                  # al recalcular a mano, las rutas se vuelven a pedir
        job.pop("motorProposal", None)
    otro = False
    try:
        otro = repo.hay_trabajo_con_vehiculo(despues.get("desiredDate"), doc_id)
    except Exception as e:  # noqa: BLE001
        print("motor otro trabajo:", repr(e))
    prop = motor.proponer(job, repo.tarifas(), rutas, otro_trabajo_ese_dia=otro, ahora=ahora)
    repo.guardar(doc_id, prop)
    return prop


try:
    from firebase_functions import firestore_fn, options

    @firestore_fn.on_document_written(document="trabajos/{doc_id}", region="europe-west1",
                                      memory=options.MemoryOption.MB_512, timeout_sec=120, max_instances=3)
    def motor_presupuesto(event: firestore_fn.Event[firestore_fn.Change]) -> None:
        cambio = event.data
        antes = cambio.before.to_dict() if cambio.before and cambio.before.exists else None
        despues = cambio.after.to_dict() if cambio.after and cambio.after.exists else None
        if not debe_calcular(antes, despues):
            return
        rutas = motor.Rutas(os.environ.get("GOOGLE_MAPS_KEY", "").strip())
        try:
            procesar(event.params["doc_id"], antes, despues, FirebaseMotorRepo(), rutas, datetime.now(timezone.utc))
        except Exception as e:  # noqa: BLE001
            print("motor_presupuesto error:", repr(e))
except ImportError:  # pruebas locales sin firebase_functions
    pass
