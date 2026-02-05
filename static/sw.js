const CACHE_NAME = 'ai-reply-v7';
const ASSETS_TO_CACHE = [
    './',
    './index.html',
    './dashboard.css',
    './dashboard.js',
    './icon-192.png',
    './icon-512.png'
];

self.addEventListener('install', (event) => {
    // Force new service worker to become active immediately
    self.skipWaiting();
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => cache.addAll(ASSETS_TO_CACHE))
    );
});

self.addEventListener('activate', (event) => {
    // Claim clients immediately
    event.waitUntil(clients.claim());

    // Remove old caches
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map((cacheName) => {
                    if (cacheName !== CACHE_NAME) {
                        return caches.delete(cacheName);
                    }
                })
            );
        })
    );
});

self.addEventListener('fetch', (event) => {
    // For API requests, always go to network
    if (event.request.url.includes('/api/')) {
        return;
    }

    event.respondWith(
        caches.match(event.request)
            .then((response) => {
                // Return cached response if found
                if (response) {
                    return response;
                }
                // Otherwise fetch from network
                return fetch(event.request);
            })
    );
});
