import { useSyncExternalStore } from "react";
import { Check, Monitor, Moon, Sun } from "lucide-react";
import { setThemePreference, subscribeTheme, themeSnapshot } from "./theme";
import type { ThemePreference } from "./theme";
import { fromScreen } from "./uiScale";

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

type ViewTransition = { ready: Promise<void> };
type TransitionDocument = Document & {
  startViewTransition?: (update: () => void) => ViewTransition;
};

/**
 * Switch theme with the new look spreading out in a circle from the button
 * that was pressed. Browsers without view transitions just switch.
 */
function revealTheme(value: ThemePreference, from: HTMLElement) {
  const doc = document as TransitionDocument;
  const before = document.documentElement.dataset.theme;
  const after =
    value === "system"
      ? window.matchMedia?.("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light"
      : value;
  const reduced = window.matchMedia?.(
    "(prefers-reduced-motion: reduce)",
  ).matches;
  // Same look before and after (e.g. "System" while already dark): no circle.
  if (!doc.startViewTransition || reduced || before === after)
    return setThemePreference(value);
  const box = from.getBoundingClientRect();
  const centerX = box.left + box.width / 2;
  const centerY = box.top + box.height / 2;
  // Screen pixels → CSS pixels, since the interface may be zoomed.
  const x = fromScreen(centerX);
  const y = fromScreen(centerY);
  const radius = fromScreen(
    Math.hypot(
      Math.max(centerX, window.innerWidth - centerX),
      Math.max(centerY, window.innerHeight - centerY),
    ),
  );
  const transition = doc.startViewTransition(() => setThemePreference(value));
  void transition.ready.then(() =>
    document.documentElement.animate(
      {
        clipPath: [
          `circle(0px at ${x}px ${y}px)`,
          `circle(${radius}px at ${x}px ${y}px)`,
        ],
      },
      {
        duration: 650,
        easing: "cubic-bezier(0.4, 0, 0.2, 1)",
        pseudoElement: "::view-transition-new(root)",
      },
    ),
  );
}

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
            onClick={(event) =>
              revealTheme(theme.id as ThemePreference, event.currentTarget)
            }
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
