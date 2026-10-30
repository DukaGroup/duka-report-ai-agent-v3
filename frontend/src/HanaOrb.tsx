import { useEffect, useRef } from "react";
import "./hana-orb.css";

/**
 * Hana as a living wireframe: spherical while listening, then stretching,
 * folding and growing uneven peaks during thought, work and speech.
 * Large changes of shape unfold slowly rather than vibrating or flickering.
 */
export type OrbMode =
  | "idle"
  | "listening"
  | "thinking"
  | "working"
  | "speaking"
  | "done"
  | "error";

// How lively each mode is: ripple height and speed.
const ENERGY: Record<OrbMode, number> = {
  idle: 0.2,
  listening: 0.35,
  thinking: 0.55,
  working: 0.7,
  speaking: 0.85,
  done: 0.6,
  error: 0.45,
};
const SWIRL: Record<OrbMode, number> = {
  idle: 0.15,
  listening: 0.2,
  thinking: 0.7,
  working: 0.45,
  speaking: 0.3,
  done: 0.3,
  error: 0.1,
};

type Wave = {
  x: number;
  y: number;
  z: number;
  frequency: number;
  speed: number;
  phase: number;
  weight: number;
};
type Spark = {
  angle: number;
  distance: number;
  size: number;
  drift: number;
  phase: number;
};
type Spike = { x: number; y: number; z: number; phase: number };

type Orb = {
  canvas: HTMLCanvasElement;
  mode: OrbMode;
  live: boolean;
  visible: boolean;
  dirty: boolean;
  energy: number;
  swirl: number;
  /** Eased blend from a sphere into the irregular active surface. */
  focus: number;
  warmth: number;
  /** Speaking/done swell, 0..1, eased toward `pulseTarget`. */
  pulse: number;
  pulseTarget: number;
  nextPulse: number;
  clock: number;
  /** Accumulated ripple phase. Kept separate from `clock` so a change of
   * speed never makes the surface jump. */
  flow: number;
  spin: number;
  waves: Wave[];
  spikes: Spike[];
  sparks: Spark[];
};

const hash = (n: number) => {
  const x = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
};

function createWaves(seed: number): Wave[] {
  return Array.from({ length: 7 }, (_, i) => {
    const r = (k: number) => hash(seed * 31 + i * 7 + k);
    // A random direction on the sphere for each ripple.
    const theta = r(1) * Math.PI * 2,
      z = r(2) * 2 - 1,
      ring = Math.sqrt(1 - z * z);
    const broad = i < 4;
    return {
      x: Math.cos(theta) * ring,
      y: Math.sin(theta) * ring,
      z,
      // Four broad, slow swells carry the shape; three gentler mid ripples
      // add life without the busy, noisy wrinkling.
      frequency: broad ? 1.3 + r(3) * 1.1 : 2.6 + r(3) * 1.6,
      speed:
        (broad ? 0.35 + r(4) * 0.35 : 0.55 + r(4) * 0.45) *
        (r(5) < 0.5 ? -1 : 1),
      phase: r(6) * Math.PI * 2,
      weight: broad ? 1 : 0.38,
    };
  });
}
function createSparks(seed: number): Spark[] {
  return Array.from({ length: 110 }, (_, i) => {
    const r = (k: number) => hash(seed * 17 + i * 13 + k);
    return {
      angle: r(1) * Math.PI * 2,
      distance: 0.97 + r(2) ** 2 * 0.3,
      size: 0.35 + r(3) * 0.8,
      drift: (r(4) - 0.5) * 0.16,
      phase: r(5) * Math.PI * 2,
    };
  });
}

function createSpikes(seed: number): Spike[] {
  // Spread the peaks evenly over the sphere. Fixed directions and phases
  // let each peak grow in place rather than flickering or racing around it.
  return Array.from({ length: 14 }, (_, i) => {
    const y = 1 - (2 * (i + 0.5)) / 14;
    const ring = Math.sqrt(1 - y * y);
    const angle = i * Math.PI * (3 - Math.sqrt(5)) + hash(seed) * Math.PI * 2;
    return {
      x: Math.cos(angle) * ring,
      y,
      z: Math.sin(angle) * ring,
      phase: hash(seed + i * 19) * Math.PI * 2,
    };
  });
}

const STOPS = [
  [80, 200, 255],
  [90, 120, 255],
  [150, 90, 255],
  [225, 80, 255],
  [255, 90, 220],
];
// Blue at the top left, violet through the middle, magenta at the bottom
// right; an error warms the whole sphere toward amber.
function surfaceColor(t: number, warmth: number, alpha: number) {
  const x = Math.max(0, Math.min(0.999, t)) * (STOPS.length - 1);
  const i = Math.floor(x),
    f = x - i;
  const c = STOPS[i].map((v, k) => v + (STOPS[i + 1][k] - v) * f);
  const warm = [255, 160, 90];
  const [r, g, b] = c.map((v, k) => Math.round(v + (warm[k] - v) * warmth));
  return `rgba(${r},${g},${b},${alpha.toFixed(3)})`;
}

// Segments are grouped by color and brightness and stroked as one path per
// group: far fewer draw calls, and no bright beads where segments meet.
const SHADES = 14,
  LEVELS = 10;
const buckets: number[][] = Array.from({ length: SHADES * LEVELS }, () => []);
// Projected sphere vertices, reused between frames.
let grid = new Float32Array(0);

function draw(orb: Orb) {
  const { canvas } = orb;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const w = canvas.width,
    c = w / 2;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, w, w);
  const small = w < 90;
  const e = orb.energy;
  const t = orb.clock;
  // A slow breath, plus a soft swell while speaking.
  // Leave space around the silhouette for the tips of the spikes.
  const radius = w * 0.35 * (1 + 0.012 * Math.sin(t * 0.9) + orb.pulse * 0.025);

  // Its own night backdrop, so it glows the same on light and dark pages,
  // with a deep violet glow behind the sphere.
  const backdrop = ctx.createRadialGradient(c, c, radius * 0.2, c, c, c);
  backdrop.addColorStop(
    0,
    `rgb(${46 + e * 14 + orb.focus * 15}, ${20 + orb.focus * 6}, ${104 + e * 20 + orb.focus * 24})`,
  );
  backdrop.addColorStop(0.7, "#160b3a");
  backdrop.addColorStop(1, "#0a0820");
  ctx.fillStyle = backdrop;
  ctx.beginPath();
  ctx.arc(c, c, c, 0, Math.PI * 2);
  ctx.fill();

  // Light spilling from behind the rim: blue top left, magenta bottom right.
  for (const [dx, dy, color] of [
    [-0.45, -0.45, "70, 170, 255"],
    [0.5, 0.55, "255, 70, 220"],
  ] as const) {
    const x = c + dx * radius,
      y = c + dy * radius;
    const light = ctx.createRadialGradient(x, y, 0, x, y, radius * 1.1);
    light.addColorStop(
      0,
      `rgba(${color}, ${0.24 + e * 0.1 + orb.focus * 0.09 + orb.pulse * 0.08})`,
    );
    light.addColorStop(1, `rgba(${color}, 0)`);
    ctx.fillStyle = light;
    ctx.fillRect(0, 0, w, w);
  }

  // Shape intensity is independent of time: active modes deform strongly
  // while all the fields that drive them continue at a slow, steady pace.
  // At zero focus every deformation vanishes, leaving a true sphere.
  const amplitude = orb.focus * (0.12 + orb.pulse * 0.04);
  const spikeHeight = orb.focus * 0.6;
  const surfaceRadius = radius * (1 - orb.focus * 0.16);
  const peaks = orb.spikes.map((spike) => ({
    ...spike,
    height: spikeHeight * (0.55 + 0.45 * Math.sin(t * 1.35 + spike.phase)),
  }));
  const totalWeight = orb.waves.reduce((sum, wave) => sum + wave.weight, 0);
  const cosY = Math.cos(orb.spin),
    sinY = Math.sin(orb.spin);
  const tilt = 0.55 + orb.focus * 0.08 * Math.sin(t * 0.7),
    cosX = Math.cos(tilt),
    sinX = Math.sin(tilt);
  const roll = orb.focus * 0.06 * Math.sin(t * 0.55),
    cosZ = Math.cos(roll),
    sinZ = Math.sin(roll);
  const flow = orb.flow;

  // Sample the sphere once on a latitude/longitude grid; rings and meridians
  // are drawn along its rows and columns.
  const rings = small ? 12 : 30;
  const meridians = small ? 16 : 44;
  const latSteps = rings * 2;
  const lonSteps = meridians * 2;
  const size = (latSteps + 1) * (lonSteps + 1) * 3;
  if (grid.length < size) grid = new Float32Array(size);
  for (let i = 0; i <= latSteps; i++) {
    const lat = (i / latSteps) * Math.PI;
    const y = -Math.cos(lat),
      ring = Math.sin(lat);
    for (let k = 0; k <= lonSteps; k++) {
      const lon = (k / lonSteps) * Math.PI * 2;
      const x = Math.cos(lon) * ring,
        z = Math.sin(lon) * ring;
      let d = 0;
      for (const wave of orb.waves)
        d +=
          Math.sin(
            (x * wave.x + y * wave.y + z * wave.z) * wave.frequency +
              flow * wave.speed +
              wave.phase,
          ) * wave.weight;
      let lift = 0;
      for (const peak of peaks) {
        const alignment = Math.max(0, x * peak.x + y * peak.y + z * peak.z);
        lift += alignment ** 40 * peak.height;
      }
      // Broad overlapping folds break up the whole silhouette; peaks alone
      // would still read as a round ball with spikes attached to it.
      const broad =
        Math.sin(x * 3.2 + y * 1.7 + flow * 0.7) *
        Math.sin(z * 2.8 - y * 2.4 + flow * 0.55 + 1.6);
      const fold =
        Math.sin(y * 5.2 - z * 2.9 + flow * 0.8) *
        Math.cos(x * 3.4 + z * 1.8 - flow * 0.6);
      const r =
        1 +
        (d / totalWeight) * amplitude +
        lift +
        orb.focus * (broad * 0.48 + fold * 0.28);
      // Bend the mesh sideways as well as outwards, giving it uneven arms
      // and deep indentations instead of a fixed, symmetric star shape.
      let px =
        x * r + orb.focus * 0.22 * Math.sin(y * 3.1 + flow * 0.7) * (1 - x * x);
      let py =
        y * r +
        orb.focus * 0.2 * Math.sin(z * 3.4 + flow * 0.55 + 1.2) * (1 - y * y);
      let pz =
        z * r + orb.focus * 0.2 * Math.sin(x * 3 + flow * 0.6) * (1 - z * z);
      const length = Math.hypot(px, py, pz);
      // Smoothly contain the longest tips within the canvas, even as the
      // folds and peaks overlap. The transition has no hard clipped edge.
      if (length > 1.5) {
        const scale = (1.5 + 0.12 * Math.tanh((length - 1.5) / 0.12)) / length;
        px *= scale;
        py *= scale;
        pz *= scale;
      }
      const normalLength = Math.hypot(px, py, pz);
      // Spin around the vertical axis, then tip toward the viewer.
      const x1 = px * cosY + pz * sinY;
      const z1 = -px * sinY + pz * cosY;
      const y2 = py * cosX - z1 * sinX;
      const z2 = py * sinX + z1 * cosX;
      const o = (i * (lonSteps + 1) + k) * 3;
      grid[o] = c + (x1 * cosZ - y2 * sinZ) * surfaceRadius;
      grid[o + 1] = c + (x1 * sinZ + y2 * cosZ) * surfaceRadius;
      grid[o + 2] = z2 / normalLength;
    }
  }

  for (const bucket of buckets) bucket.length = 0;
  const segment = (a: number, b: number, weight: number) => {
    const ax = grid[a],
      ay = grid[a + 1],
      bx = grid[b],
      by = grid[b + 1];
    // Lines on the far side are fainter, which gives the sphere depth; a
    // light rim glow keeps the silhouette crisp.
    const depth = (grid[a + 2] + grid[b + 2]) / 2;
    const front = depth * 0.5 + 0.5;
    const rim = 1 - Math.abs(depth);
    const alpha =
      (0.1 + 0.6 * front * front + 0.18 * rim * rim) *
      (small ? 1.3 : 1) *
      weight;
    if (alpha < 0.02) return;
    const level = Math.min(LEVELS - 1, Math.round(alpha * (LEVELS - 1)));
    const diagonal = ((ax + ay + bx + by) / (4 * w)) * 1.15 - 0.05;
    const shade = Math.max(
      0,
      Math.min(SHADES - 1, Math.round(diagonal * (SHADES - 1))),
    );
    buckets[shade * LEVELS + level].push(ax, ay, bx, by);
  };
  const at = (i: number, k: number) => (i * (lonSteps + 1) + k) * 3;
  const latStride = latSteps / rings,
    lonStride = lonSteps / meridians;
  for (let ring = 1; ring < rings; ring++) {
    const i = ring * latStride;
    // Rings shrink to tight circles at the poles; fade those.
    const fade = Math.min(1, Math.sin((i / latSteps) * Math.PI) ** 1.5 * 2.2);
    for (let k = 0; k < lonSteps; k++) segment(at(i, k), at(i, k + 1), fade);
  }
  for (let m = 0; m < meridians; m++) {
    const k = m * lonStride;
    for (let i = 0; i < latSteps; i++)
      // Meridians crowd together at the poles; thin them out there.
      segment(
        at(i, k),
        at(i + 1, k),
        Math.min(1, Math.sin(((i + 0.5) / latSteps) * Math.PI) ** 1.5 * 2.2),
      );
  }

  ctx.globalCompositeOperation = "lighter";
  ctx.lineWidth = Math.max(0.6, w / 420) * (1 + orb.focus * 0.12);
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  buckets.forEach((bucket, index) => {
    if (!bucket.length) return;
    const shade = Math.floor(index / LEVELS),
      level = index % LEVELS;
    ctx.strokeStyle = surfaceColor(
      shade / (SHADES - 1),
      orb.warmth,
      Math.min(1, (level / (LEVELS - 1)) * (1 + orb.focus * 0.2)),
    );
    ctx.beginPath();
    for (let n = 0; n < bucket.length; n += 4) {
      ctx.moveTo(bucket[n], bucket[n + 1]);
      ctx.lineTo(bucket[n + 2], bucket[n + 3]);
    }
    ctx.stroke();
  });

  // Sparkles drifting around the sphere.
  if (!small)
    for (const spark of orb.sparks) {
      const angle = spark.angle + t * spark.drift + orb.spin * orb.focus * 0.5;
      const distance =
        radius *
        (spark.distance + 0.03 * Math.sin(t * 0.6 + spark.phase) + e * 0.02);
      const x = c + Math.cos(angle) * distance;
      const y = c + Math.sin(angle) * distance;
      const twinkle = 0.3 + 0.7 * (0.5 + 0.5 * Math.sin(t * 1.4 + spark.phase));
      ctx.fillStyle = surfaceColor(
        (x + y) / (2 * w),
        orb.warmth,
        twinkle * (0.4 + e * 0.35 + orb.pulse * 0.2),
      );
      ctx.beginPath();
      ctx.arc(x, y, spark.size * (w / 320), 0, Math.PI * 2);
      ctx.fill();
    }
  ctx.globalCompositeOperation = "source-over";
}

function step(orb: Orb, dt: number) {
  const ease = (rate: number) => 1 - Math.exp(-dt * rate);
  // Gentle easing between modes, so a change of state glides in.
  orb.energy += (ENERGY[orb.mode] - orb.energy) * ease(1.6);
  orb.swirl += (SWIRL[orb.mode] - orb.swirl) * ease(1.2);
  orb.focus += (focusFor(orb.mode) - orb.focus) * ease(1.8);
  orb.warmth += ((orb.mode === "error" ? 0.55 : 0) - orb.warmth) * ease(2.5);
  orb.clock += dt * (0.42 + orb.energy * 0.25);
  orb.flow += dt * (0.14 + orb.energy * 0.13 + orb.swirl * 0.16);
  orb.spin += dt * (0.045 + orb.swirl * 0.11);
  // Keep the cadence calm even when the surface is heavily distorted.
  orb.nextPulse -= dt;
  if (orb.nextPulse <= 0) {
    if (orb.mode === "speaking") {
      orb.pulseTarget = Math.max(orb.pulseTarget, 0.45 + Math.random() * 0.55);
      orb.nextPulse = 0.55 + Math.random() * 0.4;
    } else if (orb.mode === "done") {
      orb.pulseTarget = 0.6;
      orb.nextPulse = 1.8;
    } else orb.nextPulse = 0.3;
  }
  orb.pulseTarget *= Math.exp(-dt * 2.2);
  if (orb.mode === "thinking" || orb.mode === "working")
    orb.pulseTarget = 0.18 + 0.18 * Math.sin(orb.clock * 1.1);
  orb.pulse += (orb.pulseTarget - orb.pulse) * ease(3);
}

function focusFor(mode: OrbMode) {
  return ["thinking", "working", "speaking"].includes(mode) ? 1 : 0;
}

// One animation loop for every orb on the page.
const MOTION_SPEED = 2;
const orbs = new Set<Orb>();
let frame = 0;
let last = 0;
const motionPreference = window.matchMedia?.(
  "(prefers-reduced-motion: reduce)",
);
const reduced = () => motionPreference?.matches;
function loop(now: number) {
  frame = 0;
  const dt = last ? Math.min(0.05, (now - last) / 1000) : 1 / 60;
  last = now;
  let running = false;
  const still = reduced();
  for (const orb of orbs) {
    if (!orb.visible) continue;
    if (orb.live && !still && !document.hidden) {
      step(orb, dt * MOTION_SPEED);
      draw(orb);
      running = true;
    } else if (orb.dirty) {
      // A still frame must reflect its mode even though the spring is paused.
      if (still || !orb.live) {
        orb.energy = ENERGY[orb.mode];
        orb.swirl = SWIRL[orb.mode];
        orb.focus = focusFor(orb.mode);
        orb.warmth = orb.mode === "error" ? 0.55 : 0;
        orb.pulse = orb.pulseTarget = 0;
      }
      draw(orb);
      orb.dirty = false;
    }
  }
  if (running) frame = requestAnimationFrame(loop);
  else last = 0;
}
function wake() {
  if (!frame) frame = requestAnimationFrame(loop);
}
document.addEventListener("visibilitychange", wake);
motionPreference?.addEventListener("change", () => {
  for (const orb of orbs) orb.dirty = true;
  wake();
});

export function HanaOrb({
  mode = "idle",
  live = true,
  className = "",
}: {
  mode?: OrbMode;
  /** Off: a still frame, for orbs that are not the one at work. */
  live?: boolean;
  className?: string;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const orb = useRef<Orb | null>(null);

  useEffect(() => {
    const element = canvas.current;
    if (!element) return;
    const seed = Math.floor(Math.random() * 1000);
    const state: Orb = {
      canvas: element,
      mode,
      live,
      visible: true,
      dirty: true,
      energy: ENERGY[mode],
      swirl: SWIRL[mode],
      focus: focusFor(mode),
      warmth: 0,
      pulse: 0,
      pulseTarget: 0,
      nextPulse: 0,
      clock: Math.random() * 100,
      flow: Math.random() * 100,
      spin: Math.random() * Math.PI * 2,
      waves: createWaves(seed),
      spikes: createSpikes(seed),
      sparks: createSparks(seed),
    };
    orb.current = state;
    orbs.add(state);
    const resize = () => {
      const size = Math.max(
        16,
        Math.round(
          element.getBoundingClientRect().width *
            Math.min(window.devicePixelRatio || 1, 2),
        ),
      );
      if (element.width !== size || element.height !== size) {
        element.width = element.height = size;
        state.dirty = true;
        wake();
      }
    };
    const sizes = new ResizeObserver(resize);
    sizes.observe(element);
    const seen = new IntersectionObserver(([entry]) => {
      state.visible = entry.isIntersecting;
      state.dirty = true;
      wake();
    });
    seen.observe(element);
    resize();
    wake();
    return () => {
      orbs.delete(state);
      sizes.disconnect();
      seen.disconnect();
    };
  }, []);

  useEffect(() => {
    if (!orb.current) return;
    // Let a new activity respond on the next frame, even if the previous
    // mode was waiting for its next pulse.
    if (orb.current.mode !== mode) orb.current.nextPulse = 0;
    orb.current.mode = mode;
    orb.current.live = live;
    orb.current.dirty = true;
    wake();
  }, [mode, live]);

  return (
    <canvas
      ref={canvas}
      className={`hana-orb ${className}`}
      data-mode={mode}
      aria-hidden="true"
    />
  );
}
