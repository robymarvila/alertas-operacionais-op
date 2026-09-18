// ==========================================================================
// Service Worker - Alertas Operacionais OP (CCO & Entrega de Equipes)
// PWA Caching, Shell Offline & Background Network-First Synchronization
// ==========================================================================

const CACHE_NAME = 'alertas-cco-pwa-v5.0.8-export-fix';

// Core shell assets to pre-cache on install
const PRECACHE_ASSETS = [
    '/',
    '/#hub',
    '/static/css/dashboard.css?v=5.0.8-export-fix',
    '/static/js/app.js?v=5.0.8-export-fix',
    '/static/manifest.webmanifest',
    '/static/icons/icon-192.png',
    '/static/icons/icon-512.png',
    '/static/icons/icon.svg',
    '/static/icons/favicon.svg',
    'https://unpkg.com/lucide@latest',
    'https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js',
    'https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js',
    'https://cdn.jsdelivr.net/npm/flatpickr/dist/flatpickr.min.css',
    'https://cdn.jsdelivr.net/npm/flatpickr',
    'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2'
];

// 1. Install Event: Pre-cache App Shell
self.addEventListener('install', (event) => {
    self.skipWaiting();
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(PRECACHE_ASSETS).catch((err) => {
                console.warn('[PWA SW] Aviso ao cachear recursos estáticos iniciais:', err);
            });
        })
    );
});

// 2. Activate Event: Clean up legacy caches & claim clients immediately
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) => {
            return Promise.all(
                keys.map((k) => {
                    if (k !== CACHE_NAME) {
                        console.log('[PWA SW] Removendo cache legado:', k);
                        return caches.delete(k);
                    }
                })
            );
        }).then(() => self.clients.claim())
    );
});

// 3. Fetch Event: Hybrid Strategy
// - Navegação HTML (/): Network-First (sempre busca a versão mais recente e atualizada)
// - API Requests (/api/): Network-First com Cache Fallback
// - Static assets (CSS, JS, Fonts, Images): Stale-While-Revalidate
self.addEventListener('fetch', (event) => {
    const request = event.request;
    const url = new URL(request.url);

    // Ignora requisições não GET ou WebSockets
    if (request.method !== 'GET' || url.protocol.startsWith('ws')) {
        return;
    }

    // A. Navegação de Página e Documentos HTML: Network-First Mandatório
    const isNavigation = request.mode === 'navigate' || 
        (request.headers.get('accept') && request.headers.get('accept').includes('text/html')) ||
        url.pathname === '/' || 
        url.pathname === '/index.html';

    if (isNavigation) {
        event.respondWith(
            fetch(request)
                .then((response) => {
                    if (response && response.status === 200) {
                        const clone = response.clone();
                        caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
                    }
                    return response;
                })
                .catch(async () => {
                    const cached = await caches.match(request);
                    if (cached) return cached;
                    const rootCached = await caches.match('/');
                    if (rootCached) return rootCached;
                    return new Response('<h1>Offline</h1><p>Sem conexão com a rede.</p>', {
                        headers: { 'Content-Type': 'text/html; charset=utf-8' }
                    });
                })
        );
        return;
    }

    // B. Requisições de API: Network-First
    if (url.pathname.startsWith('/api/')) {
        event.respondWith(
            fetch(request)
                .then((response) => {
                    if (response && response.status === 200) {
                        const clone = response.clone();
                        caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
                    }
                    return response;
                })
                .catch(async () => {
                    const cached = await caches.match(request);
                    if (cached) return cached;
                    return new Response(
                        JSON.stringify({ status: 'offline', message: 'Sem conexão com a rede. Exibindo dados locais em cache.' }),
                        { headers: { 'Content-Type': 'application/json' } }
                    );
                })
        );
        return;
    }

    // C. App Shell & Assets Estáticos: Stale-While-Revalidate
    event.respondWith(
        caches.match(request).then((cachedResponse) => {
            const fetchPromise = fetch(request).then((networkResponse) => {
                if (networkResponse && networkResponse.status === 200) {
                    const responseClone = networkResponse.clone();
                    caches.open(CACHE_NAME).then((cache) => cache.put(request, responseClone));
                }
                return networkResponse;
            }).catch(() => {
                // Falha de rede silenciosa para assets em cache
            });

            return cachedResponse || fetchPromise;
        })
    );
});
