// Service Worker pour SOVEREIGN
const CACHE_NAME = 'sovereign-v2';
const OFFLINE_URL = '/offline';

// Fichiers à mettre en cache pour le mode hors-ligne
const STATIC_CACHE_URLS = [
  '/',
  '/offline',
  '/manifest.json',
  '/favicon.ico',
  '/icons/icon-96x96.png',
  '/icons/icon-192x192.png',
  '/icons/icon-512x512.png'
];

// ============================================
// INSTALLATION
// ============================================
self.addEventListener('install', (event) => {
  console.log('🔧 Service Worker installation...');
  
  event.waitUntil(
    (async () => {
      // Skip waiting pour prendre le contrôle immédiatement
      self.skipWaiting();
      
      // Cache les fichiers statiques pour le mode hors-ligne
      const cache = await caches.open(CACHE_NAME);
      await cache.addAll(STATIC_CACHE_URLS);
      console.log('✅ Fichiers statiques mis en cache');
    })()
  );
});

// ============================================
// ACTIVATION
// ============================================
self.addEventListener('activate', (event) => {
  console.log('✅ Service Worker activation...');
  
  event.waitUntil(
    (async () => {
      // Nettoyer les anciens caches
      const cacheNames = await caches.keys();
      await Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      );
      
      // Prendre le contrôle de tous les clients
      await clients.claim();
      console.log('✅ Service Worker activé et prêt');
    })()
  );
});

// ============================================
// GESTION DES NOTIFICATIONS PUSH
// ============================================
self.addEventListener('push', (event) => {
  console.log('📨 Push reçu:', event);
  
  // Valeurs par défaut
  let notificationData = {
    title: 'SOVEREIGN',
    body: 'Nouvelle notification',
    url: '/',
    icon: '/icons/icon-192x192.png',
    badge: '/icons/icon-96x96.png',
    tag: null,           // Pour éviter les doublons
    requireInteraction: true,  // Reste à l'écran jusqu'à interaction
    vibrate: [200, 100, 200],
    timestamp: Date.now()
  };
  
  // Extraire les données de la notification
  if (event.data) {
    try {
      const parsed = event.data.json();
      notificationData = { ...notificationData, ...parsed };
    } catch (e) {
      notificationData.body = event.data.text();
    }
  }
  
  // Configurer les options de la notification
  const options = {
    body: notificationData.body,
    icon: notificationData.icon,
    badge: notificationData.badge,
    vibrate: notificationData.vibrate,
    tag: notificationData.tag,
    renotify: false,           // Ne pas renvoyer si même tag
    requireInteraction: notificationData.requireInteraction,
    data: {
      url: notificationData.url,
      timestamp: notificationData.timestamp,
      type: notificationData.type || 'default'
    },
    actions: [
      { action: 'open', title: '📋 Voir' },
      { action: 'dismiss', title: '🔔 Plus tard' }
    ]
  };
  
  // Ajouter des actions spécifiques selon le type
  if (notificationData.type === 'task') {
    options.actions.unshift({ action: 'complete', title: '✅ Terminer' });
  } else if (notificationData.type === 'document') {
    options.actions.unshift({ action: 'review', title: '📄 Voir document' });
  } else if (notificationData.type === 'win') {
    options.actions.unshift({ action: 'celebrate', title: '🎉 Célébrer' });
  } else if (notificationData.type === 'brief') {
    options.actions.unshift({ action: 'read', title: '📖 Lire le brief' });
  }
  
  event.waitUntil(
    self.registration.showNotification(notificationData.title, options)
  );
});

// ============================================
// GESTION DU CLIC SUR NOTIFICATION
// ============================================
self.addEventListener('notificationclick', (event) => {
  console.log('🔔 Clic sur notification:', event.action);
  
  // Fermer la notification
  event.notification.close();
  
  // Déterminer l'URL en fonction de l'action
  let url = event.notification.data?.url || '/';
  const notificationType = event.notification.data?.type;
  
  switch (event.action) {
    case 'complete':
      url = '/tasks';
      break;
    case 'review':
      url = '/documents';
      break;
    case 'celebrate':
      url = '/wins';
      break;
    case 'read':
      url = '/brief';
      break;
    case 'open':
    default:
      url = event.notification.data?.url || '/';
      break;
  }
  
  // Gérer la navigation vers l'URL
  event.waitUntil(
    (async () => {
      // Vérifier si une fenêtre est déjà ouverte
      const windowClients = await clients.matchAll({
        type: 'window',
        includeUncontrolled: true
      });
      
      // Chercher une fenêtre existante
      for (const client of windowClients) {
        if (client.url.includes(new URL(url).pathname) && 'focus' in client) {
          await client.focus();
          if (client.url !== url) {
            await client.navigate(url);
          }
          return;
        }
      }
      
      // Ouvrir une nouvelle fenêtre
      if (clients.openWindow) {
        await clients.openWindow(url);
      }
    })()
  );
});

// ============================================
// MODE HORS-LIGNE (FALLBACK)
// ============================================
self.addEventListener('fetch', (event) => {
  // Ne pas intercepter les appels API
  if (event.request.url.includes('/api/')) {
    return;
  }
  
  event.respondWith(
    (async () => {
      try {
        // Essayer le réseau d'abord
        const response = await fetch(event.request);
        
        // Mettre en cache si c'est une ressource statique
        if (event.request.method === 'GET' && response.status === 200) {
          const cache = await caches.open(CACHE_NAME);
          cache.put(event.request, response.clone());
        }
        
        return response;
      } catch (error) {
        // Si hors-ligne, servir depuis le cache
        const cachedResponse = await caches.match(event.request);
        if (cachedResponse) {
          return cachedResponse;
        }
        
        // Fallback vers la page offline
        if (event.request.mode === 'navigate') {
          return caches.match(OFFLINE_URL);
        }
        
        return new Response('Hors-ligne', {
          status: 503,
          statusText: 'Service Unavailable'
        });
      }
    })()
  );
});

// ============================================
// SYNCHRONISATION EN ARRIÈRE-PLAN (Background Sync)
// ============================================
self.addEventListener('sync', (event) => {
  console.log('🔄 Background sync:', event.tag);
  
  if (event.tag === 'sync-tasks') {
    event.waitUntil(syncPendingTasks());
  } else if (event.tag === 'sync-wins') {
    event.waitUntil(syncPendingWins());
  }
});

// Synchroniser les tâches en attente
async function syncPendingTasks() {
  console.log('📤 Synchronisation des tâches...');
  
  const cache = await caches.open('pending-data');
  const requests = await cache.keys();
  
  for (const request of requests) {
    try {
      const response = await fetch(request);
      if (response.ok) {
        await cache.delete(request);
        console.log('✅ Tâche synchronisée');
      }
    } catch (error) {
      console.error('❌ Erreur sync tâche:', error);
    }
  }
}

async function syncPendingWins() {
  console.log('🏆 Synchronisation des victoires...');
  // Logique similaire pour les wins
}

// ============================================
// NOTIFICATION PERIODIQUE (Periodic Background Sync)
// ============================================
self.addEventListener('periodicsync', (event) => {
  console.log('⏰ Periodic sync:', event.tag);
  
  if (event.tag === 'daily-check') {
    event.waitUntil(checkDailyReminders());
  } else if (event.tag === 'weekly-report') {
    event.waitUntil(generateWeeklyReport());
  }
});

async function checkDailyReminders() {
  console.log('📋 Vérification quotidienne...');
  
  // Récupérer les données depuis l'API
  try {
    const response = await fetch('https://sovereign-bridge.onrender.com/api/check-and-notify');
    const data = await response.json();
    console.log(`${data.count} notification(s) envoyée(s)`);
  } catch (error) {
    console.error('Erreur vérification quotidienne:', error);
  }
}

async function generateWeeklyReport() {
  console.log('📊 Génération rapport hebdomadaire...');
  // Logique pour le rapport hebdomadaire
}

// ============================================
// MISE À JOUR DU SERVICE WORKER
// ============================================
self.addEventListener('message', (event) => {
  console.log('💬 Message reçu:', event.data);
  
  if (event.data === 'skipWaiting') {
    self.skipWaiting();
  } else if (event.data.type === 'CLEAR_CACHE') {
    event.waitUntil(clearCache());
  }
});

async function clearCache() {
  const cacheNames = await caches.keys();
  await Promise.all(cacheNames.map(name => caches.delete(name)));
  console.log('🧹 Cache nettoyé');
}

// ============================================
// NOTIFICATION PARLANTE (Text-to-Speech)
// ============================================
async function speakNotification(text) {
  // Vérifier si l'API Speech est disponible
  if ('speechSynthesis' in self) {
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'fr-FR';
    utterance.rate = 0.9;
    speechSynthesis.speak(utterance);
  }
}
