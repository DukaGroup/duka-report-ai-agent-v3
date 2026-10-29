import {
  forwardRef,
  useEffect,
  useId,
  useImperativeHandle,
  useRef,
  type MutableRefObject,
} from "react";
import { HANA_AVATAR } from "./hanaAvatar";
import { stepSpring } from "./hanaSpeech";

/*
 * Hana's talking mouth, drawn over her portrait.
 *
 * The painted lips themselves move: thin vertical slices of the upper lip
 * lift a little and slices of the lower lip drop, most in the middle and not
 * at all at the corners, the way a jaw opens. Behind them sits the inside of
 * the mouth: a dark, softly lit interior, upper teeth that stay fixed to the
 * upper jaw (so they show more as the lower lip drops), a tongue that moves
 * with the jaw, and shadows under the upper lip and in the corners.
 *
 * All coordinates are percent of the portrait image (a 100 × 100 viewBox).
 */

export type MouthShape = { open: number; round: number };

// Where her lips meet in the portrait, left to right.
// Measured on the supplied portrait, following the line between her lips.
const SEAM: [number, number][] = [
  [43.4, 55.76],
  [44.3, 55.86],
  [45.3, 55.96],
  [46.3, 55.86],
  [47.3, 55.66],
  [48.3, 55.66],
  [49.2, 55.76],
  [50.2, 55.76],
  [51.2, 55.76],
  [52.1, 55.66],
  [53.1, 55.76],
  [54.1, 55.86],
  [55.1, 55.96],
  [56.1, 55.76],
  [56.8, 55.8],
];
export const seamY = (x: number) => {
  if (x <= SEAM[0][0]) return SEAM[0][1];
  for (let i = 1; i < SEAM.length; i++) {
    const [x0, y0] = SEAM[i - 1];
    const [x1, y1] = SEAM[i];
    if (x <= x1) return y0 + ((y1 - y0) * (x - x0)) / (x1 - x0);
  }
  return SEAM.at(-1)![1];
};
const pt = (x: number, y: number) => `${x.toFixed(3)} ${y.toFixed(3)}`;

const LEFT = 43.8;
const RIGHT = 56.5;
const CENTER = 50.1;
// Largest jaw drop and upper lip lift, in percent of the portrait height.
const MAX_DROP = 1.65;
const MAX_LIFT = 0.22;

// How much of the opening each point of the mouth gets: none at the corners,
// most in the middle. Rounded vowels (o, u) gather it toward the centre.
export function profile(x: number, round: number) {
  const inset = round * 2.2;
  const left = LEFT + inset;
  const right = RIGHT - inset;
  const t = (x - left) / (right - left);
  if (t <= 0 || t >= 1) return 0;
  return Math.pow(Math.sin(Math.PI * t), 1.05 - 0.45 * round);
}

const SLICE_FROM = 42.5;
const SLICE_TO = 57.7;
const LOWER_SLICES = 120;
const UPPER_SLICES = 56;
const slices = (count: number) =>
  Array.from({ length: count }, (_, index) => {
    const width = (SLICE_TO - SLICE_FROM) / count;
    const x = SLICE_FROM + index * width;
    return { x, width, center: x + width / 2 };
  });
const LOWER = slices(LOWER_SLICES);
const UPPER = slices(UPPER_SLICES);

// The painted dark line where the lips meet stays in place (it belongs to the
// closed mouth); only the lips on either side of it move.
const LINE = 0.17;
const seamPoints = (offset: number) =>
  SEAM.map(([x, y]) => pt(x, y + offset)).join("L");
// The lower lip and the skin just under it.
const LOWER_CLIP = `M42.7 ${55.76 + LINE}L${seamPoints(LINE)}L57.4 ${55.8 + LINE}L57.1 57.8L55.3 59.3L50.1 60L45 59.3L43 57.8Z`;
// The upper lip and a little of the skin above it.
const UPPER_CLIP = `M42.7 ${55.76 - LINE}L${seamPoints(-LINE)}L57.4 ${55.8 - LINE}L57.1 54.8L54 53.2L50.1 53.5L46 53.2L43 54.8Z`;

function edge(
  from: number,
  to: number,
  steps: number,
  y: (x: number) => number,
) {
  return Array.from({ length: steps + 1 }, (_, i) => {
    const x = from + ((to - from) * i) / steps;
    return pt(x, y(x));
  });
}

export function mouthGeometry({ open, round }: MouthShape) {
  const drop = (x: number) => open * MAX_DROP * profile(x, round);
  const lift = (x: number) => open * MAX_LIFT * profile(x, round);
  // Slightly larger than the gap so the moving lips overlap its edges, and
  // thinning to nothing toward the corners, where the lips stay closed.
  const reach = (x: number) => Math.min(1, profile(x, 0) * 3.5);
  const overlap = LINE + 0.04;
  const top = edge(
    LEFT,
    RIGHT,
    32,
    (x) => seamY(x) - lift(x) - overlap * reach(x),
  );
  const bottom = edge(
    LEFT,
    RIGHT,
    32,
    (x) => seamY(x) + drop(x) + overlap * reach(x),
  ).reverse();
  const cavity = `M${top.join("L")}L${bottom.join("L")}Z`;
  // The inner edges of both lips, softly darkened where they turn inward.
  const upperEdge = `M${edge(LEFT + 0.5, RIGHT - 0.5, 28, (x) => seamY(x) - LINE - lift(x)).join("L")}`;
  const lowerEdge = `M${edge(LEFT + 0.5, RIGHT - 0.5, 28, (x) => seamY(x) + LINE + drop(x)).join("L")}`;
  const centerY = seamY(CENTER);
  const centerDrop = drop(CENTER);
  return {
    cavity,
    upperEdge,
    lowerEdge,
    // The tongue rests low and moves down with the jaw.
    tongueY: centerY + centerDrop * 0.82 + 0.2,
    tongueRy: 0.35 + centerDrop * 0.18,
    // Teeth and the inside only show once the mouth is really open.
    interior: Math.min(1, open * 3),
    teeth: Math.min(0.85, Math.max(0, (open - 0.2) / 0.45)),
    lower: LOWER.map((slice) => drop(slice.center)),
    upper: UPPER.map((slice) => -lift(slice.center)),
  };
}

// Upper incisors and the teeth next to them: fixed to the upper jaw, edges
// curving up toward the sides like a real dental arch.
const TEETH_HALF = 4.7;
const GAP_OFFSETS = [-3.6, -2.45, -1.25, 0, 1.25, 2.45, 3.6];
const teethBottom = (x: number) => {
  const d = Math.abs(x - CENTER) / TEETH_HALF;
  // Each tooth's biting edge is slightly rounded, so the edge dips between them.
  const notch = GAP_OFFSETS.reduce(
    (sum, offset) =>
      sum + 0.05 * Math.exp(-Math.pow((x - CENTER - offset) / 0.26, 2)),
    0,
  );
  return seamY(x) + 0.6 - 0.9 * Math.pow(d, 2.2) - notch;
};
const TEETH = (() => {
  const from = CENTER - TEETH_HALF;
  const to = CENTER + TEETH_HALF;
  const top = edge(from, to, 20, (x) => seamY(x) - 1.5);
  const bottom = edge(from, to, 90, teethBottom).reverse();
  return `M${top.join("L")}L${bottom.join("L")}Z`;
})();
// Faint gaps between the teeth, wider apart toward the sides.
const TOOTH_GAPS = GAP_OFFSETS.map((offset) => {
  const x = CENTER + offset;
  return {
    d: `M${pt(x, seamY(x) - 1.5)}L${pt(x + offset * 0.02, teethBottom(x) - 0.03)}`,
    opacity: offset === 0 ? 0.12 : Math.abs(offset) > 3 ? 0.06 : 0.09,
  };
});

export type MouthHandle = { set: (shape: MouthShape) => void };

export const HanaMouth = forwardRef<MouthHandle, { initial?: MouthShape }>(
  function HanaMouth({ initial = { open: 0, round: 0 } }, ref) {
    const id = useId().replace(/:/g, "");
    const cavity = useRef<SVGPathElement>(null);
    const cavityClip = useRef<SVGPathElement>(null);
    const upperEdge = useRef<SVGPathElement>(null);
    const lowerEdge = useRef<SVGPathElement>(null);
    const edges = useRef<SVGGElement>(null);
    const tongue = useRef<SVGEllipseElement>(null);
    const inside = useRef<SVGGElement>(null);
    const teeth = useRef<SVGGElement>(null);
    const lower = useRef<(SVGGElement | null)[]>([]);
    const upper = useRef<(SVGGElement | null)[]>([]);
    const first = mouthGeometry(initial);

    useImperativeHandle(ref, () => ({
      set(shape) {
        const g = mouthGeometry(shape);
        cavity.current?.setAttribute("d", g.cavity);
        cavityClip.current?.setAttribute("d", g.cavity);
        upperEdge.current?.setAttribute("d", g.upperEdge);
        lowerEdge.current?.setAttribute("d", g.lowerEdge);
        edges.current?.setAttribute("opacity", g.interior.toFixed(3));
        tongue.current?.setAttribute("cy", g.tongueY.toFixed(3));
        tongue.current?.setAttribute("ry", g.tongueRy.toFixed(3));
        inside.current?.setAttribute("opacity", g.interior.toFixed(3));
        teeth.current?.setAttribute("opacity", g.teeth.toFixed(3));
        g.lower.forEach((y, i) =>
          lower.current[i]?.setAttribute(
            "transform",
            `translate(0 ${y.toFixed(3)})`,
          ),
        );
        g.upper.forEach((y, i) =>
          upper.current[i]?.setAttribute(
            "transform",
            `translate(0 ${y.toFixed(3)})`,
          ),
        );
      },
    }));

    const ids = {
      cavity: `${id}-cavity`,
      lowerClip: `${id}-lower`,
      upperClip: `${id}-upper`,
      lowerMask: `${id}-lower-mask`,
      upperMask: `${id}-upper-mask`,
      soft: `${id}-soft`,
      blur: `${id}-blur`,
      depth: `${id}-depth`,
      sides: `${id}-sides`,
      enamel: `${id}-enamel`,
      teethSides: `${id}-teeth-sides`,
      slice: (kind: string, i: number) => `${id}-${kind}-${i}`,
    };
    const portrait = (kind: "lower" | "upper", i: number) => (
      <g clipPath={`url(#${ids.slice(kind, i)})`}>
        <g
          clipPath={`url(#${kind === "lower" ? ids.lowerClip : ids.upperClip})`}
        >
          <image
            href={HANA_AVATAR}
            x="0"
            y="0"
            width="100"
            height="100"
            preserveAspectRatio="none"
          />
        </g>
      </g>
    );

    return (
      <svg
        className="hana-mouth"
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <defs>
          <clipPath id={ids.cavity}>
            <path ref={cavityClip} d={first.cavity} />
          </clipPath>
          <clipPath id={ids.lowerClip}>
            <path d={LOWER_CLIP} />
          </clipPath>
          <clipPath id={ids.upperClip}>
            <path d={UPPER_CLIP} />
          </clipPath>
          {LOWER.map((slice, i) => (
            <clipPath key={`l${i}`} id={ids.slice("lower", i)}>
              <rect
                x={slice.x - 0.02}
                y="53"
                width={slice.width + 0.04}
                height="10"
              />
            </clipPath>
          ))}
          {UPPER.map((slice, i) => (
            <clipPath key={`u${i}`} id={ids.slice("upper", i)}>
              <rect
                x={slice.x - 0.02}
                y="51"
                width={slice.width + 0.04}
                height="6.5"
              />
            </clipPath>
          ))}
          <filter id={ids.soft} x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="1" />
          </filter>
          <filter id={ids.blur} x="-30%" y="-80%" width="160%" height="260%">
            <feGaussianBlur stdDeviation="0.28" />
          </filter>
          <mask id={ids.lowerMask}>
            <ellipse
              cx={CENTER}
              cy="56.8"
              rx="8.5"
              ry="3.5"
              fill="#fff"
              filter={`url(#${ids.soft})`}
            />
          </mask>
          <mask id={ids.upperMask}>
            <ellipse
              cx={CENTER}
              cy="54.8"
              rx="8.5"
              ry="2.7"
              fill="#fff"
              filter={`url(#${ids.soft})`}
            />
          </mask>
          {/* Darker deep inside, a little warmer toward the lips. */}
          <linearGradient
            id={ids.depth}
            gradientUnits="userSpaceOnUse"
            x1={CENTER}
            y1="54.7"
            x2={CENTER}
            y2="58.2"
          >
            <stop offset="0" stopColor="#180f19" />
            <stop offset="0.5" stopColor="#251724" />
            <stop offset="1" stopColor="#392331" />
          </linearGradient>
          <linearGradient
            id={ids.sides}
            gradientUnits="userSpaceOnUse"
            x1={LEFT}
            y1="0"
            x2={RIGHT}
            y2="0"
          >
            <stop offset="0" stopColor="#140405" stopOpacity="0.85" />
            <stop offset="0.25" stopColor="#140405" stopOpacity="0" />
            <stop offset="0.75" stopColor="#140405" stopOpacity="0" />
            <stop offset="1" stopColor="#140405" stopOpacity="0.85" />
          </linearGradient>
          {/* Enamel: shaded where the lip covers it, soft ivory at the edge. */}
          <linearGradient
            id={ids.enamel}
            gradientUnits="userSpaceOnUse"
            x1={CENTER}
            y1="54.4"
            x2={CENTER}
            y2="56.9"
          >
            <stop offset="0" stopColor="#92929e" />
            <stop offset="0.35" stopColor="#b8bcc5" />
            <stop offset="0.85" stopColor="#d2d5dc" />
            <stop offset="1" stopColor="#b1b3be" />
          </linearGradient>
          <linearGradient
            id={ids.teethSides}
            gradientUnits="userSpaceOnUse"
            x1={CENTER - TEETH_HALF}
            y1="0"
            x2={CENTER + TEETH_HALF}
            y2="0"
          >
            <stop offset="0" stopColor="#3a1214" stopOpacity="0.95" />
            <stop offset="0.25" stopColor="#3a1214" stopOpacity="0.25" />
            <stop offset="0.42" stopColor="#3a1214" stopOpacity="0" />
            <stop offset="0.58" stopColor="#3a1214" stopOpacity="0" />
            <stop offset="0.75" stopColor="#3a1214" stopOpacity="0.25" />
            <stop offset="1" stopColor="#3a1214" stopOpacity="0.95" />
          </linearGradient>
        </defs>

        {/* Inside of the mouth. */}
        <g ref={inside} opacity={first.interior}>
          <path ref={cavity} d={first.cavity} fill={`url(#${ids.depth})`} />
          <g clipPath={`url(#${ids.cavity})`}>
            <ellipse
              ref={tongue}
              cx={CENTER}
              cy={first.tongueY}
              rx="4.4"
              ry={first.tongueRy}
              fill="#6d4a5b"
              opacity="0.45"
              filter={`url(#${ids.blur})`}
            />
            <g ref={teeth} opacity={first.teeth}>
              <path d={TEETH} fill={`url(#${ids.enamel})`} />
              {TOOTH_GAPS.map((gap, i) => (
                <path
                  key={i}
                  d={gap.d}
                  stroke="#9e8e85"
                  strokeWidth="0.09"
                  strokeLinecap="round"
                  opacity={gap.opacity}
                  fill="none"
                />
              ))}
              <path d={TEETH} fill={`url(#${ids.teethSides})`} />
            </g>
            <rect
              x="40"
              y="51"
              width="22"
              height="12"
              fill={`url(#${ids.sides})`}
            />
          </g>
        </g>

        {/* The lips, moved slice by slice. */}
        <g mask={`url(#${ids.lowerMask})`}>
          {LOWER.map((_, i) => (
            <g
              key={i}
              ref={(el) => {
                lower.current[i] = el;
              }}
              transform={`translate(0 ${first.lower[i].toFixed(3)})`}
            >
              {portrait("lower", i)}
            </g>
          ))}
        </g>
        <g mask={`url(#${ids.upperMask})`}>
          {UPPER.map((_, i) => (
            <g
              key={i}
              ref={(el) => {
                upper.current[i] = el;
              }}
              transform={`translate(0 ${first.upper[i].toFixed(3)})`}
            >
              {portrait("upper", i)}
            </g>
          ))}
        </g>
        {/* Where each lip turns inward it darkens a little; this softens the
            line between the lips and the inside of the mouth. */}
        <g
          ref={edges}
          opacity={first.interior}
          fill="none"
          stroke="#5a1c1f"
          strokeLinecap="round"
          filter={`url(#${ids.blur})`}
        >
          <path
            ref={upperEdge}
            d={first.upperEdge}
            strokeWidth="0.25"
            strokeOpacity="0.2"
          />
          <path
            ref={lowerEdge}
            d={first.lowerEdge}
            strokeWidth="0.3"
            strokeOpacity="0.18"
          />
        </g>
      </svg>
    );
  },
);

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
    const stiffness = { open: 40, round: 26 };
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
