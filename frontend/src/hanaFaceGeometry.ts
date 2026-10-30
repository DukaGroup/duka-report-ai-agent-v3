/**
 * Hana's face, measured on her portrait (public/brand/hana-portrait.webp),
 * in photo units: 0–100 across the square image. The talking mouth and the
 * blinking eyelids are drawn as meshes of the photograph itself; these
 * functions say where each point of the face moves.
 */
export type MouthShape = { open: number; round: number };
export type Point = [number, number];
type Region = { x: number; y: number; width: number; height: number };

const smoothstep = (a: number, b: number, x: number) => {
  const t = Math.max(0, Math.min(1, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};
/** Piecewise-linear curve through measured points, flat beyond the ends. */
const curve = (points: Point[]) => (x: number) => {
  if (x <= points[0][0]) return points[0][1];
  for (let i = 1; i < points.length; i++) {
    const [x0, y0] = points[i - 1];
    const [x1, y1] = points[i];
    if (x <= x1) return y0 + ((y1 - y0) * (x - x0)) / (x1 - x0);
  }
  return points[points.length - 1][1];
};

// ------------------------------------------------------------------ mouth

/** The line where her lips meet, corner to corner. */
export const seamY = curve([
  [43.45, 55.53],
  [44.99, 55.73],
  [46.99, 55.58],
  [47.98, 55.38],
  [48.98, 55.46],
  [49.98, 55.46],
  [50.97, 55.43],
  [51.97, 55.48],
  [52.97, 55.58],
  [53.96, 55.66],
  [54.96, 55.68],
  [56.31, 55.48],
]);
export const LIPS = {
  left: 43.45,
  right: 56.31,
  center: 49.9,
  /** Lips, chin and the cheeks between: everything the jaw moves. */
  region: { x: 36, y: 49.5, width: 28, height: 19 } as Region,
  chinBottom: 65,
};
// Movement sizes scale with the mouth: it spans ~12.9 photo units.
const U = (LIPS.right - LIPS.left) / 6.4;
const HALF = (LIPS.right - LIPS.left) / 2;

/**
 * How much of the opening each point along the lips gets: none at the
 * corners, most in the middle. Rounded vowels gather it toward the centre.
 */
export function opening(x: number, round: number) {
  const inset = round * 0.35 * U;
  const t = (x - (LIPS.left + inset)) / (LIPS.right - LIPS.left - inset * 2);
  if (t <= 0 || t >= 1) return 0;
  return Math.pow(Math.sin(Math.PI * t), 0.85 + 0.6 * round);
}

const LIP_DROP = 1.0 * U; // lower lip at the centre, mouth fully open
const JAW_DROP = 0.82 * U; // the chin
const LIP_LIFT = 0.2 * U; // upper lip

/**
 * Where a point of the face moves for a mouth shape. The mesh is split along
 * the lip line: `side` says which half a point belongs to. The halves part
 * between the corners and stay joined outside them.
 */
export function displaceMouth(
  x: number,
  y: number,
  side: "upper" | "lower",
  { open, round }: MouthShape,
): Point {
  const { region, center } = LIPS;
  const seam = seamY(x);
  const across =
    smoothstep(region.x, region.x + 3, x) *
    (1 - smoothstep(region.x + region.width - 3, region.x + region.width, x));
  const p = opening(x, round);
  let dy: number;
  if (side === "upper") {
    const lift = (open * LIP_LIFT + round * 0.05 * U) * p;
    dy = -lift * (1 - smoothstep(0, 1.25 * U, seam - y));
  } else {
    // At the lips the lower lip moves by its own opening; further down the
    // whole chin moves with the jaw, so the skin between stretches evenly.
    const lip = open * LIP_DROP * p;
    const jaw = open * JAW_DROP * Math.exp(-(((x - center) / (3.8 * U)) ** 2));
    const toward = smoothstep(0, 2.2 * U, y - seam);
    dy =
      (lip + (jaw - lip) * toward) *
      (1 - smoothstep(LIPS.chinBottom, region.y + region.height - 0.3, y));
  }
  // The corners pull in for rounded vowels and drop a touch as the jaw
  // opens. Both halves move alike here, so the corners stay sealed.
  const corner =
    Math.exp(-(((Math.abs(x - center) - HALF) / (1.1 * U)) ** 2)) *
    Math.exp(-(((y - seam) / (1.3 * U)) ** 2));
  dy += open * 0.08 * U * corner;
  const dx = -Math.sign(x - center) * (round * 0.8 + open * 0.12) * U * corner;
  return [dx * across, dy * across];
}

/** The inner edges of the lips: the outline of the open mouth. */
export function mouthOutline(shape: MouthShape, steps = 48) {
  const top: Point[] = [];
  const bottom: Point[] = [];
  for (let i = 0; i <= steps; i++) {
    const x = LIPS.left + ((LIPS.right - LIPS.left) * i) / steps;
    const y = seamY(x);
    const [ux, uy] = displaceMouth(x, y, "upper", shape);
    const [lx, ly] = displaceMouth(x, y, "lower", shape);
    top.push([x + ux, y + uy]);
    bottom.push([x + lx, y + ly]);
  }
  return { top, bottom };
}

/** How much a lip darkens at its inner edge as it turns into the mouth. */
export function innerLip(x: number, y: number, side: "upper" | "lower") {
  const distance = side === "upper" ? seamY(x) - y : y - seamY(x);
  return (1 - smoothstep(0, 0.3 * U, distance)) * opening(x, 0);
}

/** Upper teeth: fixed to the skull, a rounded arch behind the upper lip. */
export const TEETH = {
  half: 2.6 * U,
  edge: (x: number) =>
    seamY(x) + 0.16 * U - 0.35 * U * ((x - LIPS.center) / (2.4 * U)) ** 2,
  gaps: [-1.85, -1.2, -0.58, 0, 0.58, 1.2, 1.85].map((g) => g * U),
  unit: U,
};

// ------------------------------------------------------------------- eyes

/** Each eye: where the upper lid meets the eyeball, and the lower lid. */
const EYES = [
  {
    from: 38.0,
    to: 45.55,
    upper: curve([
      [38.0, 37.12],
      [39.17, 36.4],
      [40.04, 36.11],
      [40.99, 35.96],
      [42.07, 36.0],
      [43.02, 36.18],
      [43.96, 36.54],
      [44.68, 37.27],
      [45.55, 38.57],
    ]),
    lower: curve([
      [38.0, 37.12],
      [39.17, 37.92],
      [40.26, 38.28],
      [41.35, 38.5],
      [42.44, 38.57],
      [43.52, 38.5],
      [44.61, 38.36],
      [45.55, 38.57],
    ]),
  },
  {
    from: 54.72,
    to: 63.35,
    upper: curve([
      [54.72, 38.5],
      [55.81, 37.56],
      [57.04, 36.4],
      [57.99, 36.04],
      [59.07, 35.96],
      [60.16, 36.04],
      [61.25, 36.4],
      [62.34, 36.91],
      [63.35, 37.56],
    ]),
    lower: curve([
      [54.72, 38.5],
      [56.17, 38.57],
      [57.62, 38.57],
      [59.07, 38.5],
      [60.52, 38.21],
      [61.97, 37.78],
      [63.35, 37.56],
    ]),
  },
];
export const EYE_REGION: Region = { x: 35, y: 31.6, width: 31, height: 9.4 };
// The lashes stand about this far above the lid edge; they move as one band.
const LASHES = 1.0;
// How far the lid skin above the lashes stretches, up toward the brow.
const LID_SKIN = 1.6;
// The lower lid rises a little to meet the upper lid.
const LOWER_RISE = 0.2;

/**
 * Where a point moves when the eyes close by `blink` (0 open, 1 shut). The
 * upper lid with its lashes slides down to meet the lower lid, which rises a
 * touch; the lid skin above stretches and the eye beneath folds away.
 */
export function displaceEyes(x: number, y: number, blink: number): Point {
  if (blink <= 0) return [0, 0];
  for (const eye of EYES) {
    if (x < eye.from - 1 || x > eye.to + 1) continue;
    // Full movement across the eye, easing off just past the corners.
    const inside =
      smoothstep(eye.from - 0.7, eye.from + 0.5, x) *
      (1 - smoothstep(eye.to - 0.5, eye.to + 0.7, x));
    const upper = eye.upper(x);
    const lower = eye.lower(x);
    const closed = lower - LOWER_RISE;
    const travel = (closed - upper) * blink * inside;
    const rise = LOWER_RISE * blink * inside;
    if (y <= upper)
      return [0, travel * smoothstep(upper - LASHES - LID_SKIN, upper - LASHES, y)];
    if (y <= lower) {
      const top = upper + travel;
      const bottom = lower - rise;
      const t = lower > upper ? (y - upper) / (lower - upper) : 1;
      return [0, top + t * (bottom - top) - y];
    }
    return [0, -rise * (1 - smoothstep(lower, lower + 1.2, y))];
  }
  return [0, 0];
}
