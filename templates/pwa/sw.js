{% load static %}/* Service worker de Crecenta (versión {{ version }}).
   - Estáticos: primero caché.
   - Páginas: primero red; sin conexión, la última copia guardada o la página "sin conexión".
   - Registro rápido sin conexión: el POST del formulario se guarda en IndexedDB y se envía al
     recuperar la conexión (Background Sync, o aviso de la página en navegadores sin él). El
     servidor no duplica gracias al client_uuid. */
importScripts("{% static 'js/offline-queue.js' %}");

const VERSION = "{{ version }}";
const STATIC_CACHE = "crecenta-static-" + VERSION;
const PAGES_CACHE = "crecenta-paginas";
const PRECACHE = {{ precache_json|safe }};
const OFFLINE_URL = "{{ offline_url }}";
const SAVED_URL = "{{ saved_url }}";
const SYNC_TAG = "sync-movimientos";
const QUICK_ENTRY = /\/e\/[0-9a-f-]+\/movimientos\/nuevo\/$/;

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key.startsWith("crecenta-static-") && key !== STATIC_CACHE) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (request.method === "POST" && request.mode === "navigate" && QUICK_ENTRY.test(url.pathname)) {
    event.respondWith(postOrQueue(event));
    return;
  }
  if (request.method !== "GET") return;
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(cacheFirst(request));
  } else if (request.mode === "navigate") {
    event.respondWith(networkFirst(request));
  }
});

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) (await caches.open(STATIC_CACHE)).put(request, response.clone());
  return response;
}

async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response.ok && !response.redirected && response.type === "basic") {
      (await caches.open(PAGES_CACHE)).put(request, response.clone());
    }
    return response;
  } catch (error) {
    const cached = await caches.match(request);
    return cached || (await caches.match(OFFLINE_URL)) || Response.error();
  }
}

function itemFromForm(form, url) {
  return {
    client_uuid: form.get("client_uuid"),
    account_id: form.get("account"),
    category_id: form.get("category") || "",
    amount: form.get("amount"),
    kind: form.get("kind"),
    date: form.get("date"),
    description: form.get("description") || "",
    source: "offline",
    syncUrl: url.pathname.replace(/nuevo\/$/, "sync/"),
    csrf: form.get("csrfmiddlewaretoken"),
    createdAt: Date.now(),
  };
}

async function postOrQueue(event) {
  const copy = event.request.clone();
  try {
    return await fetch(event.request);
  } catch (error) {
    const item = itemFromForm(await copy.formData(), new URL(copy.url));
    await self.CrecentaQueue.add(item);
    try { await self.registration.sync.register(SYNC_TAG); } catch (e) { /* sin Background Sync */ }
    await notify({ type: "queued" });
    return Response.redirect(SAVED_URL, 303);
  }
}

async function notify(message) {
  for (const client of await self.clients.matchAll({ includeUncontrolled: true })) {
    client.postMessage(message);
  }
}

let flushing = null;

function flush(freshToken) {
  // Evita dos envíos simultáneos (sync + aviso de la página).
  flushing = flushing || doFlush(freshToken).finally(() => { flushing = null; });
  return flushing;
}

async function doFlush(freshToken) {
  const items = (await self.CrecentaQueue.all()).filter((i) => !i.error);
  const groups = {};
  for (const item of items) (groups[item.syncUrl] = groups[item.syncUrl] || []).push(item);
  let sent = 0;
  for (const [syncUrl, group] of Object.entries(groups)) {
    const response = await fetch(syncUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": freshToken || group[0].csrf },
      body: JSON.stringify({
        items: group.map(({ syncUrl: _u, csrf: _c, createdAt: _t, error: _e, ...data }) => data),
      }),
    });
    if (!response.ok) continue; // sesión cerrada u otro espacio: se reintenta luego
    const data = await response.json();
    for (const result of data.resultados) {
      if (result.estado === "error") {
        await self.CrecentaQueue.markError(result.client_uuid, result.errores);
      } else {
        await self.CrecentaQueue.remove(result.client_uuid);
        sent += 1;
      }
    }
  }
  await notify({ type: "synced", count: sent });
  return sent;
}

self.addEventListener("sync", (event) => {
  if (event.tag === SYNC_TAG) event.waitUntil(flush());
});

self.addEventListener("message", (event) => {
  const data = event.data || {};
  if (data.type === "flush") event.waitUntil(flush(data.csrf).catch(() => 0));
  if (data.type === "logout") event.waitUntil(caches.delete(PAGES_CACHE));
});
