export type ThemePreference = "light" | "dark" | "system";
const storageKey = "duka.theme";
let preference: ThemePreference = "system";
let media: MediaQueryList | null = null;
let initialized = false;
const listeners = new Set<() => void>();

function normalize(value: string | null): ThemePreference {
  return value === "light" || value === "dark" ? value : "system";
}

function applyTheme() {
  const resolved =
    preference === "system" ? (media?.matches ? "dark" : "light") : preference;
  document.documentElement.dataset.theme = resolved;
  document.documentElement.dataset.themePreference = preference;
  document.documentElement.style.colorScheme = resolved;
  for (const listener of listeners) listener();
}

export function initializeTheme() {
  if (initialized) return () => {};
  initialized = true;
  try {
    preference = normalize(localStorage.getItem(storageKey));
  } catch {
    // Storage may be blocked; changes still work for the current session.
  }
  media = window.matchMedia("(prefers-color-scheme: dark)");
  const changed = () => applyTheme();
  const stored = (event: StorageEvent) => {
    if (event.key !== storageKey && event.key !== null) return;
    preference = normalize(event.newValue);
    applyTheme();
  };
  media.addEventListener("change", changed);
  window.addEventListener("storage", stored);
  applyTheme();
  return () => {
    media?.removeEventListener("change", changed);
    window.removeEventListener("storage", stored);
    initialized = false;
  };
}

export function setThemePreference(value: ThemePreference) {
  preference = normalize(value);
  try {
    localStorage.setItem(storageKey, preference);
  } catch {
    // Applying a theme must not depend on successful persistence.
  }
  applyTheme();
}

export function themeSnapshot() {
  return `${preference}:${document.documentElement.dataset.theme || "light"}`;
}

export function subscribeTheme(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
