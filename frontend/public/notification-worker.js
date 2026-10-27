/* System notification delivery only: no app pages, chats or reports are cached. */
self.addEventListener("install", (event) =>
  event.waitUntil(self.skipWaiting()),
);
self.addEventListener("activate", (event) =>
  event.waitUntil(self.clients.claim()),
);
const validId = (value) =>
  typeof value === "string" && /^[a-zA-Z0-9_-]{1,128}$/.test(value);
function request(client, message) {
  return new Promise((resolve) => {
    const channel = new MessageChannel();
    const finish = (value) => {
      clearTimeout(timer);
      channel.port1.close();
      resolve(value);
    };
    const timer = setTimeout(() => finish(null), 500);
    channel.port1.onmessage = (event) => finish(event.data);
    client.postMessage(message, [channel.port2]);
  });
}
const view = (client) => request(client, { type: "duka-notification-state" });
self.addEventListener("push", (event) => {
  event.waitUntil(
    (async () => {
      let data;
      try {
        data = event.data.json();
      } catch {
        return;
      }
      if (
        data.type !== "reply-completed" ||
        ![data.userId, data.conversationId, data.messageId].every(validId)
      )
        return;
      // Recheck the currently signed-in member; an old push cannot cross an account switch.
      const response = await fetch(
        "/api/notifications/messages/" + encodeURIComponent(data.messageId),
        { credentials: "same-origin", cache: "no-store" },
      );
      if (!response.ok) return;
      const owned = await response.json();
      if (
        owned.userId !== data.userId ||
        owned.conversationId !== data.conversationId
      )
        return;
      const cache = await caches.open("duka-notification-ids-v1");
      const key = new URL(
        "/__notification_seen/" + data.userId + "/" + data.messageId,
        self.location.origin,
      ).href;
      if (await cache.match(key)) return;
      const windows = await self.clients.matchAll({
        type: "window",
        includeUncontrolled: true,
      });
      const views = await Promise.all(
        windows.map(async (client) => ({ client, state: await view(client) })),
      );
      const reading = views.some(
        ({ client, state }) =>
          client.focused &&
          client.visibilityState === "visible" &&
          state?.userId === data.userId &&
          state.page === "chat" &&
          state.conversationId === data.conversationId,
      );
      if (!reading) {
        // Exactly one signed-in tab supplies the chime. Closed, suspended or
        // autoplay-blocked tabs fall back to the device's notification sound.
        let sounded = false;
        for (const { client, state } of views) {
          if (state?.userId !== data.userId) continue;
          const result = await request(client, {
            type: "duka-notification-sound",
            userId: data.userId,
            messageId: data.messageId,
            expiresAt: Date.now() + 450,
          });
          if (result?.played === true) {
            sounded = true;
            break;
          }
        }
        await self.registration.showNotification("Hana", {
          body:
            owned.reportCount > 1
              ? "Raportet tuaja janë gati për t’u hapur ose shkarkuar."
              : owned.reportCount
                ? "Raporti juaj është gati për t’u hapur ose shkarkuar."
                : "Përgjigjja juaj është gati. Shtypni këtu për të hapur bisedën.",
          icon: "/brand/hana-avatar.png",
          lang: "sq",
          tag: "duka-reply-" + data.messageId,
          renotify: false,
          data,
          silent: sounded,
        });
      }
      await cache.put(key, new Response("seen"));
      const keys = await cache.keys();
      await Promise.all(
        keys
          .slice(0, Math.max(0, keys.length - 200))
          .map((old) => cache.delete(old)),
      );
    })().catch(() => undefined),
  );
});
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const data = event.notification.data;
  if (!data || ![data.userId, data.conversationId].every(validId)) return;
  event.waitUntil(
    (async () => {
      const url = new URL("/", self.location.origin);
      url.searchParams.set("conversation", data.conversationId);
      url.searchParams.set("notification_user", data.userId);
      const windows = await self.clients.matchAll({
        type: "window",
        includeUncontrolled: true,
      });
      for (const client of windows) {
        if (new URL(client.url).origin !== self.location.origin) continue;
        await client.focus();
        const state = await view(client);
        if (state?.userId === data.userId) {
          client.postMessage({
            type: "duka-open-conversation",
            userId: data.userId,
            conversationId: data.conversationId,
          });
        } else await client.navigate(url.href);
        return;
      }
      await self.clients.openWindow(url.href);
    })(),
  );
});
