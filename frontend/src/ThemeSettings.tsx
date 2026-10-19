import { useSyncExternalStore } from "react";
import { Check, Monitor, Moon, Sun } from "lucide-react";
import { setThemePreference, subscribeTheme, themeSnapshot } from "./theme";
import type { ThemePreference } from "./theme";

const themes = [
  {
    id: "light",
    label: "E çelët",
    description: "Sfond i çelët dhe ngjyra të lehta.",
    icon: Sun,
  },
  {
    id: "dark",
    label: "E errët",
    description: "Sfond i errët dhe kontrast i qartë.",
    icon: Moon,
  },
  {
    id: "system",
    label: "Sipas sistemit",
    description: "Ndiq automatikisht pamjen e pajisjes.",
    icon: Monitor,
  },
] as const;

export function ThemeSettings() {
  const [preference, resolved] = useSyncExternalStore(
    subscribeTheme,
    themeSnapshot,
  ).split(":");
  return (
    <section className="panel appearance-settings">
      <h2>Pamja</h2>
      <p className="muted">
        Zgjidhni temën e kësaj pajisjeje. Zgjedhja ruhet në këtë shfletues.
      </p>
      <div
        className="theme-options"
        role="group"
        aria-label="Tema e aplikacionit"
      >
        {themes.map((theme) => (
          <button
            key={theme.id}
            type="button"
            className="theme-option"
            aria-pressed={preference === theme.id}
            onClick={() => setThemePreference(theme.id as ThemePreference)}
          >
            <span
              className={`theme-preview theme-preview-${theme.id}`}
              aria-hidden="true"
            >
              <span />
              <span>
                <i />
                <i />
                <i />
              </span>
            </span>
            <span className="theme-option-title">
              <theme.icon size={18} />
              {theme.label}
              {preference === theme.id && <Check size={17} />}
            </span>
            <small>{theme.description}</small>
          </button>
        ))}
      </div>
      <p className="theme-status" role="status">
        Pamja aktive: {resolved === "dark" ? "e errët" : "e çelët"}.
        {preference === "system" && " Ndryshon bashkë me cilësimet e sistemit."}
      </p>
    </section>
  );
}
