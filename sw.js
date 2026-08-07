// Service Worker - 离线缓存 & 后台更新
const CACHE_NAME = 'probiotic-hotspot-v2';
const STATIC_ASSETS = [
  '/widget.html',
  '/archive.html',
  '/slides.html',
  '/manifest.json',
  '/manifest-slides.json',
  '/icon-192.png',
  '/icon-512.png'
];

// 安装：预缓存静态资源
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

// 激活：清理旧缓存
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// 网络优先，失败回退缓存（HTML 页面）
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // 仅处理同源请求
  if (url.origin !== location.origin) return;

  // HTML 页面：网络优先
  if (event.request.mode === 'navigate' || event.request.headers.get('accept')?.includes('text/html')) {
    event.respondWith(
      fetch(event.request)
        .then((resp) => {
          const copy = resp.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
          return resp;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // 其它资源：缓存优先
  event.respondWith(
    caches.match(event.request).then((cached) =>
      cached || fetch(event.request).then((resp) => {
        const copy = resp.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        return resp;
      })
    )
  );
});

// 接收 skipWaiting 消息
self.addEventListener('message', (event) => {
  if (event.data === 'skipWaiting') self.skipWaiting();
});