const eventName = "duka:session-ended";
const storageKey = "duka.sessionEnded";

export function endSession(userId?: string) {
  window.dispatchEvent(new CustomEvent(eventName, { detail: userId }));
  try {
    localStorage.setItem(
      storageKey,
      JSON.stringify({ userId, nonce: crypto.randomUUID() }),
    );
  } catch {
    // Local logout still works when browser storage is unavailable.
  }
}

export function onSessionEnded(userId: string, logout: () => void) {
  const targetWindow = window;
  const local = (event: Event) => {
    const target = (event as CustomEvent<string | undefined>).detail;
    if (!target || target === userId) logout();
  };
  const storage = (event: StorageEvent) => {
    if (event.key !== storageKey || !event.newValue) return;
    try {
      const value = JSON.parse(event.newValue);
      if (value && (!value.userId || value.userId === userId)) logout();
    } catch {
      // Ignore unrelated or malformed browser storage.
    }
  };
  targetWindow.addEventListener(eventName, local);
  targetWindow.addEventListener("storage", storage);
  return () => {
    targetWindow.removeEventListener(eventName, local);
    targetWindow.removeEventListener("storage", storage);
  };
}
