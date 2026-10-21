import { api } from "./api";

const preferenceKey = (userId: string) => `duka.deviceNotifications.${userId}`;
export function supportsDeviceNotifications() {
  return (
    window.isSecureContext &&
    "Notification" in window &&
    "serviceWorker" in navigator &&
    "PushManager" in window
  );
}
function saved(userId: string) {
  try {
    return localStorage.getItem(preferenceKey(userId)) === "true";
  } catch {
    return false;
  }
}
function save(userId: string, enabled: boolean) {
  try {
    localStorage.setItem(preferenceKey(userId), String(enabled));
  } catch {
    /* Optional preference storage. */
  }
}
function keyBytes(key: string) {
  const text = atob(
    key.replace(/-/g, "+").replace(/_/g, "/") +
      "=".repeat((4 - (key.length % 4)) % 4),
  );
  return Uint8Array.from(text, (c) => c.charCodeAt(0));
}
async function bind(userId: string) {
  const registration = await navigator.serviceWorker.register(
    "/notification-worker.js",
    { scope: "/", updateViaCache: "none" },
  );
  await navigator.serviceWorker.ready;
  const config = await api<{ public_key: string }>("/notifications/config");
  let subscription = await registration.pushManager.getSubscription();
  if (
    subscription?.options.applicationServerKey &&
    btoa(
      String.fromCharCode(
        ...new Uint8Array(subscription.options.applicationServerKey),
      ),
    )
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "") !== config.public_key
  ) {
    await subscription.unsubscribe();
    subscription = null;
  }
  subscription ??= await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: keyBytes(config.public_key),
  });
  await api("/notifications/subscriptions", {
    method: "POST",
    body: JSON.stringify(subscription.toJSON()),
  });
  save(userId, true);
  return true;
}
export async function restoreDeviceNotifications(userId: string) {
  if (
    !supportsDeviceNotifications() ||
    Notification.permission !== "granted" ||
    !saved(userId)
  )
    return false;
  return bind(userId);
}
export async function enableDeviceNotifications(userId: string) {
  if (!supportsDeviceNotifications())
    throw Error(
      "Njoftimet kërkojnë HTTPS dhe një shfletues që mbështet njoftimet e pajisjes.",
    );
  // Keep this before any await so the permission prompt retains the button gesture.
  const permission = await Notification.requestPermission();
  if (permission !== "granted")
    throw Error(
      "Njoftimet nuk u lejuan. Mund t’i aktivizoni te lejet e faqes në shfletues.",
    );
  return bind(userId);
}
export async function disableDeviceNotifications(userId: string) {
  const registration = await navigator.serviceWorker.getRegistration("/");
  const subscription = await registration?.pushManager.getSubscription();
  if (subscription) {
    await api("/notifications/subscriptions", {
      method: "DELETE",
      body: JSON.stringify({ endpoint: subscription.endpoint }),
    });
    await subscription.unsubscribe();
  }
  const notices = await registration?.getNotifications();
  notices?.forEach((notice) => notice.close());
  save(userId, false);
  return false;
}
