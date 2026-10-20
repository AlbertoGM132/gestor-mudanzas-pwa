"""
Panel de seguimiento del negocio (app aparte, sitio de hosting «panel»).

  POST /api/panel   {accion, ...}   con el token de sesión de alguien del equipo
     resumen          {desde, hasta}                 todo el periodo + comparación con el anterior
     sesiones         {desde, hasta, fuente, solo_contactos}   recorridos de visitas concretas
     informes         {}                             últimos informes semanales
     generar_informe  {desde, hasta}                 genera un informe ahora (IA)
     asignar_origen   {id, origen}                   apunta de dónde vino una solicitud
     guardar_redes    {red, dias, publicaciones}     métricas de redes a mano
     enlace           {url, fuente, medio, campana, contenido}   enlace con etiqueta UTM

  informe_semanal   cada lunes a las 7:30 (Madrid): informe de la semana con IA + aviso al móvil
"""
import json
import os

import analitica as an

# Los mismos correos que EQUIPO en main.py y en firestore.rules
EQUIPO = {"albertogmez99@gmail.com", "contactomudanzasdelsur@gmail.com"}
MODELOS_INFORME = [m.strip() for m in os.environ.get(
    "GEMINI_MODELOS_INFORME", "gemini-3.6-flash,gemini-3.8-flash,gemini-3.5-flash-lite").split(",") if m.strip()]


class PanelError(Exception):
    def __init__(self, status, mensaje):
        super().__init__(mensaje)
        self.status, self.mensaje = status, mensaje


def usuario(req, verificar=None):
    """Email si la petición trae el token de alguien del equipo; si no, None."""
    cab = req.headers.get("Authorization", "")
    if not cab.startswith("Bearer "):
        return None
    try:
        if verificar is None:
            from firebase_admin import auth as fb_auth
            verificar = fb_auth.verify_id_token
        tok = verificar(cab[7:].strip())
    except Exception:
        return None
    email = (tok.get("email") or "").lower()
    # Igual que MudanzaPro (main.py y firestore.rules): basta con que el correo sea del equipo.
    # Las cuentas de email y contraseña no tienen el correo «verificado», así que no se exige.
    return email if email in EQUIPO else None


def accion(body, quien, repo, gem=None, clave=""):
    body = body if isinstance(body, dict) else {}
    a = body.get("accion")
    try:
        if a == "resumen":
            return an.resumen(repo, body.get("desde"), body.get("hasta"))
        if a == "sesiones":
            return an.sesiones_detalle(repo, body.get("desde"), body.get("hasta"), body.get("fuente") or None,
                                       bool(body.get("solo_contactos")), body.get("limite") or 40)
        if a == "informes":
            return {"informes": repo.informes(8)}
        if a == "generar_informe":
            if gem is None:
                from web_ia import gemini as gem
            return an.generar_informe(repo, gem, clave, MODELOS_INFORME, body.get("desde"), body.get("hasta"))
        if a == "asignar_origen":
            origen = body.get("origen")
            if origen not in an.ORIGENES_MANUALES:
                raise PanelError(400, "Origen no válido.")
            repo.asignar_origen(str(body.get("id") or ""), origen, quien)
            return {"ok": True}
        if a == "guardar_redes":
            return an.guardar_redes(body, repo)
        if a == "enlace":
            return {"url": an.enlace_utm(body.get("url") or "/", body.get("fuente"), body.get("medio"),
                                         body.get("campana"), body.get("contenido"))}
    except ValueError as e:
        raise PanelError(400, str(e))
    raise PanelError(404, "Acción desconocida.")


def handle(req, repo_factory=None, verificar=None, gem=None, clave=None):
    from firebase_functions import https_fn

    def resp(obj, status=200):
        return https_fn.Response(json.dumps(obj, ensure_ascii=False, default=str), status=status,
                                 mimetype="application/json", headers={"Cache-Control": "no-store"})

    if req.method != "POST":
        return resp({"ok": False, "error": "No permitido."}, 405)
    quien = usuario(req, verificar)
    if not quien:
        return resp({"ok": False, "error": "Inicia sesión con una cuenta del equipo."}, 401)
    try:
        repo = (repo_factory or an.FirebaseAnaliticaRepo)()
        clave = clave if clave is not None else os.environ.get("GEMINI_KEY", "").strip()
        return resp(accion(req.get_json(silent=True), quien, repo, gem, clave))
    except PanelError as e:
        return resp({"ok": False, "error": e.mensaje}, e.status)
    except Exception as e:  # noqa: BLE001
        print("panel_api error:", repr(e))
        return resp({"ok": False, "error": "Algo ha fallado al calcular los datos."}, 500)


try:
    from firebase_functions import https_fn, options, scheduler_fn

    @https_fn.on_request(region="europe-west1", memory=options.MemoryOption.MB_512, timeout_sec=120,
                         max_instances=2, secrets=["GEMINI_KEY"])
    def panel_api(req: https_fn.Request) -> https_fn.Response:
        return handle(req)

    @scheduler_fn.on_schedule(schedule="30 7 * * 1", timezone=scheduler_fn.Timezone("Europe/Madrid"),
                              region="europe-west1", memory=options.MemoryOption.MB_512, timeout_sec=300,
                              secrets=["GEMINI_KEY"])
    def informe_semanal(event: scheduler_fn.ScheduledEvent) -> None:
        from web_ia import gemini
        repo = an.FirebaseAnaliticaRepo()
        doc = an.generar_informe(repo, gemini, os.environ.get("GEMINI_KEY", "").strip(), MODELOS_INFORME)
        try:
            import formulario_web as fw
            fw.FirebaseFormRepo().avisar("📊 Informe semanal listo", (doc["informe"].get("titular") or "")[:180])
        except Exception as e:  # noqa: BLE001
            print("informe_semanal aviso:", repr(e))
except ImportError:  # pruebas locales sin firebase_functions
    pass
