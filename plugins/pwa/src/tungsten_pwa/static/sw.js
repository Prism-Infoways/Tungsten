/* Tungsten PWA service worker.
 *
 * The panel puts its settings in front of this file: self.TW_PWA = {...}.
 *
 * Rules:
 * - Pages are never cached. They always come from the server, so nobody sees
 *   old data or another person's data. When the network is down, the offline
 *   page is shown instead.
 * - Form posts, HTMX requests, downloads and anything that is not a GET are
 *   left alone, so CSRF, login and logout work as before.
 * - Only CSS, JavaScript, images and fonts are cached. Files with a ?v= hash
 *   never change, so they come from the cache first; other static files are
 *   shown from the cache and refreshed in the background.
 */
(function () {
  "use strict";

  var C = self.TW_PWA || {};
  var PREFIX = C.cachePrefix || "tungsten-pwa-";
  var STATIC = PREFIX + "static-" + C.version;
  var RUNTIME = PREFIX + "runtime-" + C.version;
  var MAX_RUNTIME = 80;
  var DESTINATIONS = ["style", "script", "image", "font"];
  var scope = new URL(self.registration.scope).pathname;

  function noop() {}

  function ownOldCaches(keep) {
    return caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (k) {
        return k.indexOf(PREFIX) === 0 && keep.indexOf(k) === -1;
      }).map(function (k) { return caches.delete(k); }));
    });
  }

  // PWAPlugin(uninstall=True): clean up and remove this worker from every browser that has it.
  if (C.uninstall) {
    self.addEventListener("install", function () { self.skipWaiting(); });
    self.addEventListener("activate", function (event) {
      event.waitUntil(ownOldCaches([]).then(function () { return self.registration.unregister(); }));
    });
    return;
  }

  self.addEventListener("install", function (event) {
    event.waitUntil(caches.open(STATIC).then(function (cache) {
      // the offline page must be saved, or the install fails and the browser tries again later
      return cache.add(new Request(C.offline, { cache: "reload" })).then(function () {
        return Promise.all((C.precache || []).map(function (url) {
          return cache.add(new Request(url, { cache: "reload" })).catch(noop);
        }));
      });
    }).then(function () {
      // safe to take over at once: pages are never served from the cache
      return self.skipWaiting();
    }));
  });

  self.addEventListener("activate", function (event) {
    event.waitUntil(Promise.all([
      ownOldCaches([STATIC, RUNTIME]),
      self.registration.navigationPreload ? self.registration.navigationPreload.enable().catch(noop) : null
    ]).then(function () { return self.clients.claim(); }));
  });

  function cacheable(res) {
    if (!res || res.status !== 200 || res.type !== "basic") return false;
    return !/no-store|private/i.test(res.headers.get("Cache-Control") || "");
  }

  function offlinePage() {
    return caches.match(C.offline, { cacheName: STATIC }).then(function (hit) {
      return hit || new Response("You are offline.", {
        status: 503, headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" }
      });
    });
  }

  function navigate(event) {
    var preload = Promise.resolve(event.preloadResponse);
    event.waitUntil(preload.catch(noop));
    return preload.then(function (res) {
      return res || fetch(event.request);
    }).catch(offlinePage);
  }

  function cacheFirst(req) {
    return caches.open(STATIC).then(function (cache) {
      return cache.match(req).then(function (hit) {
        if (hit) return hit;
        return fetch(req).then(function (res) {
          if (cacheable(res)) cache.put(req, res.clone()).catch(noop);
          return res;
        });
      });
    });
  }

  function trim(cache) {
    return cache.keys().then(function (keys) {
      var extra = keys.length - MAX_RUNTIME;
      return Promise.all(keys.slice(0, Math.max(extra, 0)).map(function (k) { return cache.delete(k); }));
    });
  }

  function staleWhileRevalidate(event) {
    var req = event.request;
    return caches.open(RUNTIME).then(function (cache) {
      return cache.match(req).then(function (hit) {
        var fresh = fetch(req).then(function (res) {
          if (cacheable(res)) {
            return cache.put(req, res.clone()).then(function () { return trim(cache); }).catch(noop).then(function () {
              return res;
            });
          }
          return res;
        });
        if (hit) {
          event.waitUntil(fresh.catch(noop));
          return hit;
        }
        return fresh;
      });
    });
  }

  function isStaticFile(path) {
    return /\.(css|js|mjs|png|jpe?g|gif|webp|avif|svg|ico|woff2?|ttf|otf)$/i.test(path);
  }

  self.addEventListener("fetch", function (event) {
    var req = event.request;
    if (req.method !== "GET" || req.headers.has("range")) return;
    var url = new URL(req.url);
    if (url.origin !== self.location.origin || url.pathname === new URL(C.sw, self.location).pathname) return;

    if (req.mode === "navigate") {
      event.respondWith(navigate(event));
      return;
    }

    // never touch data requests (HTMX swaps, fetch() calls, exports): only real static files
    if (req.headers.has("HX-Request") || DESTINATIONS.indexOf(req.destination) === -1) return;
    var path = url.pathname;
    if (path.indexOf(scope) !== 0 || !isStaticFile(path)) return;
    var rest = path.slice(scope.length);
    if (rest.indexOf("assets/") === 0 && /(^|&)v=/.test(url.search.slice(1))) {
      event.respondWith(cacheFirst(req));
    } else if (rest.indexOf("assets/") === 0 || rest.indexOf("plugins/") === 0) {
      event.respondWith(staleWhileRevalidate(event));
    }
  });
})();
