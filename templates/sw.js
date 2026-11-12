// Minimal offline support: keep the pages a visitor opened and show them when
// the network is gone or too slow (weak signal at the crag).
//
// - Only pages the server marks with the {{ header }} header are stored
//   (home, crag list, crag pages, help). Everything else is never stored.
// - CSS, JS and photos are NOT stored here: the browser's normal cache already
//   keeps them (served as immutable) and uses them offline, too.
// - Logging in or out deletes all stored pages (shared devices).
//
// Served by Django at /sw.js with "Cache-Control: no-cache", so browsers pick
// up a new version on the next visit. Emergency off switch: see
// docs/technical-stack.md ("Offline support").

const CACHE = "pages-v1"; // change when the stored format changes; old caches are deleted
const OFFLINE_URL = "{{ offline_url }}";
const MARK = "{{ header }}";
const NETWORK_TIMEOUT_MS = 4000; // weak signal: show the saved copy after this
const MAX_PAGES = 50;
const CLEAR_ON_POST = "{{ clear_urls }}".split(" "); // login and logout URLs
// (template values stay inside strings, so this file is valid JavaScript as-is)

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE)
            .then((cache) => cache.add(OFFLINE_URL))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys()
            .then((keys) => Promise.all(
                keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))
            ))
            .then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", (event) => {
    const request = event.request;
    const url = new URL(request.url);
    if (url.origin !== self.location.origin) {
        return;
    }
    if (request.method === "POST" && CLEAR_ON_POST.includes(url.pathname)) {
        // login/logout: the request itself goes to the network as usual
        event.waitUntil(clearPages());
        return;
    }
    if (request.method !== "GET" || request.mode !== "navigate") {
        return; // CSS, JS, photos, forms: the browser handles them normally
    }

    let saving = Promise.resolve();
    const network = fetch(request).then((response) => {
        saving = remember(request, response.clone());
        return response;
    });
    // keep the stored copy up to date even if a saved copy was shown meanwhile
    event.waitUntil(network.then(() => saving).catch(() => {}));
    event.respondWith(answer(request, network));
});

async function answer(request, network) {
    try {
        return await withTimeout(network, NETWORK_TIMEOUT_MS);
    } catch (error) {
        const saved = await caches.match(request, { ignoreVary: true });
        if (saved) {
            return saved;
        }
        try {
            return await network; // no saved copy: the network is the only chance
        } catch (error) {
            return (await caches.match(OFFLINE_URL)) || Response.error();
        }
    }
}

async function remember(request, response) {
    const cache = await caches.open(CACHE);
    if (response.status === 404 || response.status === 410) {
        await cache.delete(request, { ignoreVary: true }); // removed crag: forget it
        return;
    }
    if (!response.ok || response.headers.get(MARK) !== "1") {
        return;
    }
    await cache.put(request, response);
    await trim(cache);
}

async function trim(cache) {
    // keys() lists entries oldest first; put() moves an updated page to the end
    const pages = (await cache.keys()).filter(
        (request) => new URL(request.url).pathname !== OFFLINE_URL
    );
    for (const request of pages.slice(0, Math.max(pages.length - MAX_PAGES, 0))) {
        await cache.delete(request);
    }
}

async function clearPages() {
    const cache = await caches.open(CACHE);
    for (const request of await cache.keys()) {
        if (new URL(request.url).pathname !== OFFLINE_URL) {
            await cache.delete(request);
        }
    }
}

function withTimeout(promise, ms) {
    return new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error("timeout")), ms);
        promise.then(
            (value) => { clearTimeout(timer); resolve(value); },
            (error) => { clearTimeout(timer); reject(error); }
        );
    });
}
