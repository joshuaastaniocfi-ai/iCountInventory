const CACHE_NAME = 'icebergINV-v1.0.1';
const urlsToCache = [
  '/',
  '/static/css/style.css',
  '/static/css/flatpickr.min.css',
  '/static/js/app.js',
  '/static/js/flatpickr.min.js',
  '/static/icons/icon_logo.png',
  '/scanner/mobile-scanner',
  '/scanner/scanner'
];

// Install event - cache resources
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => {
        console.log('Opened cache');
        return cache.addAll(urlsToCache);
      })
  );
});

// Fetch event - serve from cache when offline
self.addEventListener('fetch', (event) => {
  // Handle navigation requests specially
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .catch(() => {
          // If offline, redirect to scanner page
          return caches.match('/scanner/mobile-scanner') || 
                 Response.redirect('/scanner/mobile-scanner');
        })
    );
    return;
  }

  // Handle other requests normally
  event.respondWith(
    caches.match(event.request)
      .then((response) => {
        // Return cached version or fetch from network
        if (response) {
          return response;
        }
        return fetch(event.request);
      }
    )
  );
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cacheName) => {
          if (cacheName !== CACHE_NAME) {
            console.log('Deleting old cache:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
});

// Background sync for offline data
self.addEventListener('sync', (event) => {
  if (event.tag === 'background-sync') {
    event.waitUntil(doBackgroundSync());
  }
});

function doBackgroundSync() {
  // Handle offline data sync when connection is restored
  console.log('Background sync triggered');
  // Add your offline data sync logic here
}

// Push notification handling
self.addEventListener('push', (event) => {
  const options = {
    body: event.data ? event.data.text() : 'New notification from IcebergINV',
    icon: '/static/icons/icon_logo.png',
    badge: '/static/icons/icon_logo.png',
    vibrate: [100, 50, 100],
    data: {
      dateOfArrival: Date.now(),
      primaryKey: 1
    },
    actions: [
      {
        action: 'explore',
        title: 'Open App',
        icon: '/static/icons/icon_logo.png'
      },
      {
        action: 'close',
        title: 'Close',
        icon: '/static/icons/icon_logo.png'
      }
    ]
  };

  event.waitUntil(
    self.registration.showNotification('IcebergINV', options)
  );
});

// Notification click handling
self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  if (event.action === 'explore') {
    event.waitUntil(
      clients.openWindow('/')
    );
  }
});
