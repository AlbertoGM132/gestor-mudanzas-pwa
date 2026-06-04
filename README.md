# gestor-mudanzas-pwa

Aplicación web progresiva (PWA) de gestión integral para empresas de mudanzas. Permite administrar trabajos, generar presupuestos en PDF, llevar el control financiero y enviar notificaciones push al equipo, todo desde el móvil o el escritorio.

---

## Características principales

| Módulo | Descripción |
|---|---|
| **Calendario** | Vista mensual de trabajos con estado codificado por color |
| **Trabajos** | CRUD completo: cliente, horarios, vehículo, equipo, materiales y fotos |
| **Cierre económico** | Cálculo de beneficios post-trabajo (mano de obra, materiales, gasolina, extras) |
| **Presupuestos PDF** | Generación automática de PDFs con logo, IVA y líneas de presupuesto |
| **Finanzas** | Dashboard de ingresos y gastos mensuales con balance acumulado |
| **Tarifas** | Configuración de tarifa por hora/trabajador y precios de materiales |
| **Notificaciones push** | FCM integrado para alertas en tiempo real, incluso con la app cerrada |
| **Galería de fotos** | Subida y visualización de fotos por trabajo |

---

## Tecnologías

### Frontend
- **HTML5 + CSS3 + JavaScript (ES6+)** — Vanilla JS sin frameworks
- **Firebase Web SDK v11** — Auth, Firestore, Storage, Messaging
- **PWA** — Service Worker, manifest, instalable en iOS/Android

### Backend
- **Python 3.12** — Firebase Cloud Functions
- **ReportLab 4.0** — Generación de PDFs con diseño personalizado
- **Firebase Admin SDK** — Acceso a Firestore y Storage desde el servidor

### Infraestructura (Google Cloud)
- **Firebase Hosting** — Alojamiento del frontend
- **Firestore** — Base de datos NoSQL en tiempo real
- **Firebase Storage** — Fotos y PDFs generados
- **Firebase Authentication** — Login con email y contraseña
- **Firebase Cloud Functions** — Endpoint HTTP para generación de PDFs
- **Firebase Cloud Messaging (FCM)** — Notificaciones push
- **Región:** `europe-west1`

---

## Estructura del proyecto

```
MudanzasApp/
├── public/                        # Frontend estático
│   ├── index.html                 # UI principal (SPA)
│   ├── app.js                     # Lógica de la aplicación
│   ├── styles.css                 # Estilos (dark theme, mobile-first)
│   └── firebase-messaging-sw.js  # Service Worker para FCM y PWA
│
├── functions/                     # Cloud Functions (Python)
│   ├── main.py                    # Función HTTP: generar_presupuesto
│   ├── requirements.txt           # Dependencias Python
│   └── __init__.py
│
├── firebase.json                  # Configuración de deploy
├── firestore.rules                # Reglas de seguridad de Firestore
├── storage.rules                  # Reglas de seguridad de Storage
├── manifest.json                  # Metadatos PWA
└── .firebaserc                    # ID del proyecto Firebase
```

---

## Requisitos previos

- [Node.js](https://nodejs.org/) v18 o superior
- [Firebase CLI](https://firebase.google.com/docs/cli): `npm install -g firebase-tools`
- [Python 3.12](https://www.python.org/)
- Una cuenta de [Firebase](https://console.firebase.google.com/) con un proyecto creado

---

## Configuración inicial

### 1. Clonar el repositorio

```bash
git clone https://github.com/AlbertoGM132/gestor-mudanzas-pwa.git
cd gestor-mudanzas-pwa
```

### 2. Crear un proyecto en Firebase

1. Ve a [Firebase Console](https://console.firebase.google.com/) y crea un nuevo proyecto
2. Activa los siguientes servicios:
   - **Authentication** → método Email/Contraseña
   - **Firestore Database** → modo producción
   - **Storage** → modo producción
   - **Hosting**
   - **Functions** (requiere plan Blaze)

### 3. Obtener la configuración de Firebase

En Firebase Console → Configuración del proyecto → Tus aplicaciones → Web app, copia el objeto `firebaseConfig` y también la **VAPID key** (Configuración → Cloud Messaging → Certificados push web).

Edita `public/app.js` y reemplaza los valores al inicio del archivo:

```javascript
const firebaseConfig = {
  apiKey: "TU_API_KEY",
  authDomain: "TU_PROYECTO.firebaseapp.com",
  projectId: "TU_PROYECTO",
  storageBucket: "TU_PROYECTO.firebasestorage.app",
  messagingSenderId: "TU_SENDER_ID",
  appId: "TU_APP_ID"
};

const VAPID_KEY = "TU_VAPID_KEY";
```

También edita `firebase-messaging-sw.js` con los mismos valores de `firebaseConfig`.

### 4. Configurar los datos de la empresa

En `public/app.js`, localiza el objeto `EMPRESA_DATA` y actualiza los datos:

```javascript
const EMPRESA_DATA = {
  nombre:    "Tu empresa",
  direccion: "Tu dirección",
  ciudad:    "Tu ciudad",
  telefono:  "Tu teléfono",
  email:     "tuemail@ejemplo.com"
};
```

### 5. Subir el logo al Storage

Sube tu logo como `assets/logo.jpg` en la raíz de Firebase Storage. Ese archivo se usa para el encabezado de los PDFs generados.

### 6. Crear las cuentas de usuario

En Firebase Console → Authentication → Usuarios, crea manualmente las cuentas de los miembros del equipo (email + contraseña). La app no tiene registro público.

### 7. Actualizar el ID del proyecto

Edita `.firebaserc` con el ID de tu proyecto:

```json
{
  "projects": {
    "default": "tu-proyecto-id"
  }
}
```

---

## Despliegue

### Instalar dependencias del entorno virtual (solo primer uso)

```bash
cd functions
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt
cd ..
```

### Autenticarse en Firebase

```bash
firebase login
firebase use --add   # selecciona tu proyecto
```

### Desplegar todo

```bash
firebase deploy
```

O desplegar por partes:

```bash
# Solo frontend
firebase deploy --only hosting

# Solo Cloud Functions
firebase deploy --only functions

# Solo reglas de base de datos y storage
firebase deploy --only firestore,storage
```

Al finalizar, Firebase mostrará la URL pública del hosting (ej. `https://tu-proyecto.web.app`).

---

## Uso de la aplicación

### Acceder
Navega a la URL del hosting e inicia sesión con las credenciales creadas en Firebase Authentication.

### Instalar como PWA
- **Android**: Chrome → menú → "Añadir a pantalla de inicio"
- **iOS**: Safari → compartir → "Añadir a pantalla de inicio" (requiere iOS 16.4+)

### Flujo de trabajo habitual

1. **Crear trabajo** — Desde el calendario, pulsa "+" y rellena el formulario multi-paso (datos, direcciones, recursos, materiales, fotos)
2. **Gestionar estado** — Los trabajos pasan por `pendiente → en_curso → completado`
3. **Cierre económico** — Al completar, introduce horas trabajadas, materiales usados y gastos; la app calcula el beneficio automáticamente
4. **Generar presupuesto** — Rellena las líneas del presupuesto y pulsa "Generar PDF"; el PDF se sube a Storage y se abre en una nueva pestaña
5. **Finanzas** — Consulta el dashboard de ingresos/gastos o añade movimientos manuales

---

## Colecciones de Firestore

| Colección | Contenido |
|---|---|
| `trabajos` | Trabajos de mudanza con todos sus datos |
| `presupuestos` | Metadatos de presupuestos generados (con URL al PDF) |
| `finanzas` | Movimientos de ingresos y gastos |
| `config` | Configuración de tarifas |
| `fcm_tokens` | Tokens de notificaciones push por usuario |

---

## Cloud Function: `generar_presupuesto`

Endpoint HTTP (POST) que:

1. Recibe los datos del presupuesto en JSON
2. Descarga el logo desde Firebase Storage
3. Genera el PDF con ReportLab (cabecera corporativa, tabla de líneas, IVA opcional)
4. Sube el PDF a Storage como archivo público
5. Guarda los metadatos en Firestore
6. Devuelve la URL pública del PDF

**Región:** `europe-west1` · **Memoria:** 512 MB · **Timeout:** 60 s

---

## Seguridad

Las reglas de Firestore y Storage están en `firestore.rules` y `storage.rules`. Por defecto permiten acceso a cualquier usuario autenticado; se recomienda ajustarlas para restringir por `request.auth.uid` según las necesidades de cada equipo.

---

## Licencia

Uso privado. Todos los derechos reservados.
