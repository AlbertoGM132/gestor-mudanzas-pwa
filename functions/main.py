"""
Cloud Function: generar_presupuesto
- Recibe un JSON con los datos del presupuesto vía HTTP POST
- Genera el PDF con reportlab
- Lo sube a Firebase Storage
- Guarda el documento en Firestore (colección 'presupuestos')
- Devuelve la URL pública del PDF

Deploy:
  firebase deploy --only functions
"""
#comentario de prueba
import os, io, json, tempfile
from datetime import datetime
from firebase_functions import https_fn, options
from firebase_admin import initialize_app, storage, firestore, auth as fb_auth
import google.cloud.firestore

# ── ReportLab ──────────────────────────────────────────────
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas

initialize_app()

# Correos que pueden usar la app (los mismos que en firestore.rules y storage.rules)
EQUIPO = {"albertogmez99@gmail.com", "contactomudanzasdelsur@gmail.com"}


def usuario_del_equipo(req):
    """uid si la petición trae el token de sesión de alguien del equipo; si no, None."""
    cab = req.headers.get("Authorization", "")
    if not cab.startswith("Bearer "):
        return None
    try:
        tok = fb_auth.verify_id_token(cab[7:].strip())
    except Exception:
        return None
    return tok["uid"] if (tok.get("email") or "").lower() in EQUIPO else None

RED   = colors.HexColor("#C0392B")
GRAY  = colors.HexColor("#555555")
LGRAY = colors.HexColor("#AAAAAA")
BLACK = colors.HexColor("#222222")
WHITE = colors.white

PAGE_W, PAGE_H = A4

# ── Logo embebido en base64 (se carga desde el bucket) ──────
LOGO_STORAGE_PATH = "assets/logo.jpg"   # sube logo.jpg a Storage en esta ruta


def _fmt(value):
    try:
        return f"{float(value):,.2f}".replace(",","X").replace(".",",").replace("X",".")
    except Exception:
        return str(value)


def draw_presupuesto(c, data, logo_tmp_path=None):
    """Dibuja el presupuesto completo — mismo diseño que el modelo."""

    # Franjas rojas
    c.setFillColor(RED)
    c.rect(0, PAGE_H - 18*mm, PAGE_W, 18*mm, fill=1, stroke=0)
    c.rect(0, 0, PAGE_W, 10*mm, fill=1, stroke=0)

    # Logo
    if logo_tmp_path and os.path.exists(logo_tmp_path):
        c.drawImage(logo_tmp_path, PAGE_W - 58*mm, PAGE_H - 52*mm,
                    width=38*mm, height=28*mm, preserveAspectRatio=True, mask='auto')

    # Título
    c.setFont("Helvetica", 26)
    c.setFillColor(BLACK)
    c.drawString(20*mm, PAGE_H - 38*mm, "PRESUPUESTO")

    # Datos empresa
    emp = data.get("empresa", {})
    y = PAGE_H - 52*mm
    c.setFont("Helvetica-Bold", 9); c.setFillColor(BLACK)
    c.drawString(20*mm, y, emp.get("nombre", ""))
    y -= 5*mm
    c.setFont("Helvetica", 8.5); c.setFillColor(GRAY)
    for line in [emp.get("direccion",""), emp.get("ciudad",""),
                 emp.get("telefono",""), emp.get("email","")]:
        if line:
            c.drawString(20*mm, y, line)
            y -= 4.5*mm

    # Fecha
    fecha = data.get("fecha", datetime.today().strftime("%d/%m/%Y"))
    c.setFont("Helvetica-Bold", 9); c.setFillColor(BLACK)
    c.drawRightString(PAGE_W - 20*mm, PAGE_H - 57*mm, f"FECHA: {fecha}")
    c.setStrokeColor(LGRAY); c.setLineWidth(0.5)
    c.line(PAGE_W - 62*mm, PAGE_H - 59.5*mm, PAGE_W - 20*mm, PAGE_H - 59.5*mm)

    # Separador
    sep_y = PAGE_H - 78*mm
    c.setStrokeColor(LGRAY); c.setLineWidth(0.4)
    c.line(20*mm, sep_y, PAGE_W - 20*mm, sep_y)

    # Número de presupuesto
    num = data.get("numero", "")
    if num:
        c.setFont("Helvetica", 8); c.setFillColor(GRAY)
        c.drawRightString(PAGE_W - 20*mm, sep_y + 2*mm, f"Nº {num}")

    # Cliente
    y_cl = sep_y - 7*mm
    c.setFont("Helvetica-Bold", 9); c.setFillColor(RED)
    c.drawString(20*mm, y_cl, "CLIENTE")
    c.setStrokeColor(LGRAY)
    c.line(20*mm, y_cl - 1.5*mm, PAGE_W - 20*mm, y_cl - 1.5*mm)

    col_w = (PAGE_W - 40*mm) / 2
    clientes = data.get("clientes", [{}])
    for i, cli in enumerate(clientes[:2]):
        x_base = 20*mm + i * col_w
        yy = y_cl - 8*mm
        c.setFont("Helvetica-Bold", 9); c.setFillColor(BLACK)
        c.drawString(x_base, yy, cli.get("nombre", ""))
        yy -= 5*mm
        c.setFont("Helvetica", 8.5); c.setFillColor(GRAY)
        c.drawString(x_base, yy, cli.get("nif", ""))

    # Origen / Destino
    y_od = y_cl - 22*mm
    c.setStrokeColor(LGRAY); c.setLineWidth(0.4)
    c.line(20*mm, y_od + 4*mm, col_w + 20*mm - 5*mm, y_od + 4*mm)
    c.line(col_w + 20*mm, y_od + 4*mm, PAGE_W - 20*mm, y_od + 4*mm)
    c.setFont("Helvetica-Bold", 9); c.setFillColor(RED)
    c.drawString(20*mm, y_od, "Origen")
    c.drawString(col_w + 20*mm, y_od, "Destino")
    y_addr = y_od - 6*mm
    c.setFont("Helvetica", 8.5); c.setFillColor(BLACK)
    c.drawString(20*mm, y_addr, data.get("origen", ""))
    c.drawString(col_w + 20*mm, y_addr, data.get("destino", ""))

    # Tabla
    table_top  = y_addr - 10*mm
    table_left = 20*mm
    table_right= PAGE_W - 20*mm
    table_w    = table_right - table_left
    col_total_w= 28*mm
    row_h = 7*mm

    # Cabecera
    c.setFillColor(RED)
    c.rect(table_left, table_top - row_h, table_w, row_h, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 9); c.setFillColor(WHITE)
    c.drawString(table_left + 3*mm, table_top - row_h + 2.3*mm, "DESCRIPCIÓN")
    c.drawRightString(table_right - 2*mm, table_top - row_h + 2.3*mm, "TOTAL")

    lineas = list(data.get("lineas", []))
    while len(lineas) < 12:
        lineas.append({"descripcion": "", "total": ""})

    row_y = table_top - row_h
    for idx, linea in enumerate(lineas):
        row_y -= row_h
        if idx % 2 == 0:
            c.setFillColor(colors.HexColor("#FAFAFA"))
            c.rect(table_left, row_y, table_w, row_h, fill=1, stroke=0)
        c.setStrokeColor(colors.HexColor("#EEEEEE")); c.setLineWidth(0.3)
        c.line(table_left, row_y, table_right, row_y)
        desc  = str(linea.get("descripcion", ""))
        total = str(linea.get("total", ""))
        c.setFont("Helvetica", 8.5); c.setFillColor(BLACK)
        if desc:  c.drawString(table_left + 3*mm, row_y + 2.3*mm, desc[:80])
        if total: c.drawRightString(table_right - 2*mm, row_y + 2.3*mm, total)

    c.setStrokeColor(LGRAY); c.setLineWidth(0.4)
    c.line(table_right - col_total_w, table_top - row_h, table_right - col_total_w, row_y)
    c.setStrokeColor(LGRAY); c.setLineWidth(0.5)
    c.rect(table_left, row_y, table_w, table_top - row_y, fill=0, stroke=1)

    # Observaciones
    obs_list = data.get("observaciones", [
        "El precio puede variar si el volumen final excede lo estimado.",
        "Los embalajes especiales (piano, obras de arte, electrodomésticos de gran tamaño) se presupuestan aparte.",
        "El cliente debe indicar restricciones de acceso (calles estrechas, permisos de estacionamiento)."
    ])
    obs_y = row_y - 3*mm
    c.setFont("Helvetica-Bold", 8); c.setFillColor(BLACK)
    c.drawString(table_left, obs_y - 4*mm, "Observaciones importantes")
    c.setFont("Helvetica", 7.5); c.setFillColor(GRAY)
    obs_text_y = obs_y - 9*mm
    for obs in obs_list:
        words = obs.split()
        line_buf, lines_out = [], []
        for w in words:
            if len(" ".join(line_buf + [w])) > 68:
                lines_out.append(" ".join(line_buf)); line_buf = [w]
            else:
                line_buf.append(w)
        if line_buf: lines_out.append(" ".join(line_buf))
        for ln in lines_out:
            c.drawString(table_left + 2*mm, obs_text_y, f" {ln}")
            obs_text_y -= 4*mm

    # Totales
    subtotal  = float(data.get("subtotal", 0))
    usar_iva  = data.get("usar_iva", True)
    iva_pct   = float(data.get("iva_pct", 21))
    iva_val   = round(subtotal * iva_pct / 100, 2) if usar_iva else 0
    total_fin = round(subtotal + iva_val, 2)

    tot_label_x = PAGE_W - 82*mm
    tot_val_x   = PAGE_W - 20*mm
    tot_y = row_y - 6*mm

    def tot_row(label, value):
        nonlocal tot_y
        c.setFont("Helvetica", 8.5); c.setFillColor(BLACK)
        c.drawString(tot_label_x, tot_y, label)
        c.drawRightString(tot_val_x, tot_y, _fmt(value))
        c.setStrokeColor(LGRAY); c.setLineWidth(0.4)
        c.line(tot_label_x, tot_y - 1.8*mm, tot_val_x, tot_y - 1.8*mm)
        tot_y -= 8*mm

    tot_row("Subtotal", subtotal)
    if usar_iva:
        tot_row(f"IVA ({int(iva_pct)}%)", iva_val)

    tot_y -= 2*mm
    c.setStrokeColor(BLACK); c.setLineWidth(0.8)
    c.line(tot_label_x, tot_y + 2*mm, tot_val_x, tot_y + 2*mm)
    tot_y -= 5*mm

    c.setFont("Helvetica-Bold", 9.5); c.setFillColor(BLACK)
    c.drawString(tot_label_x, tot_y, "Cotización total")
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(tot_val_x, tot_y, _fmt(total_fin) + " \u20ac")

    c.save()


# ── CLOUD FUNCTION ──────────────────────────────────────────
@https_fn.on_request(
    cors=options.CorsOptions(cors_origins="*", cors_methods=["POST", "OPTIONS"]),
    memory=options.MemoryOption.MB_512,
    timeout_sec=60,
    region="europe-west1"   # elige la región más cercana a España
)
def generar_presupuesto(req: https_fn.Request) -> https_fn.Response:
    """
    POST /generar_presupuesto
    Body JSON: { data: {...}, uid: "...", guardar: true }
    Response:  { url: "https://...", docId: "..." }
    """
    if req.method == "OPTIONS":
        return https_fn.Response("", status=204)

    uid = usuario_del_equipo(req)
    if not uid:
        return https_fn.Response(json.dumps({"error": "No autorizado"}), status=401, mimetype="application/json")

    try:
        body = req.get_json(silent=True) or {}
        data = body.get("data", {})
        guardar = body.get("guardar", True)

        if not data:
            return https_fn.Response(
                json.dumps({"error": "No se recibieron datos"}),
                status=400, mimetype="application/json"
            )

        # ── Descargar logo desde Storage ──────────────────
        bucket = storage.bucket()
        logo_tmp = None
        try:
            blob = bucket.blob(LOGO_STORAGE_PATH)
            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            blob.download_to_filename(tmp.name)
            logo_tmp = tmp.name
        except Exception:
            pass  # sin logo si no existe

        # ── Generar PDF en memoria ────────────────────────
        pdf_buffer = io.BytesIO()
        c = rl_canvas.Canvas(pdf_buffer, pagesize=A4)
        draw_presupuesto(c, data, logo_tmp_path=logo_tmp)

        # ── Subir PDF a Storage ───────────────────────────
        fecha_str = datetime.today().strftime("%Y%m%d_%H%M%S")
        cliente_slug = (data.get("clientes", [{}])[0]
                        .get("nombre", "cliente")
                        .replace(" ", "_")[:30])
        storage_path = f"presupuestos/{uid}/{fecha_str}_{cliente_slug}.pdf"

        pdf_buffer.seek(0)
        blob_pdf = bucket.blob(storage_path)
        blob_pdf.upload_from_file(pdf_buffer, content_type="application/pdf")
        blob_pdf.make_public()
        pdf_url = blob_pdf.public_url

        # ── Guardar en Firestore ──────────────────────────
        doc_id = None
        if guardar:
            db = firestore.client()
            doc_ref = db.collection("presupuestos").add({
                "uid":         uid,
                "cliente":     data.get("clientes", [{}])[0].get("nombre", ""),
                "origen":      data.get("origen", ""),
                "destino":     data.get("destino", ""),
                "subtotal":    data.get("subtotal", 0),
                "usar_iva":    data.get("usar_iva", True),
                "iva_pct":     data.get("iva_pct", 21),
                "total":       round(float(data.get("subtotal", 0)) *
                               (1 + float(data.get("iva_pct", 21))/100
                               if data.get("usar_iva", True) else 1), 2),
                "pdfUrl":      pdf_url,
                "storagePath": storage_path,
                "fecha":       data.get("fecha", datetime.today().strftime("%d/%m/%Y")),
                "data":        data,
                "creadoEn":    firestore.SERVER_TIMESTAMP
            })
            doc_id = doc_ref[1].id

        # Limpiar logo temporal
        if logo_tmp and os.path.exists(logo_tmp):
            os.unlink(logo_tmp)

        return https_fn.Response(
            json.dumps({"url": pdf_url, "docId": doc_id}),
            status=200, mimetype="application/json"
        )

    except Exception as e:
        return https_fn.Response(
            json.dumps({"error": str(e)}),
            status=500, mimetype="application/json"
        )


# ── Conector MCP para Claude (solo lectura) ───────────────
# Firebase solo despliega las funciones visibles en main.py
from mcp_mudanzapro import mudanzapro_mcp  # noqa: E402,F401

# ── Formulario público «Pide tu presupuesto» (/presupuesto) ──
from formulario_web import solicitud_publica  # noqa: E402,F401
