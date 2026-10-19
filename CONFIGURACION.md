# ══════════════════════════════════════════════════════
#  REGLAS DE SEGURIDAD — Solo copia y pega en Firebase
# ══════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────
#  FIRESTORE  (Firebase Console → Firestore → Reglas)
# ─────────────────────────────────────────────────────

rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {

    // Solo usuarios autenticados (tus dos cuentas) pueden leer/escribir
    match /inventario/{docId} {
      allow read, write: if request.auth != null;
    }

    // Tokens FCM: cada usuario solo escribe los suyos; cualquier autenticado puede leer
    match /fcm_tokens/{docId} {
      allow read:  if request.auth != null;
      allow write: if request.auth != null && request.resource.data.uid == request.auth.uid;
    }
  }
}


# ─────────────────────────────────────────────────────
#  STORAGE  (Firebase Console → Storage → Reglas)
# ─────────────────────────────────────────────────────

rules_version = '2';
service firebase.storage {
  match /b/{bucket}/o {

    // Solo usuarios autenticados pueden subir/leer imágenes del inventario
    match /inventario/{userId}/{allPaths=**} {
      allow read:  if request.auth != null;
      allow write: if request.auth != null
                   && request.auth.uid == userId
                   && request.resource.size < 10 * 1024 * 1024   // máx 10 MB
                   && request.resource.contentType.matches('image/.*');
    }
  }
}


# ══════════════════════════════════════════════════════
#  CHECKLIST DE CONFIGURACIÓN — Pasos a seguir
# ══════════════════════════════════════════════════════

## 1. OBTENER TU firebaseConfig
#   Firebase Console → Configuración del proyecto → Tus apps → Web
#   Copia el objeto firebaseConfig y pégalo en:
#     - index.html  (en la variable firebaseConfig)
#     - firebase-messaging-sw.js  (en firebase.initializeApp)

## 2. OBTENER TU VAPID KEY
#   Firebase Console → Configuración del proyecto → Cloud Messaging
#   → Configuración web → Generar par de claves
#   Copia la "Clave pública" y pégala en index.html como VAPID_KEY

## 3. CREAR LAS DOS CUENTAS DE USUARIO
#   Firebase Console → Authentication → Users → Añadir usuario
#   Crea las dos cuentas (tú y tu socio) con email/password

## 4. ACTIVAR FCM EN iOS (importante)
#   - Abre index.html en Safari en el iPhone
#   - Pulsa compartir → "Añadir a pantalla de inicio"
#   - Abre la app desde el icono (NO desde Safari)
#   - Pulsa "Activar notificaciones" cuando aparezca el banner
#   - Las push en iOS requieren iOS 16.4+ y que la app esté instalada como PWA

## 5. DESPLIEGUE RECOMENDADO
#   Opción A (más fácil): Firebase Hosting
#     npm install -g firebase-tools
#     firebase login
#     firebase init hosting
#     firebase deploy
#
#   Opción B: Cualquier hosting HTTPS (Netlify, Vercel, etc.)
#   ⚠️  El Service Worker REQUIERE HTTPS para funcionar

## 6. ESTRUCTURA DE ARCHIVOS
#   /
#   ├── index.html                ← App principal
#   ├── firebase-messaging-sw.js  ← Service Worker (en raíz obligatoriamente)
#   ├── manifest.json             ← Metadatos PWA
#   ├── icon-192.png              ← Icono PWA (genera en realfavicongenerator.net)
#   └── icon-512.png              ← Icono PWA grande

## 7. NOTIFICACIONES PUSH → CLOUD FUNCTIONS (opcional, avanzado)
#   Para que cuando uno suba algo el otro reciba notificación automáticamente,
#   necesitas una Cloud Function que:
#     1. Se dispare con onDocumentCreated('inventario/{id}')
#     2. Lea los tokens FCM de la colección 'fcm_tokens'
#     3. Envíe la notificación con admin.messaging().sendEachForMulticast()
#   Documentación: https://firebase.google.com/docs/functions/firestore-events

## IA de la web pública (mudanzasdelsur.es)

Función `web_api` (functions/web_ia.py): asistente de chat, análisis de fotos, calculadora y
formulario de contacto de la web. Todo lo que llega se guarda como **solicitud** en la app.

1. Crea la clave gratuita en https://aistudio.google.com/apikey y guárdala como secreto
   (antes del primer deploy, si no el deploy falla):
   `firebase functions:secrets:set GEMINI_KEY --data-file clave.txt` (y borra clave.txt).
2. `firebase deploy --only functions,hosting`
3. Persona y conocimientos del asistente: `functions/web_conocimiento.py`.
   Reglas del cálculo: `functions/estimador.py` (usa las tarifas de la app).
4. Pruebas: `python -m pytest tests`

Con la clave gratuita Google puede usar lo enviado para mejorar sus modelos: para clientes
reales conviene activar la facturación en Google AI Studio (cuesta céntimos al mes).
