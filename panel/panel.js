// Panel del negocio · Mudanzas del Sur
// Lee los datos ya calculados de la función panel_api (mismo proyecto que MudanzaPro).
import { initializeApp } from "https://www.gstatic.com/firebasejs/11.6.0/firebase-app.js";
import { getAuth, signInWithEmailAndPassword, signOut, onAuthStateChanged }
  from "https://www.gstatic.com/firebasejs/11.6.0/firebase-auth.js";

const firebaseConfig = {
  apiKey: "AIzaSyBW-DXKRKumti5YDyFCqOHgWHAKYK-6AtQ",
  authDomain: "smartsonubalogictis.firebaseapp.com",
  projectId: "smartsonubalogictis",
  storageBucket: "smartsonubalogictis.firebasestorage.app",
  messagingSenderId: "692783709731",
  appId: "1:692783709731:web:f2cb16afd96e45abed7b96",
};
const EQUIPO = ["albertogmez99@gmail.com", "contactomudanzasdelsur@gmail.com"];
// Solo en local: ?demo enseña datos de ejemplo sin iniciar sesión (para probar el diseño)
const DEMO = ["localhost", "127.0.0.1"].includes(location.hostname) && new URLSearchParams(location.search).has("demo");

const auth = DEMO ? null : getAuth(initializeApp(firebaseConfig));
const $ = (id) => document.getElementById(id);
const nf = new Intl.NumberFormat("es-ES");
const eur = new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const pct = (v) => (v == null ? "—" : `${nf.format(v)} %`);
const n = (v) => (v == null ? "—" : nf.format(v));
const diaFmt = new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "short" });
const diaLargo = new Intl.DateTimeFormat("es-ES", { weekday: "short", day: "numeric", month: "short" });

const guardar = (k, v) => { try { localStorage.setItem("panel." + k, v); } catch {} };
const leer = (k, d) => { try { return localStorage.getItem("panel." + k) ?? d; } catch { return d; } };

const estado = { tab: leer("tab", "resumen"), preset: leer("preset", "28"), desde: "", hasta: "", R: null, informes: null };

// ── DOM seguro (los textos que vienen de datos van siempre como texto, nunca como HTML) ──
function h(tag, props = {}, ...hijos) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of hijos.flat()) if (c != null && c !== false) e.append(c instanceof Node ? c : String(c));
  return e;
}
const card = (titulo, sub, ...cuerpo) => h("article", { class: "card" }, h("h2", { text: titulo }), sub ? h("p", { class: "sub", text: sub }) : null, h("div", { class: "cuerpo" }, ...cuerpo));
const vacio = (t) => h("p", { class: "vacio", text: t });
function toast(t) { const e = h("div", { class: "toast", role: "status", text: t }); document.body.append(e); setTimeout(() => e.remove(), 2600); }

// ── API ──
async function api(accion, cuerpo = {}) {
  if (DEMO) {
    const r = await fetch(`/__demo/${accion}.json`);
    return r.ok ? r.json() : {};
  }
  const token = await auth.currentUser.getIdToken();
  const r = await fetch("/api/panel", { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ accion, ...cuerpo }) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok || data.ok === false) throw new Error(data.error || `Error ${r.status}`);
  return data;
}

// ── Fechas ──
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
function calcularRango(p) {
  const hoy = new Date();
  if (p === "mes") return [iso(new Date(hoy.getFullYear(), hoy.getMonth(), 1)), iso(hoy)];
  if (p === "mes-1") return [iso(new Date(hoy.getFullYear(), hoy.getMonth() - 1, 1)), iso(new Date(hoy.getFullYear(), hoy.getMonth(), 0))];
  const dias = Number(p) || 28;
  const d = new Date(hoy); d.setDate(d.getDate() - dias + 1);
  return [iso(d), iso(hoy)];
}
function diasEntre(a, b) {
  const out = []; const d = new Date(a + "T12:00:00"); const fin = new Date(b + "T12:00:00");
  while (d <= fin && out.length < 400) { out.push(iso(d)); d.setDate(d.getDate() + 1); }
  return out;
}

// ── Gráficos (una serie, un color; valores siempre visibles o en tabla) ──
function barras(filas, { valor, etiqueta, extra, max, fmt = n } = {}) {
  if (!filas.length) return vacio("Sin datos en este periodo.");
  const tope = max ?? Math.max(...filas.map(valor), 1);
  return h("div", { class: "barras" }, filas.map((f) => {
    const v = valor(f);
    return h("div", { class: "barra", title: `${etiqueta(f)}: ${fmt(v)}` },
      h("span", { class: "n", text: etiqueta(f) }),
      h("span", { class: "t", "aria-hidden": "true" }, h("i", { style: `width:${Math.max(0, Math.min(100, (100 * v) / tope))}%` })),
      h("span", { class: "v" }, fmt(v), extra ? h("small", { text: extra(f) }) : null));
  }));
}

function linea(puntos, { valor, etiqueta, detalle }) {
  const caja = h("div", { class: "linea" });
  const dibujar = () => {
    caja.replaceChildren();
    const W = Math.max(280, caja.clientWidth || 600), H = 220, pl = 34, pr = 10, pt = 12, pb = 26;
    const vals = puntos.map(valor), max = Math.max(4, ...vals);
    const paso = Math.pow(10, Math.floor(Math.log10(max))); const tope = Math.ceil(max / paso) * paso;
    const x = (i) => pl + (puntos.length < 2 ? 0 : (i * (W - pl - pr)) / (puntos.length - 1));
    const y = (v) => pt + (H - pt - pb) * (1 - v / tope);
    const ns = "http://www.w3.org/2000/svg";
    const s = (tag, a) => { const e = document.createElementNS(ns, tag); for (const k in a) e.setAttribute(k, a[k]); return e; };
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Gráfico por día" });
    for (let k = 0; k <= 4; k++) {
      const v = (tope * k) / 4, yy = y(v);
      svg.append(s("line", { x1: pl, x2: W - pr, y1: yy, y2: yy, class: "grid-l" }));
      const t = s("text", { x: pl - 6, y: yy + 4, "text-anchor": "end", class: "eje" }); t.textContent = nf.format(Math.round(v)); svg.append(t);
    }
    const cada = Math.ceil(puntos.length / Math.max(2, Math.floor((W - pl) / 70)));
    puntos.forEach((p, i) => {
      if (i % cada && i !== puntos.length - 1) return;
      const t = s("text", { x: x(i), y: H - 6, "text-anchor": i === 0 ? "start" : i === puntos.length - 1 ? "end" : "middle", class: "eje" });
      t.textContent = etiqueta(p); svg.append(t);
    });
    const d = puntos.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(valor(p)).toFixed(1)}`).join("");
    if (puntos.length) {
      svg.append(s("path", { d: `${d}L${x(puntos.length - 1)},${y(0)}L${x(0)},${y(0)}Z`, class: "area" }));
      svg.append(s("path", { d, class: "serie" }));
    }
    const cruz = s("line", { y1: pt, y2: H - pb, class: "cruz", visibility: "hidden" });
    const punto = s("circle", { r: 4.5, class: "punto", visibility: "hidden" });
    svg.append(cruz, punto);
    const tip = h("div", { class: "tip", hidden: true });
    const mover = (cx) => {
      const r = svg.getBoundingClientRect(); const px = ((cx - r.left) / r.width) * W;
      const i = Math.max(0, Math.min(puntos.length - 1, Math.round(((px - pl) / (W - pl - pr)) * (puntos.length - 1))));
      const p = puntos[i]; if (!p) return;
      cruz.setAttribute("x1", x(i)); cruz.setAttribute("x2", x(i)); punto.setAttribute("cx", x(i)); punto.setAttribute("cy", y(valor(p)));
      cruz.setAttribute("visibility", "visible"); punto.setAttribute("visibility", "visible");
      tip.hidden = false; tip.replaceChildren(h("span", { class: "k" }), h("b", { text: n(valor(p)) }), " ", detalle(p));
      tip.style.left = `${(x(i) / W) * 100}%`; tip.style.top = `${(y(valor(p)) / H) * 100}%`;
    };
    svg.addEventListener("pointermove", (e) => mover(e.clientX));
    svg.addEventListener("pointerleave", () => { tip.hidden = true; cruz.setAttribute("visibility", "hidden"); punto.setAttribute("visibility", "hidden"); });
    caja.append(svg, tip);
  };
  requestAnimationFrame(dibujar);
  new ResizeObserver(() => { clearTimeout(caja._t); caja._t = setTimeout(dibujar, 120); }).observe(caja);
  return caja;
}

function tabla(cols, filas) {
  if (!filas.length) return vacio("Sin datos en este periodo.");
  return h("div", { class: "tabla-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, cols.map((c) => h("th", { class: c.num ? "num" : null, scope: "col", text: c.t })))),
    h("tbody", {}, filas.map((f) => h("tr", {}, cols.map((c) => { const v = c.v(f); return h("td", { class: c.num ? "num" : null }, v instanceof Node ? v : String(v ?? "—")); }))))));
}

// ── Nombres legibles ──
const SECCIONES = { inicio: "Portada", ventajas: "Por qué nosotros", "como-funciona": "Cómo funciona", servicios: "Servicios", calculadora: "Promo de la calculadora",
  nosotros: "Nuestra historia", opiniones: "Opiniones", preguntas: "Preguntas frecuentes", contacto: "Contacto" };
const CLICS = { whatsapp: "WhatsApp", llamar: "Llamar", email: "Email", calculadora: "Ir a la calculadora", instagram: "Instagram", tiktok: "TikTok", facebook: "Facebook", mapa: "Mapa", otro: "Otros" };
const REDES = { instagram: "Instagram", tiktok: "TikTok", facebook: "Facebook", google_perfil: "Perfil de Google", google_ads: "Google Ads", meta_ads: "Anuncios de Meta" };
const METRICAS = { seguidores: "Seguidores", alcance: "Alcance", visualizaciones: "Visualizaciones", interacciones: "Interacciones", nuevos_seguidores: "Nuevos seguidores",
  clics_web: "Clics a la web", publicaciones: "Publicaciones", me_gusta: "Me gusta", comentarios: "Comentarios", guardados: "Guardados", compartidos: "Compartidos",
  llamadas: "Llamadas", como_llegar: "Cómo llegar", busquedas: "Búsquedas", impresiones: "Impresiones", clics: "Clics", coste: "Coste (€)", conversiones: "Conversiones" };
const ORIGENES = [["instagram", "Instagram"], ["tiktok", "TikTok"], ["facebook", "Facebook"], ["google_ads", "Google Ads"], ["google_perfil", "Perfil de Google"],
  ["google", "Google (búsqueda)"], ["whatsapp", "WhatsApp"], ["boca_a_boca", "Boca a boca"], ["repetidor", "Cliente que repite"], ["telefono", "Llamada"],
  ["offline", "Flyers, QR y vehículos"], ["otras_webs", "Otras webs"], ["directo", "Directo"]];
const ETAPAS = { solicitud: "Solicitud", presupuestado: "Presupuestado", aceptado: "Aceptado", programado: "Programado", completado: "Hecho", perdido: "Perdido" };
const nombreDia = (d) => diaFmt.format(new Date(d + "T12:00:00"));

function kpi(etiqueta, k, fmt = n) {
  const d = k?.cambio_pct;
  if (k?.antes === undefined) return h("div", { class: "kpi" }, h("div", { class: "l", text: etiqueta }), h("div", { class: "v", text: fmt(k?.ahora ?? 0) }));
  const txt = d == null ? (k?.antes === 0 && k?.ahora ? "nuevo respecto al periodo anterior" : "sin datos del periodo anterior")
    : `${d > 0 ? "▲ +" : d < 0 ? "▼ " : ""}${nf.format(d)} % vs anterior (${fmt(k.antes)})`;
  return h("div", { class: "kpi" }, h("div", { class: "l", text: etiqueta }), h("div", { class: "v", text: fmt(k?.ahora ?? 0) }),
    h("div", { class: `d ${d > 0 ? "up" : d < 0 ? "down" : ""}`, text: txt }));
}

// ── Vistas ──
function vistaResumen(R) {
  const K = R.anterior?.kpis || {};
  const dias = diasEntre(R.desde, R.hasta), mapa = Object.fromEntries((R.web.por_dia || []).map((x) => [x.dia, x]));
  const serie = dias.map((d) => mapa[d] || { dia: d, visitas: 0, contactan: 0, leads: 0 });
  const pendientes = [];
  if (R.negocio.sin_origen.length) pendientes.push(h("li", {}, `${R.negocio.sin_origen.length} solicitudes sin origen apuntado. `, h("a", { href: "#clientes", text: "Apúntalas en Clientes" }), " para saber qué portal trae trabajo."));
  if (!Object.keys(R.redes.redes).length) pendientes.push(h("li", {}, "Aún no hay datos de redes. ", h("a", { href: "#redes", text: "Mira cómo conectarlas" }), "."));
  if (!R.web.visitas) pendientes.push(h("li", { text: "Aún no hay visitas medidas: la medición empieza cuando se publica la web nueva." }));
  return [
    h("div", { class: "kpis" }, kpi("Visitas a la web", K.visitas), kpi("Visitas que contactan", K.contactan), kpi("Solicitudes", K.solicitudes),
      kpi("Ganadas", K.ganadas), kpi("Trabajos hechos", K.trabajos_hechos), kpi("Facturado", K.ingresos, (v) => eur.format(v || 0))),
    h("div", { class: "grid g2" },
      card("Visitas a la web por día", "Pasa el dedo o el ratón por el gráfico para ver cada día.",
        linea(serie, { valor: (p) => p.visitas, etiqueta: (p) => nombreDia(p.dia), detalle: (p) => `visitas · ${diaLargo.format(new Date(p.dia + "T12:00:00"))} · ${p.contactan} contactan` })),
      estado.informes?.[0] ? tarjetaInforme(estado.informes[0], true) : card("Informe semanal", "Cada lunes a las 7:30 la IA analiza la semana.", vacio("Todavía no hay informes. Puedes generar uno en «Informes IA»."))),
    h("div", { class: "grid", style: "margin-top:14px" },
      card("Del portal al cliente", "Cómo se mueve la gente: de cada origen, cuántos visitan la web, contactan, piden presupuesto, se cierran y cuánto facturan.",
        tabla([{ t: "Origen", v: (f) => f.nombre }, { t: "Alcance en la red", num: 1, v: (f) => n(f.alcance_red) }, { t: "Visitas web", num: 1, v: (f) => n(f.visitas_web) },
          { t: "Contactan", num: 1, v: (f) => n(f.contactan) }, { t: "Solicitudes", num: 1, v: (f) => n(f.solicitudes) }, { t: "Ganadas", num: 1, v: (f) => n(f.ganadas) },
          { t: "Facturado", num: 1, v: (f) => (f.ingresos ? eur.format(f.ingresos) : "—") }], R.flujo))),
    pendientes.length ? h("div", { class: "nota", style: "margin-top:14px" }, h("b", { text: "Para medir mejor: " }), h("ul", { style: "margin:6px 0 0 18px" }, pendientes)) : null,
  ];
}

function vistaWeb(R) {
  const W = R.web;
  const pagsScroll = Object.entries(W.scroll || {}).map(([p, v]) => ({ p, ...v }));
  return [
    h("div", { class: "kpis" },
      kpi("Visitas", { ahora: W.visitas }), kpi("Páginas vistas", { ahora: W.paginas_vistas }), kpi("Contactan", { ahora: W.pct_contactan }, pct),
      kpi("Se van sin hacer nada", { ahora: W.pct_rebote }, pct), kpi("Tiempo medio (mediana)", { ahora: W.duracion_mediana_seg }, (v) => `${n(v)} s`)),
    h("div", { class: "grid g2" },
      card("De dónde llegan", "Visitas por origen y qué parte contacta (WhatsApp, llamada, email o solicitud).",
        barras(W.fuentes, { valor: (f) => f.visitas, etiqueta: (f) => f.nombre, extra: (f) => `${nf.format(f.pct_contactan)} % contactan` })),
      card("Calculadora", `${n(W.calculadora.visitas)} visitas la abren · ${n(W.calculadora.con_precio)} ven precio · ${n(W.calculadora.enviadas)} la envían (${pct(W.calculadora.pct_terminan)}).`,
        barras(W.calculadora.embudo, { valor: (f) => f.visitas, etiqueta: (f) => `${f.paso}. ${f.nombre}`, extra: (f) => `${nf.format(f.pct)} %` }),
        Object.keys(W.calculadora.errores || {}).length ? h("p", { class: "sub", style: "margin-top:10px", text: "Avisos y errores: " + Object.entries(W.calculadora.errores).map(([k, v]) => `${k} (${v})`).join(" · ") }) : null),
      card("Qué secciones del inicio se ven", "Porcentaje de las visitas al inicio que llegan a ver cada sección.",
        barras(W.secciones["/"] || [], { valor: (f) => f.pct, max: 100, etiqueta: (f) => SECCIONES[f.id] || f.id, fmt: pct })),
      card("Qué pulsan", "Botones y enlaces más usados.",
        barras(Object.entries(W.clics || {}).map(([k, v]) => ({ k, v })), { valor: (f) => f.v, etiqueta: (f) => CLICS[f.k] || f.k }),
        W.clics_zona.length ? h("details", { style: "margin-top:12px" }, h("summary", { text: "Ver dónde los pulsan" }),
          tabla([{ t: "Botón · zona", v: (f) => f.clic }, { t: "Veces", num: 1, v: (f) => n(f.veces) }], W.clics_zona)) : null),
      card("Hasta dónde bajan", "Porcentaje de visitas de cada página que llega al 25, 50, 75 y 100 % de la página.",
        tabla([{ t: "Página", v: (f) => f.p }, { t: "25 %", num: 1, v: (f) => pct(f["25"]) }, { t: "50 %", num: 1, v: (f) => pct(f["50"]) },
          { t: "75 %", num: 1, v: (f) => pct(f["75"]) }, { t: "Final", num: 1, v: (f) => pct(f["100"]) }], pagsScroll)),
      card("Dispositivo", null, barras(Object.entries(W.dispositivos || {}).map(([k, v]) => ({ k, v })), { valor: (f) => f.v, max: 100, etiqueta: (f) => ({ movil: "Móvil", escritorio: "Ordenador", tablet: "Tablet" })[f.k] || f.k, fmt: pct }))),
    h("div", { class: "grid", style: "margin-top:14px" },
      card("Páginas", "Vistas, visitas distintas, tiempo que pasan (mediana) y cuántas visitas terminan ahí.",
        tabla([{ t: "Página", v: (f) => f.pagina }, { t: "Vistas", num: 1, v: (f) => n(f.vistas) }, { t: "Visitas", num: 1, v: (f) => n(f.visitas) },
          { t: "Tiempo", num: 1, v: (f) => (f.seg_mediana == null ? "—" : `${f.seg_mediana} s`) }, { t: "Se van aquí", num: 1, v: (f) => n(f.salidas) }], W.paginas))),
    h("div", { class: "grid g2", style: "margin-top:14px" },
      card("Recorridos más repetidos", "El camino de páginas de cada visita.", tabla([{ t: "Recorrido", v: (f) => f.recorrido }, { t: "Visitas", num: 1, v: (f) => n(f.visitas) }], W.recorridos)),
      card("Asistente «Sur»", `${n(W.chat.visitas_que_lo_abren)} visitas lo abren (${pct(W.chat.pct_abren)}) · ${n(W.chat.mensajes)} mensajes.`,
        R.preguntas_chat.length ? h("ul", { class: "ideas" }, R.preguntas_chat.slice(0, 25).map((p) => h("li", { text: `${p.texto}` }))) : vacio("Sin preguntas en este periodo."),
        h("p", { class: "sub", style: "margin-top:10px", text: "Lo que pregunta la gente son ideas de contenido para redes y para las preguntas frecuentes." })),
      W.campanas.length ? card("Campañas (enlaces con etiqueta)", null, tabla([{ t: "Campaña", v: (f) => f.campana }, { t: "Visitas", num: 1, v: (f) => n(f.visitas) }], W.campanas)) : null,
      card("Por dónde entran", "Primera página de cada visita.", barras(W.entradas, { valor: (f) => f.visitas, etiqueta: (f) => f.pagina }))),
  ];
}

function vistaRedes(R) {
  const redes = R.redes.redes, claves = Object.keys(redes);
  const ayuda = h("div", { class: "nota" }, h("b", { text: "Cómo llegan aquí los datos de las redes. " }),
    "Conecta Instagram, TikTok, Facebook y tu Perfil de Google a Metricool (en el plan gratuito caben todas en la misma marca). ",
    "Cada mañana Claude lee Metricool y guarda aquí las métricas del día y de cada publicación. ",
    "También puedes pedírselo cuando quieras: «guarda en el panel las métricas de Instagram de esta semana».");
  if (!claves.length) return [ayuda];
  return [
    h("div", { class: "grid g3" }, claves.map((red) => {
      const r = redes[red], t = r.totales || {};
      const serieAlc = (r.serie || []).filter((s) => s.alcance != null || s.visualizaciones != null);
      return card(REDES[red] || r.nombre, `${r.dias_con_datos} días con datos`,
        h("div", { class: "kpis", style: "grid-template-columns:repeat(2,1fr);margin-bottom:10px" },
          kpi("Seguidores", { ahora: r.seguidores }),
          kpi("Cambio en el periodo", { ahora: r.seguidores_cambio }, (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${nf.format(v)}`))),
        tabla([{ t: "Métrica", v: (f) => METRICAS[f[0]] || f[0] }, { t: "Total", num: 1, v: (f) => n(f[1]) }], Object.entries(t)),
        serieAlc.length > 2 ? h("div", { style: "margin-top:10px" }, linea(serieAlc, { valor: (p) => p.alcance ?? p.visualizaciones ?? 0, etiqueta: (p) => nombreDia(p.dia), detalle: (p) => `alcance · ${nombreDia(p.dia)}` })) : null);
    })),
    h("div", { class: "grid", style: "margin-top:14px" },
      card("Publicaciones que mejor funcionan", "Ordenadas por visualizaciones, interacciones y veces compartidas.",
        tabla([{ t: "Red", v: (f) => REDES[f.red] || f.red }, { t: "Fecha", v: (f) => f.fecha }, { t: "Tipo", v: (f) => f.tipo },
          { t: "Publicación", v: (f) => (f.url ? h("a", { href: f.url, target: "_blank", rel: "noopener noreferrer", text: f.texto || "Ver" }) : f.texto) },
          { t: "Visualiz.", num: 1, v: (f) => n(f.m?.visualizaciones) }, { t: "Interacc.", num: 1, v: (f) => n(f.m?.interacciones) }, { t: "Compart.", num: 1, v: (f) => n(f.m?.compartidos) }],
          R.redes.top_publicaciones))),
    h("div", { style: "margin-top:14px" }, ayuda),
  ];
}

function vistaClientes(R) {
  const N = R.negocio, K = R.anterior?.kpis || {};
  const sinOrigen = N.sin_origen.map((x) => {
    const sel = h("select", { class: "input", "aria-label": `Origen de ${x.cliente || "la solicitud"}`, name: `origen-${x.id}` },
      h("option", { value: "", text: "¿De dónde vino?" }), ORIGENES.map(([v, t]) => h("option", { value: v, text: t })));
    const btn = h("button", { class: "btn btn-ink", type: "button", text: "Guardar", onclick: async () => {
      if (!sel.value) return toast("Elige un origen");
      btn.disabled = true;
      try { await api("asignar_origen", { id: x.id, origen: sel.value }); toast("Guardado"); fila.remove(); estado.R = null; }
      catch (e) { toast(e.message); btn.disabled = false; }
    } });
    const fila = h("div", { class: "fila" }, h("div", { class: "quien" }, h("b", { text: x.cliente || "Sin nombre" }), h("span", { text: `${x.poblacion || "—"} · entró el ${x.creado}` })), sel, btn);
    return fila;
  });
  return [
    h("div", { class: "kpis" }, kpi("Solicitudes", K.solicitudes), kpi("Ganadas", K.ganadas), kpi("% ganadas", { ahora: N.pct_ganadas }, pct),
      kpi("Trabajos hechos", K.trabajos_hechos), kpi("Facturado", K.ingresos, (v) => eur.format(v || 0)), kpi("Ticket medio", { ahora: N.ticket_medio }, (v) => eur.format(v || 0)),
      kpi("Programados por hacer", { ahora: N.programados_pendientes })),
    h("div", { class: "grid" },
      card("Qué origen trae trabajo", "Solicitudes nuevas del periodo por origen, cuántas se ganan y lo facturado por los trabajos hechos.",
        tabla([{ t: "Origen", v: (f) => f.nombre }, { t: "Solicitudes", num: 1, v: (f) => n(f.solicitudes) }, { t: "Presupuestadas", num: 1, v: (f) => n(f.presupuestadas) },
          { t: "Ganadas", num: 1, v: (f) => n(f.ganadas) }, { t: "% ganadas", num: 1, v: (f) => pct(f.pct_ganadas) }, { t: "Perdidas", num: 1, v: (f) => n(f.perdidas) },
          { t: "Hechos", num: 1, v: (f) => n(f.trabajos_hechos) }, { t: "Facturado", num: 1, v: (f) => (f.ingresos ? eur.format(f.ingresos) : "—") }], N.por_origen)),
      card("Solicitudes sin origen", "Las que entraron por WhatsApp o teléfono. Apunta de dónde vinieron y el panel lo sumará a su portal.",
        sinOrigen.length ? h("div", { class: "asignar" }, sinOrigen)
          : vacio("Todas las solicitudes del periodo tienen origen. 👌")),
      card("Últimas solicitudes", null, tabla([{ t: "Entró", v: (f) => f.creado }, { t: "Cliente", v: (f) => f.cliente || "—" }, { t: "Población", v: (f) => f.poblacion || "—" },
        { t: "Origen", v: (f) => h("span", { class: "chip", text: (ORIGENES.find((o) => o[0] === f.origen) || [0, f.origen === "presupuesto_app" ? "Formulario /presupuesto" : f.origen === "web" ? "Web" : "Sin apuntar"])[1] }) },
        { t: "Etapa", v: (f) => ETAPAS[f.etapa] || f.etapa }, { t: "Precio", num: 1, v: (f) => (f.precio ? eur.format(f.precio) : "—") }], N.recientes))),
  ];
}

async function vistaVisitas() {
  const R = estado.R;
  const fuentes = R.web.fuentes;
  const sel = h("select", { class: "input", name: "fuente", "aria-label": "Origen" }, h("option", { value: "", text: "Todos los orígenes" }), fuentes.map((f) => h("option", { value: f.fuente, text: f.nombre })));
  const chk = h("input", { type: "checkbox", name: "solo_contactos" });
  const lista = h("div", {}, vacio("Cargando…"));
  const cargar = async () => {
    lista.style.opacity = 0.5;
    try {
      const d = await api("sesiones", { desde: estado.desde, hasta: estado.hasta, fuente: sel.value, solo_contactos: chk.checked, limite: 60 });
      lista.replaceChildren(...(d.visitas?.length ? d.visitas.map((v) => h("details", { class: "visita" },
        h("summary", {}, h("b", { text: v.dia }), h("span", { class: "chip", text: (fuentes.find((f) => f.fuente === v.fuente) || {}).nombre || v.fuente }),
          v.campana ? h("span", { class: "sub", text: v.campana }) : null, h("span", { class: "sub", text: `${v.disp === "movil" ? "Móvil" : v.disp === "tablet" ? "Tablet" : "Ordenador"} · ${v.duracion_seg} s` }),
          v.lead ? h("span", { class: "lead-tag", text: `Envió ${v.lead}` }) : null),
        h("ol", {}, v.pasos.map((p) => h("li", { text: p }))))) : [vacio("No hay visitas con ese filtro.")]));
    } catch (e) { lista.replaceChildren(vacio(e.message)); }
    lista.style.opacity = 1;
  };
  sel.onchange = cargar; chk.onchange = cargar;
  cargar();
  return [card("Visitas una a una", "Recorrido anónimo de cada visita: qué ve, qué pulsa y cuánto tiempo pasa. Sirve para ver dónde se atascan.",
    h("div", { class: "filtros" }, sel, h("label", { class: "sub", style: "display:flex;gap:6px;align-items:center" }, chk, "Solo las que contactan")), lista)];
}

function tarjetaInforme(doc, corto = false) {
  const i = doc.informe || {};
  const pts = (i.puntos || []).slice(0, corto ? 5 : 20);
  return h("article", { class: "card informe" },
    h("p", { class: "sub", text: `Informe del ${doc.desde} al ${doc.hasta}${i.sin_ia ? " · sin IA (" + i.sin_ia + ")" : ""}` }),
    h("p", { class: "titular", text: i.titular || "" }), i.resumen ? h("p", { class: "resumen", text: i.resumen }) : null,
    pts.length ? h("ul", { class: "puntos" }, pts.map((p) => h("li", {}, h("span", { class: `tag ${p.tipo}`, text: p.portal || "general" }), h("span", { text: p.texto })))) : null,
    !corto && i.ideas_contenido?.length ? [h("h2", { style: "margin-top:16px", text: "Ideas de contenido" }), h("ul", { class: "ideas" }, i.ideas_contenido.map((x) => h("li", { text: x })))] : null,
    !corto && i.experimento ? h("div", { class: "nota", style: "margin-top:14px" }, h("b", { text: "Experimento de la semana: " }), i.experimento) : null,
    corto ? h("p", { style: "margin-top:12px" }, h("a", { href: "#informes", text: "Ver el informe completo →" })) : null);
}

async function vistaInformes() {
  const btn = h("button", { class: "btn btn-lime", type: "button", text: "Generar informe de los últimos 7 días" });
  const lista = h("div", { class: "grid" }, (estado.informes || []).length ? estado.informes.map((d) => tarjetaInforme(d)) : vacio("Todavía no hay informes."));
  btn.onclick = async () => {
    btn.disabled = true; btn.textContent = "Analizando… (puede tardar un minuto)";
    try { const d = await api("generar_informe", {}); estado.informes = [d, ...(estado.informes || [])]; render(); }
    catch (e) { toast(e.message); btn.disabled = false; btn.textContent = "Generar informe de los últimos 7 días"; }
  };
  return [h("div", { class: "filtros" }, btn, h("span", { class: "sub", text: "Se genera solo cada lunes a las 7:30 y te llega un aviso al móvil." })), lista];
}

function enlaceUTM(url, fuente, medio, campana, contenido) {
  const limpio = (s) => String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9_-]+/g, "-").replace(/^-|-$/g, "").slice(0, 40);
  const base = url.startsWith("http") ? url : "https://mudanzasdelsur.es" + (url.startsWith("/") ? url : "/" + url);
  const q = [["utm_source", fuente], ["utm_medium", medio], ["utm_campaign", campana], ["utm_content", contenido]].map(([k, v]) => [k, limpio(v)]).filter(([, v]) => v).map(([k, v]) => `${k}=${v}`).join("&");
  return base + (base.includes("?") ? "&" : "?") + q;
}
async function copiar(t) {
  try { await navigator.clipboard.writeText(t); toast("Copiado"); }
  catch { const a = h("textarea", {}, t); document.body.append(a); a.select(); document.execCommand("copy"); a.remove(); toast("Copiado"); }
}
function vistaEnlaces() {
  const fijos = [
    ["Bio de Instagram", "/", "instagram", "bio"], ["Historias de Instagram (pegatina de enlace)", "/calculadora/", "instagram", "historia"],
    ["Bio de TikTok", "/", "tiktok", "bio"], ["Página de Facebook (botón y publicaciones)", "/", "facebook", "pagina"],
    ["Perfil de Google (botón «Sitio web»)", "/", "gbp", "perfil"], ["Estado y mensajes de WhatsApp", "/calculadora/", "whatsapp", "mensaje"],
    ["QR del camión y la furgoneta", "/calculadora/", "camion", "qr"], ["QR de flyers y tarjetas", "/", "flyer", "qr"],
  ].map(([t, u, f, m]) => { const url = enlaceUTM(u, f, m); return h("div", { class: "enlace" }, h("b", { text: t }), h("code", { text: url }), h("button", { class: "btn btn-ghost", type: "button", text: "Copiar", onclick: () => copiar(url) })); });
  const pagina = h("select", { class: "input", name: "pagina" }, [["/", "Inicio"], ["/calculadora/", "Calculadora"], ["/contacto/", "Contacto"], ["/servicios/", "Servicios"], ["/blog/", "Consejos"]].map(([v, t]) => h("option", { value: v, text: t })));
  const fuente = h("select", { class: "input", name: "fuente" }, [["instagram", "Instagram"], ["tiktok", "TikTok"], ["facebook", "Facebook"], ["gbp", "Perfil de Google"], ["whatsapp", "WhatsApp"], ["flyer", "Flyer / QR"], ["email", "Email"]].map(([v, t]) => h("option", { value: v, text: t })));
  const medio = h("select", { class: "input", name: "medio" }, ["historia", "bio", "reel", "post", "mensaje", "anuncio", "qr"].map((v) => h("option", { value: v, text: v })));
  const campana = h("input", { class: "input", name: "campana", placeholder: "Ej.: octubre…", autocomplete: "off" });
  const contenido = h("input", { class: "input", name: "contenido", placeholder: "Ej.: nevera-isla-cristina…", autocomplete: "off" });
  const salida = h("code", { style: "word-break:break-all" });
  const act = () => { salida.textContent = enlaceUTM(pagina.value, fuente.value, medio.value, campana.value, contenido.value); };
  [pagina, fuente, medio, campana, contenido].forEach((e) => e.addEventListener("input", act)); act();
  const campo = (t, e) => h("label", { class: "field" }, t, e);
  return [
    card("Enlaces fijos para cada portal", "Pon cada uno en su sitio una vez y el panel sabrá de dónde viene cada visita.", h("div", { class: "enlaces" }, fijos)),
    h("div", { style: "margin-top:14px" }, card("Crear un enlace para una publicación concreta", "Para historias, mensajes o anuncios: así sabes qué contenido trae clientes.",
      h("div", { class: "form-enlace" }, campo("Página", pagina), campo("Dónde lo pones", fuente), campo("Formato", medio), campo("Campaña", campana), campo("Contenido", contenido)),
      h("div", { class: "enlace", style: "margin-top:12px" }, h("b", { text: "Tu enlace" }), salida, h("button", { class: "btn btn-ink", type: "button", text: "Copiar", onclick: () => copiar(salida.textContent) })))),
    h("div", { class: "nota", style: "margin-top:14px" }, h("b", { text: "Google Ads " }), "ya se mide solo (etiquetado automático). Los reels no admiten enlace: su efecto se ve en las visitas de «Instagram · bio» de los días en que se publican."),
  ];
}

// ── Montaje ──
const VISTAS = { resumen: vistaResumen, web: vistaWeb, redes: vistaRedes, clientes: vistaClientes, visitas: vistaVisitas, informes: vistaInformes, enlaces: vistaEnlaces };

async function cargarDatos() {
  document.body.classList.add("cargando");
  try {
    const [R, inf] = await Promise.all([api("resumen", { desde: estado.desde, hasta: estado.hasta }), estado.informes ? null : api("informes").catch(() => ({ informes: [] }))]);
    estado.R = R;
    estado.cargado = Date.now();
    if (inf) estado.informes = inf.informes || [];
  } catch (e) { toast(e.message); }
  document.body.classList.remove("cargando");
}

let pintando = 0;
async function render() {
  const id = ++pintando;
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === estado.tab)));
  document.querySelectorAll(".presets button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.dias === estado.preset)));
  $("f-desde").value = estado.desde; $("f-hasta").value = estado.hasta;
  $("rango-txt").textContent = estado.R ? `${estado.R.dias} días · comparado con los ${estado.R.dias} anteriores` : "";
  $("filtros").style.display = ["enlaces", "informes"].includes(estado.tab) ? "none" : "";
  if (!estado.R && !["enlaces"].includes(estado.tab)) await cargarDatos();
  if (id !== pintando) return;
  $("rango-txt").textContent = estado.R ? `${estado.R.dias} días · comparado con los ${estado.R.dias} anteriores` : "";
  const contenido = estado.R || estado.tab === "enlaces" ? await VISTAS[estado.tab](estado.R) : [vacio("No se han podido cargar los datos.")];
  if (id !== pintando) return;
  $("vista").replaceChildren(...[contenido].flat(3).filter(Boolean));
}

function irA(tab) { if (!VISTAS[tab]) tab = "resumen"; estado.tab = tab; guardar("tab", tab); if (location.hash !== "#" + tab) history.replaceState(null, "", "#" + tab); render(); window.scrollTo({ top: 0 }); }
function ponerPreset(p) { estado.preset = p; guardar("preset", p); [estado.desde, estado.hasta] = calcularRango(p); estado.R = null; render(); }

// Datos frescos: botón «Actualizar» y al volver a la pestaña si han pasado más de 2 minutos
function actualizar() { estado.R = null; estado.informes = null; render(); }
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && estado.cargado && Date.now() - estado.cargado > 120000 && !$("app").hidden) actualizar();
});

function arrancar(email) {
  $("btn-actualizar").onclick = actualizar;
  $("login").hidden = true; $("app").hidden = false; $("quien").textContent = email;
  [estado.desde, estado.hasta] = calcularRango(estado.preset);
  document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => irA(b.dataset.tab)));
  document.querySelectorAll(".presets button").forEach((b) => (b.onclick = () => ponerPreset(b.dataset.dias)));
  const manual = () => { if ($("f-desde").value && $("f-hasta").value) { estado.preset = ""; estado.desde = $("f-desde").value; estado.hasta = $("f-hasta").value; estado.R = null; render(); } };
  $("f-desde").onchange = manual; $("f-hasta").onchange = manual;
  window.addEventListener("hashchange", () => irA(location.hash.slice(1)));
  irA(location.hash.slice(1) || estado.tab);
}

if (DEMO) arrancar("modo demo");
else {
  $("btn-salir").onclick = () => signOut(auth);
  $("form-login").onsubmit = async (e) => {
    e.preventDefault(); $("login-error").textContent = ""; $("btn-login").disabled = true;
    try { await signInWithEmailAndPassword(auth, $("email").value.trim(), $("pass").value); }
    catch { $("login-error").textContent = "Email o contraseña incorrectos."; }
    $("btn-login").disabled = false;
  };
  onAuthStateChanged(auth, (u) => {
    if (u && EQUIPO.includes((u.email || "").toLowerCase())) arrancar(u.email);
    else { if (u) { signOut(auth); $("login-error").textContent = "Esta cuenta no es del equipo."; } $("app").hidden = true; $("login").hidden = false; }
  });
}
