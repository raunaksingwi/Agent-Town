// Agent Town's service worker: what makes the chat app installable, and shows notifications
// (backend/app/push.py sends them) even when the app is closed. It caches nothing but a fallback
// page: everything an agent says is live, so an offline copy would only mislead.

const OFFLINE = '<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">' +
  '<body style="font:16px system-ui;background:#1f3f68;color:#f6ebcf;display:grid;place-items:center;height:100vh;margin:0">' +
  '<p>You\'re offline. Your agents will be here when you\'re back.</p>'

self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()))

self.addEventListener('fetch', e => {
  if (e.request.mode !== 'navigate') return                     // only pages; the API and assets go straight through
  e.respondWith(fetch(e.request).catch(() => new Response(OFFLINE, { headers: { 'Content-Type': 'text/html' } })))
})

self.addEventListener('push', e => {
  let d = { title: 'Agent Town', body: '', tag: undefined, url: '/chat' }
  try { if (e.data) d = { ...d, ...e.data.json() } } catch { /* not JSON: the generic notice is better than none */ }
  e.waitUntil(self.registration.showNotification(d.title, {
    body: d.body, tag: d.tag, renotify: !!d.tag, icon: '/icon-192.png', badge: '/icon-192.png', data: { url: d.url || '/chat' },
  }))
})

// Tapping it opens that conversation: in the chat app if it's open, else in a new window (never on top
// of the town or the workspace someone is using)
self.addEventListener('notificationclick', e => {
  e.notification.close()
  const url = new URL(e.notification.data?.url || '/chat', self.location.origin).href
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
    const open = list.find(c => new URL(c.url).pathname.startsWith('/chat'))
    if (!open) return self.clients.openWindow(url)
    return open.navigate(url).then(c => (c || open).focus()).catch(() => self.clients.openWindow(url))
  }))
})
