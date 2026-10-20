# Panel del negocio (web + redes + MudanzaPro)

Una app aparte (`panel/`) en el mismo proyecto de Firebase que MudanzaPro, con el mismo login.
Junta en un sitio lo que pasa en cada portal y cómo se pasa la gente de uno a otro:

```
Instagram / TikTok / Facebook / Google ─┐
                                        ├─► web (visitas, secciones, calculadora, chat) ─► solicitud en MudanzaPro ─► trabajo ─► €
Perfil de Google / flyers / QR ─────────┘
```

## Piezas

| Pieza | Dónde | Qué hace |
|---|---|---|
| Medición de la web | repo de la web: `src/lib/analitica.ts` y `Analitica.tsx` | Sin cookies. Manda eventos a `web_api/evento` |
| Recogida y cálculo | `functions/analitica.py` | Guarda visitas (`analitica_sesiones`), clasifica el origen y calcula los resúmenes |
| Origen de cada solicitud | `web_ia.py` | La calculadora y el contacto guardan `attribution` en el trabajo |
| API del panel | `functions/panel.py` → `panel_api` | Solo para el equipo (token de Firebase) |
| Informe semanal | `panel.py` → `informe_semanal` | Lunes 7:30, con Gemini. Avisa al móvil |
| Herramientas para Claude | `functions/mcp_analitica.py` | Se añaden al conector de MudanzaPro: `analitica_resumen`, `analitica_visitas`, `analitica_informes`, `analitica_enlace`, `guardar_metricas_redes`, `asignar_origen_solicitud` |
| Redes | colecciones `redes_metricas` y `redes_publicaciones` | Las rellena Claude cada mañana desde Metricool (tarea programada) o a mano |
| Panel | `panel/` (sitio de hosting `mudanzasdelsur-panel`) | Resumen, Web, Redes, Clientes, Visitas, Informes IA, Enlaces |

## Puesta en marcha (una vez)

1. Crear el sitio del panel (si el nombre está cogido, usa otro y cámbialo en `firebase.json` → `"site"`):
   ```
   firebase hosting:sites:create mudanzasdelsur-panel --project smartsonubalogictis
   ```
2. Desplegar funciones y hosting (la primera vez pide activar Cloud Scheduler para el informe semanal: acepta):
   ```
   firebase deploy --only functions,hosting --project smartsonubalogictis
   ```
3. (Opcional, recomendado) Que Firestore borre solo los datos de más de 13 meses:
   ```
   gcloud firestore fields ttls update expira --collection-group=analitica_sesiones --enable-ttl --project smartsonubalogictis
   gcloud firestore fields ttls update expira --collection-group=analitica_preguntas --enable-ttl --project smartsonubalogictis
   ```
4. Abrir `https://mudanzasdelsur-panel.web.app` y entrar con la cuenta de MudanzaPro.
   Para tenerlo en `panel.mudanzasdelsur.es`: Firebase → Hosting → sitio del panel → Añadir dominio personalizado, y en Hostinger el registro que indique.

## Notas

- La web solo se mide si el navegador no pide «No rastrear». No se guarda la IP ni nada en el navegador; la visita es un id aleatorio en memoria.
- Las solicitudes que llegan por WhatsApp o teléfono no tienen origen: apúntalo en Panel → Clientes, o pídeselo a Claude.
- Los reels no admiten enlace: su efecto se ve en las visitas de «instagram · bio» de esos días. Para historias, usa enlaces de Panel → Enlaces.
