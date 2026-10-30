import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  type MutableRefObject,
} from "react";
import { HANA_PORTRAIT } from "./hanaAvatar";
import { stepSpring } from "./hanaSpeech";
import { createFaceWarp, gridMesh, loadImage, watchSize } from "./faceWarp";
import {
  displaceMouth,
  innerLip,
  LIPS,
  mouthOutline,
  seamY,
  TEETH,
  type MouthShape,
  type Point,
} from "./hanaFaceGeometry";

export type { MouthShape };
export type MouthHandle = { set: (shape: MouthShape) => void };

/*
 * Hana's talking mouth, in two layers over her portrait:
 *
 * - underneath, the inside of the mouth (canvas 2D): a dark cavity, the
 *   tongue, lower teeth riding on the jaw, upper teeth fixed to the skull,
 *   the shadow the upper lip casts on them, and deep corners;
 * - on top, her own lips, chin and cheeks (WebGL): the photograph as a mesh
 *   split along the line between the lips. The jaw drops the lower lip and
 *   the chin together and the upper lip lifts slightly, so the skin
 *   stretches like skin instead of sliding in strips.
 *
 * Teeth are never faded in: they show exactly where the lips part over
 * them, as in a real mouth.
 */

const { region } = LIPS;
const MESH = gridMesh(region, 84, [
  {
    // Upper half: from the top of the region down to the lip line, with
    // rows bunched toward the lips where the detail is.
    rows: 30,
    y: (x, t) => region.y + (seamY(x) - region.y) * (1 - (1 - t) ** 1.7),
    shade: (x, y) => innerLip(x, y, "upper"),
  },
  {
    rows: 50,
    y: (x, t) => seamY(x) + (region.y + region.height - seamY(x)) * t ** 1.7,
    shade: (x, y) => innerLip(x, y, "lower"),
  },
]);
const SIDES = ["upper", "lower"] as const;

function movedMesh(shape: MouthShape, out: Float32Array) {
  for (let i = 0; i < MESH.band.length; i++) {
    const x = MESH.source[i * 2],
      y = MESH.source[i * 2 + 1];
    const [dx, dy] = displaceMouth(x, y, SIDES[MESH.band[i]], shape);
    out[i * 2] = x + dx;
    out[i * 2 + 1] = y + dy;
  }
  return out;
}

/** The inside of the mouth, drawn only where the lips have parted. */
function drawInterior(canvas: HTMLCanvasElement, shape: MouthShape) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (shape.open < 0.004) return;
  const sx = canvas.width / region.width,
    sy = canvas.height / region.height;
  ctx.setTransform(sx, 0, 0, sy, -region.x * sx, -region.y * sy);
  const u = TEETH.unit;
  const { top, bottom } = mouthOutline(shape);
  const cx = LIPS.center;
  const seam = seamY(cx);
  const middle = Math.floor(top.length / 2);
  const upperLip = top[middle][1];
  const lowerLip = bottom[middle][1];
  const outline = new Path2D();
  [...top, ...bottom.slice().reverse()].forEach(([x, y], i) =>
    i ? outline.lineTo(x, y) : outline.moveTo(x, y),
  );
  outline.closePath();
  ctx.save();
  ctx.clip(outline);
  const span = LIPS.right - LIPS.left;

  // The cavity: darkest deep inside, warmer toward the lips.
  const cavity = ctx.createRadialGradient(cx, (seam + lowerLip) / 2, 0, cx, seam, 3.4 * u);
  cavity.addColorStop(0, "#110709");
  cavity.addColorStop(0.55, "#2a1216");
  cavity.addColorStop(1, "#4b2328");
  ctx.fillStyle = cavity;
  ctx.fillRect(LIPS.left - u, upperLip - u, span + 2 * u, 4 * u);

  // The tongue rests low, behind the lower teeth, and moves with the jaw.
  // It fades out softly at every edge; it is never outlined.
  ctx.save();
  ctx.translate(cx, lowerLip + 0.15 * u);
  ctx.scale(2.3 * u, (0.5 + shape.open * 0.3) * u);
  const tongue = ctx.createRadialGradient(0, 0, 0, 0, 0, 1);
  tongue.addColorStop(0, "rgba(150, 76, 88, 0.75)");
  tongue.addColorStop(0.6, "rgba(118, 54, 64, 0.45)");
  tongue.addColorStop(1, "rgba(80, 34, 42, 0)");
  ctx.fillStyle = tongue;
  ctx.fillRect(-1, -1, 2, 2);
  ctx.restore();

  // Lower teeth ride on the jaw and only just peek over the lower lip, in
  // the lip's shadow and darker toward the sides.
  const lowerTop = lowerLip - (0.05 + shape.open * 0.09) * u;
  const lowerTeeth = new Path2D();
  for (let i = 0; i <= 24; i++) {
    const x = cx - 1.9 * u + (3.8 * u * i) / 24;
    const y = lowerTop + 0.2 * u * ((x - cx) / (1.9 * u)) ** 2 + (seamY(x) - seam);
    i ? lowerTeeth.lineTo(x, y) : lowerTeeth.moveTo(x, y);
  }
  lowerTeeth.lineTo(cx + 1.9 * u, lowerLip + 0.6 * u);
  lowerTeeth.lineTo(cx - 1.9 * u, lowerLip + 0.6 * u);
  lowerTeeth.closePath();
  const lower = ctx.createLinearGradient(0, lowerTop, 0, lowerLip + 0.2 * u);
  lower.addColorStop(0, "rgba(186, 178, 172, 0.55)");
  lower.addColorStop(1, "rgba(100, 84, 82, 0.2)");
  ctx.fillStyle = lower;
  ctx.fill(lowerTeeth);
  const lowerSides = ctx.createLinearGradient(cx - 1.9 * u, 0, cx + 1.9 * u, 0);
  lowerSides.addColorStop(0, "rgba(30, 10, 12, 0.9)");
  lowerSides.addColorStop(0.35, "rgba(30, 10, 12, 0)");
  lowerSides.addColorStop(0.65, "rgba(30, 10, 12, 0)");
  lowerSides.addColorStop(1, "rgba(30, 10, 12, 0.9)");
  ctx.fillStyle = lowerSides;
  ctx.fill(lowerTeeth);

  // Upper teeth with a softly rounded biting edge that curves up toward the
  // sides, like a dental arch.
  const teeth = new Path2D();
  const half = TEETH.half;
  for (let i = 0; i <= 48; i++) {
    const x = cx - half + (2 * half * i) / 48;
    i ? teeth.lineTo(x, seamY(x) - 0.8 * u) : teeth.moveTo(x, seamY(x) - 0.8 * u);
  }
  for (let i = 48; i >= 0; i--) {
    const x = cx - half + (2 * half * i) / 48;
    teeth.lineTo(x, TEETH.edge(x));
  }
  teeth.closePath();
  const enamel = ctx.createLinearGradient(0, seam - 0.4 * u, 0, TEETH.edge(cx));
  enamel.addColorStop(0, "#9b938e");
  enamel.addColorStop(0.55, "#d9d2ca");
  enamel.addColorStop(0.9, "#cdc6be");
  // The biting edge is slightly translucent.
  enamel.addColorStop(1, "#b4b2b4");
  ctx.fillStyle = enamel;
  ctx.fill(teeth);
  // Faint, soft gaps between the teeth.
  ctx.lineWidth = 0.03 * u;
  for (const offset of TEETH.gaps) {
    const x = cx + offset;
    ctx.strokeStyle = `rgba(110, 92, 86, ${offset === 0 ? 0.16 : 0.1})`;
    ctx.beginPath();
    ctx.moveTo(x, seamY(x) - 0.6 * u);
    ctx.lineTo(x + offset * 0.02, TEETH.edge(x) - 0.02 * u);
    ctx.stroke();
  }
  // Side teeth sit deeper in the mouth, so they fall into shadow.
  const sides = ctx.createLinearGradient(cx - half, 0, cx + half, 0);
  sides.addColorStop(0, "rgba(30, 10, 12, 0.85)");
  sides.addColorStop(0.3, "rgba(30, 10, 12, 0.15)");
  sides.addColorStop(0.5, "rgba(30, 10, 12, 0)");
  sides.addColorStop(0.7, "rgba(30, 10, 12, 0.15)");
  sides.addColorStop(1, "rgba(30, 10, 12, 0.85)");
  ctx.fillStyle = sides;
  ctx.fill(teeth);

  // The upper lip shades the top of the opening.
  const shade = ctx.createLinearGradient(0, upperLip, 0, upperLip + 0.45 * u);
  shade.addColorStop(0, "rgba(36, 10, 12, 0.6)");
  shade.addColorStop(1, "rgba(36, 10, 12, 0)");
  ctx.fillStyle = shade;
  ctx.fillRect(LIPS.left - u, upperLip - 0.5 * u, span + 2 * u, u);
  // Deep shadow in the corners.
  for (const [x, y] of [top[0], top[top.length - 1]] as Point[]) {
    const corner = ctx.createRadialGradient(x, y, 0, x, y, 1.5 * u);
    corner.addColorStop(0, "rgba(18, 5, 7, 0.95)");
    corner.addColorStop(1, "rgba(18, 5, 7, 0)");
    ctx.fillStyle = corner;
    ctx.fillRect(x - 1.6 * u, y - 1.6 * u, 3.2 * u, 3.2 * u);
  }
  ctx.restore();
}

/** Hana's mouth; place it inside a box that spans the whole portrait. */
export const HanaMouth = forwardRef<MouthHandle>(function HanaMouth(_, ref) {
  const box = useRef<HTMLDivElement>(null);
  const inside = useRef<HTMLCanvasElement>(null);
  const face = useRef<HTMLCanvasElement>(null);
  const render = useRef<((moved: Float32Array, shade: number) => void) | null>(null);
  const size = useRef<ReturnType<typeof watchSize> | null>(null);
  const shape = useRef<MouthShape>({ open: 0, round: 0 });
  const moved = useRef(new Float32Array(MESH.source.length));

  const draw = () => {
    const s = shape.current;
    const visible = s.open > 0.004 || s.round > 0.01;
    if (box.current) box.current.style.visibility = visible ? "visible" : "hidden";
    if (!visible || !inside.current) return;
    size.current?.check();
    drawInterior(inside.current, s);
    render.current?.(movedMesh(s, moved.current), s.open);
  };

  useImperativeHandle(ref, () => ({
    set(next) {
      shape.current = next;
      draw();
    },
  }));

  useEffect(() => {
    if (!box.current || !face.current || !inside.current) return;
    let cancelled = false;
    size.current = watchSize(box.current, [face.current, inside.current], draw);
    loadImage(HANA_PORTRAIT)
      .then((image) => {
        if (cancelled || !face.current) return;
        render.current = createFaceWarp(face.current, image, region, MESH);
        draw();
      })
      .catch(() => {});
    return () => {
      cancelled = true;
      size.current?.stop();
      render.current = null;
    };
  }, []);

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
      <canvas ref={inside} />
      <canvas ref={face} />
    </div>
  );
});

/**
 * Follows a target mouth shape with a soft spring every frame, so the jaw has
 * a little weight and never snaps between sounds.
 */
export function useMouthSpring(
  mouth: MutableRefObject<MouthHandle | null>,
  target: MutableRefObject<MouthShape>,
  onLevel?: (level: number) => void,
  enabled = true,
) {
  useEffect(() => {
    if (!enabled) return;
    let frame = 0;
    const current = { open: 0, round: 0 };
    const velocity = { open: 0, round: 0 };
    let drawn = { open: -1, round: -1 };
    let previous = performance.now();
    // Quick enough to keep up with her speaking pace, still without snapping.
    const stiffness = { open: 30, round: 20 };
    const step = (now: number) => {
      const dt = Math.min(0.05, (now - previous) / 1000);
      previous = now;
      for (const key of ["open", "round"] as const) {
        const next = stepSpring(
          current[key],
          velocity[key],
          target.current[key],
          stiffness[key],
          dt,
        );
        velocity[key] = next.velocity;
        current[key] = Math.max(0, Math.min(1, next.position));
      }
      if (
        Math.abs(current.open - drawn.open) > 0.002 ||
        Math.abs(current.round - drawn.round) > 0.004
      ) {
        drawn = { ...current };
        mouth.current?.set(drawn);
        onLevel?.(drawn.open);
      }
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [enabled]);
}
