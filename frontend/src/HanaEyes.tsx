import { useEffect, useRef } from "react";
import { HANA_PORTRAIT } from "./hanaAvatar";
import { createFaceWarp, gridMesh, loadImage, watchSize } from "./faceWarp";
import { displaceEyes, EYE_REGION } from "./hanaFaceGeometry";

const region = EYE_REGION;
const MESH = gridMesh(region, 124, [
  { rows: 64, y: (_, t) => region.y + region.height * t },
]);

// A blink closes quickly and opens more slowly, as real eyelids do.
const CLOSE = 80;
const HOLD = 30;
const OPEN = 160;
function lidAt(ms: number) {
  if (ms < CLOSE) return (ms / CLOSE) ** 2;
  if (ms < CLOSE + HOLD) return 1;
  const t = Math.min(1, (ms - CLOSE - HOLD) / OPEN);
  return 1 - t * t * (3 - 2 * t);
}

/**
 * Hana's eyelids. She blinks by herself at natural, irregular intervals and
 * now and then twice; the upper lid's own skin and lashes slide down over
 * the eye. Place inside a box that spans the whole portrait.
 */
export function HanaEyes({ firstBlink = 1600 }: { firstBlink?: number }) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!box.current || !canvas.current) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    let cancelled = false,
      frame = 0,
      timer = 0;
    let render: ((moved: Float32Array) => void) | null = null;
    const moved = new Float32Array(MESH.source.length);
    const element = box.current;
    const size = watchSize(element, [canvas.current], () => {});

    const draw = (blink: number) => {
      element.style.visibility = blink > 0.001 ? "visible" : "hidden";
      if (blink <= 0.001 || !render) return;
      size.check();
      for (let i = 0; i < moved.length; i += 2) {
        const [dx, dy] = displaceEyes(MESH.source[i], MESH.source[i + 1], blink);
        moved[i] = MESH.source[i] + dx;
        moved[i + 1] = MESH.source[i + 1] + dy;
      }
      render(moved);
    };
    const blink = (twice: boolean) => {
      const start = performance.now();
      const length = CLOSE + HOLD + OPEN;
      const tick = (now: number) => {
        const ms = now - start;
        // A double blink: the second follows right after the first opens.
        const value = ms < length ? lidAt(ms) : twice ? lidAt(ms - length - 60) : 0;
        draw(ms > length && ms < length + 60 ? 0 : value);
        if (ms < (twice ? length * 2 + 60 : length)) frame = requestAnimationFrame(tick);
        else {
          draw(0);
          schedule(2200 + Math.random() * 3800);
        }
      };
      frame = requestAnimationFrame(tick);
    };
    const schedule = (delay: number) => {
      timer = window.setTimeout(() => {
        if (!cancelled) blink(Math.random() < 0.2);
      }, delay);
    };
    loadImage(HANA_PORTRAIT)
      .then((image) => {
        if (cancelled || !canvas.current) return;
        render = createFaceWarp(canvas.current, image, region, MESH);
        schedule(firstBlink + Math.random() * 600);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
      clearTimeout(timer);
      cancelAnimationFrame(frame);
      size.stop();
    };
  }, [firstBlink]);

  return (
    <div
      ref={box}
      className="hana-face-layer"
      style={{
        left: `${region.x}%`,
        top: `${region.y}%`,
        width: `${region.width}%`,
        height: `${region.height}%`,
      }}
      aria-hidden="true"
    >
      <canvas ref={canvas} />
    </div>
  );
}
