{% load static %}// Service worker for push notifications (crags/push.py), served at /sw.js.
//
// It does two things only:
// - push: show a quiet notification (no sound, no vibration) and set the number
//   on the app icon; all notifications share one slot, so a new one replaces
//   the previous one instead of piling up.
// - notification click: open the page it is about.
// It stores nothing and does not intercept requests (no "fetch" handler).

const ICON = "{% static 'icons/icon-192.png' %}";
const FALLBACK_URL = "{% url 'notifications' %}";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
    let data = {};
    try {
        data = event.data ? event.data.json() : {};
    } catch (error) {
        data = {};
    }
    const work = [
        self.registration.showNotification(data.title || "gr8base", {
            body: data.body || "",
            icon: ICON,
            tag: "gr8base",
            renotify: false,
            silent: true,
            data: { url: data.url || FALLBACK_URL },
        }),
    ];
    if ("setAppBadge" in self.navigator) {
        const count = Number(data.badge) || 0;
        work.push(count > 0 ? self.navigator.setAppBadge(count) : self.navigator.clearAppBadge());
    }
    event.waitUntil(Promise.all(work).catch(() => {}));
});

self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    const target = new URL(event.notification.data?.url || FALLBACK_URL, self.location.origin).href;
    event.waitUntil(
        self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
            const open = windows.find((client) => "navigate" in client);
            if (open) {
                return open.navigate(target).then((client) => (client || open).focus());
            }
            return self.clients.openWindow(target);
        })
    );
});
