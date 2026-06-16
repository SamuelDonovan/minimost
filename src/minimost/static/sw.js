globalThis.addEventListener("install", () => globalThis.skipWaiting());
globalThis.addEventListener("activate", () => globalThis.clients.claim());

// Clicking an OS notification should focus an existing MiniMost tab/window if
// one is open, otherwise open a fresh one. Without this handler a clicked
// notification just dismisses and does nothing.
globalThis.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((wins) => {
        for (const w of wins) {
          if ("focus" in w) return w.focus();
        }
        if (clients.openWindow) return clients.openWindow("/");
      }),
  );
});

// Display notifications delivered via the Web Push protocol. MiniMost does not
// ship a push server (that would require a VAPID-signing dependency, which the
// app deliberately avoids), so this only fires if a push backend is added
// later. It is harmless otherwise and lets the SW surface OS notifications even
// when no tab is open.
globalThis.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { body: event.data?.text() };
  }
  event.waitUntil(
    globalThis.registration.showNotification(data.title || "MiniMost", {
      body: data.body || "You have a new message",
      icon: "/static/web-app-manifest-192x192.png",
      tag: data.tag || "minimost-push",
      renotify: true,
    }),
  );
});
