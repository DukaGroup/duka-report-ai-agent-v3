import { platform, type Platform } from "@floating-ui/react-dom";
import type { CSSProperties } from "react";

/*
 * The whole interface grows on large screens so text and controls are never
 * tiny. Up to about 1440 × 860 everything is shown at its normal size; above
 * that it scales with the screen (up to 1.6×), using CSS zoom on the page.
 *
 * Under zoom, screen coordinates (getBoundingClientRect, mouse positions) are
 * real pixels while CSS lengths are multiplied by the zoom. Anything placed
 * from screen coordinates divides by `uiZoom()`; viewport units in CSS are
 * divided by `--ui-zoom`.
 */

const BASE_WIDTH = 1440;
const BASE_HEIGHT = 860;
const MAX_ZOOM = 1.6;

let zoom = 1;
let initialized = false;

export const uiZoom = () => zoom;

// The zoom for a screen size, in steps of 0.05 so it does not flicker while
// a window is being resized.
export function zoomFor(width: number, height: number) {
  const fit = Math.min(width / BASE_WIDTH, height / BASE_HEIGHT);
  return Math.min(MAX_ZOOM, Math.max(1, Math.floor(fit * 20) / 20));
}

function apply() {
  const next = zoomFor(window.innerWidth, window.innerHeight);
  if (initialized && next === zoom) return;
  zoom = next;
  const root = document.documentElement;
  root.style.setProperty("--ui-zoom", String(zoom));
  root.style.zoom = zoom === 1 ? "" : String(zoom);
}

export function initializeUiScale() {
  if (initialized) return;
  apply();
  initialized = true;
  let frame = 0;
  window.addEventListener("resize", () => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(apply);
  });
}

/** Screen pixels → CSS pixels. */
export const fromScreen = (pixels: number) => pixels / zoom;

/*
 * Floating UI (tooltips and menus) works in screen pixels. Under zoom it
 * needs the popup's real on-screen size and the real screen as its
 * boundary, and its result must be converted back to CSS pixels.
 */
export const zoomedPlatform: Platform = {
  ...platform,
  async getDimensions(element) {
    if (zoom === 1) return platform.getDimensions(element);
    const box = element as HTMLElement;
    return { width: box.offsetWidth * zoom, height: box.offsetHeight * zoom };
  },
};

export function screenBoundary() {
  if (zoom === 1) return {};
  const rect = { x: 0, y: 0, width: window.innerWidth, height: window.innerHeight };
  return { boundary: rect, rootBoundary: rect };
}

export function unzoomed(styles: CSSProperties): CSSProperties {
  if (zoom === 1) return styles;
  const convert = (value: CSSProperties["left"]) =>
    typeof value === "number" ? value / zoom : value;
  return { ...styles, left: convert(styles.left), top: convert(styles.top) };
}
