// ══════════════════════════════════════════════════════════════
//  firebase-messaging-sw.js
//  Service Worker para Firebase Cloud Messaging (FCM)
//  ⚠️  Debe estar en la RAÍZ de tu sitio (junto a index.html)
// ══════════════════════════════════════════════════════════════

// Versión del caché de la PWA
const CACHE_NAME  = 'mudanza-v2';
const CACHE_FILES = ['/', '/index.html', '/manifest.json'];

// ── Firebase SDK (modo compat, requerido en SW) ──
importScripts('https://www.gstatic.com/firebasejs/11.6.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/11.6.0/firebase-messaging-compat.js');

// ✏️  Mismo firebaseConfig que en index.html
// ✏️  Tus datos reales de Firebase
firebase.initializeApp({
  apiKey: "AIzaSyBW-DXRKumti5YDyFCqOHgWHAKYK-6AtQ",
  authDomain: "smartsonubalogictis.firebaseapp.com",
  projectId: "smartsonubalogictis",
  storageBucket: "smartsonubalogictis.firebasestorage.app",
  messagingSenderId: "692783709731",
  appId: "1:692783709731:web:f2cb16afd96e45abed7b96"
});

const messaging = firebase.messaging();

// ── Notificaciones en SEGUNDO PLANO ──
// Cuando la app está cerrada o en background, FCM llama a este handler.
messaging.onBackgroundMessage(payload => {
  console.log('[SW] Notificación en background:', payload);

  const { title = '📦 MudanzaApp', body = 'Nueva actualización', icon = '/icon-192.png' }
    = payload.notification || {};

  self.registration.showNotification(title, {
    body,
    icon,
    badge:  '/icon-192.png',
    vibrate: [200, 100, 200],
    data:   payload.data || {},
    actions: [{ action: 'open', title: 'Ver inventario' }]
  });
});

// ── Click en la notificación ──
self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      for (const client of list) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          return client.focus();
        }
      }
      return clients.openWindow('/');
    })
  );
});

// ── Cache básico para PWA offline-first ──
self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(CACHE_FILES))
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  // Solo cachea GET de la propia app, deja pasar Firebase/CDN
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (!url.origin.includes(self.location.hostname)) return;

  // Red primero (así cada deploy se ve al momento); la caché solo se usa sin conexión
  event.respondWith(
    fetch(event.request).then(res => {
      if (res.ok && CACHE_FILES.includes(url.pathname)) {
        const copy = res.clone();
        caches.open(CACHE_NAME).then(c => c.put(event.request, copy));
      }
      return res;
    }).catch(() => caches.match(event.request))
  );
});
