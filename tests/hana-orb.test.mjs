import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import ts from "../frontend/node_modules/typescript/lib/typescript.js";
const source = await readFile(
  new URL("../frontend/src/HanaOrb.tsx", import.meta.url),
  "utf8",
);
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.CommonJS,
    jsx: ts.JsxEmit.ReactJSX,
  },
}).outputText;
function setup() {
  let active,
    id = 0;
  const pending = new Map(),
    listeners = new Map(),
    observers = [];
  const media = {
    matches: false,
    addEventListener(type, fn) {
      listeners.set("motion:" + type, fn);
    },
    removeEventListener() {},
  };
  const context = {
    setTransform() {},
    clearRect() {
      this.clears++;
      this.points.length = 0;
    },
    clears: 0,
    styles: [],
    points: [],
    createRadialGradient() {
      return { addColorStop() {} };
    },
    beginPath() {},
    arc() {},
    fill() {},
    fillRect() {},
    moveTo(x, y) {
      this.points.push(x, y);
    },
    lineTo() {},
    stroke() {
      this.styles.push(this.strokeStyle);
    },
  };
  const canvas = () => ({
    width: 0,
    height: 0,
    getBoundingClientRect: () => ({ width: 40 }),
    context: { ...context, styles: [], points: [] },
    getContext() {
      return this.context;
    },
  });
  const effects = [];
  const react = {
    useRef(value) {
      const i = active.index++;
      return active.hooks[i] ?? (active.hooks[i] = { current: value });
    },
    useEffect(effect, deps) {
      const i = active.index++,
        old = active.hooks[i];
      if (!old || deps.some((dep, k) => !Object.is(dep, old.deps[k])))
        effects.push(() => {
          old?.cleanup?.();
          active.hooks[i] = { deps, cleanup: effect() };
        });
    },
  };
  const module = { exports: {} };
  const document = {
    hidden: false,
    addEventListener(type, fn) {
      listeners.set(type, fn);
    },
  };
  const sandbox = {
    module,
    exports: module.exports,
    document,
    window: { matchMedia: () => media, devicePixelRatio: 1 },
    Math: Object.assign(Object.create(Math), { random: () => 0.5 }),
    Float32Array,
    requestAnimationFrame(fn) {
      const next = ++id;
      pending.set(next, fn);
      return next;
    },
    cancelAnimationFrame(i) {
      pending.delete(i);
    },
    ResizeObserver: class {
      observe() {}
      disconnect() {}
    },
    IntersectionObserver: class {
      constructor(fn) {
        this.fn = fn;
        observers.push(this);
      }
      observe() {}
      disconnect() {
        this.disconnected = true;
      }
    },
    require(name) {
      if (name === "react") return react;
      if (name === "react/jsx-runtime")
        return { jsx: (type, props) => ({ type, props }) };
      if (name.endsWith(".css")) return {};
      throw new Error(name);
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(compiled, sandbox);
  function render(instance, props) {
    active = instance;
    instance.index = 0;
    const node = module.exports.HanaOrb(props);
    node.props.ref.current = instance.canvas;
    while (effects.length) effects.shift()();
    active = null;
  }
  return {
    media,
    document,
    pending,
    observers,
    surface() {
      return Array.from(vm.runInContext("grid", sandbox));
    },
    mount(props = {}) {
      const instance = { hooks: [], canvas: canvas(), index: 0 };
      render(instance, props);
      return instance;
    },
    update(instance, props) {
      render(instance, props);
    },
    flush(time = 16) {
      const work = [...pending.values()];
      pending.clear();
      work.forEach((fn) => fn(time));
    },
    motion(value) {
      media.matches = value;
      listeners.get("motion:change")?.({ matches: value });
    },
    visibility(value) {
      document.hidden = value;
      listeners.get("visibilitychange")?.();
    },
    unmount(instance) {
      instance.hooks.forEach((h) => h?.cleanup?.());
    },
  };
}
test("all animated orbs share one loop; completed reply icons render once", () => {
  const env = setup();
  const live = env.mount({ mode: "thinking" }),
    still = env.mount({ mode: "working", live: false });
  assert.equal(env.pending.size, 1);
  env.flush();
  const draws = still.canvas.context.clears;
  assert.ok(draws > 0);
  env.flush(33);
  assert.equal(still.canvas.context.clears, draws);
  assert.ok(live.canvas.context.clears > draws);
  env.unmount(live);
  env.unmount(still);
  env.flush(50);
  assert.equal(env.pending.size, 0);
});

function silhouetteSpread(points, width = 40) {
  const radii = [];
  for (let i = 0; i < points.length; i += 3) {
    if (Math.abs(points[i + 2]) < 0.12)
      radii.push(Math.hypot(points[i] - width / 2, points[i + 1] - width / 2));
  }
  return Math.max(...radii) / Math.min(...radii);
}

test("listening is spherical while thought, reports and speech deform the whole outline", () => {
  for (const mode of ["listening", "thinking", "working", "speaking"]) {
    const env = setup();
    env.mount({ mode });
    env.flush();
    const points = env.surface();
    const spread = silhouetteSpread(points);
    if (mode === "listening") assert.ok(spread < 1.02, `sphere: ${spread}`);
    else assert.ok(spread > 1.5, `${mode} outline: ${spread}`);
    for (let i = 0; i < points.length; i += 3) {
      assert.ok(Number.isFinite(points[i + 2]));
      assert.ok(
        Math.hypot(points[i] - 20, points[i + 1] - 20) < 20,
        "tips fit inside canvas",
      );
    }
  }
});

test("an irregular surface changes smoothly and settles back into a sphere when listening", () => {
  const env = setup();
  const orb = env.mount({ mode: "working" });
  env.flush();
  let previous = env.surface();
  const start = previous;
  let totalChange = 0;
  for (let frame = 2; frame <= 180; frame++) {
    if (frame === 60) env.update(orb, { mode: "listening" });
    env.flush(frame * (1000 / 60));
    const points = env.surface();
    let largestStep = 0;
    for (let i = 0; i < points.length; i += 3) {
      largestStep = Math.max(
        largestStep,
        Math.hypot(points[i] - previous[i], points[i + 1] - previous[i + 1]),
      );
    }
    assert.ok(largestStep < 40 * 0.015, `frame moves gently: ${largestStep}`);
    totalChange += largestStep;
    previous = points;
  }
  assert.ok(totalChange > 1, "surface actually morphs");
  assert.ok(silhouetteSpread(previous) < silhouetteSpread(start) * 0.8);
  // Allow the eased return to finish.
  for (let frame = 181; frame <= 360; frame++) env.flush(frame * (1000 / 60));
  assert.ok(silhouetteSpread(env.surface()) < 1.03);
});
test("changing reduced motion pauses and resumes an already mounted orb", () => {
  const env = setup();
  env.mount({ mode: "speaking" });
  env.flush();
  env.motion(true);
  env.flush(33);
  assert.equal(env.pending.size, 0);
  env.motion(false);
  assert.equal(env.pending.size, 1);
  env.flush(50);
  assert.equal(env.pending.size, 1);
});
test("a still or reduced-motion orb still shows the error color", () => {
  for (const reduced of [false, true]) {
    const env = setup();
    env.media.matches = reduced;
    const orb = env.mount({ mode: "idle", live: reduced });
    env.flush();
    const idle = [...orb.canvas.context.styles];
    orb.canvas.context.styles.length = 0;
    env.update(orb, { mode: "error", live: reduced });
    env.flush(33);
    assert.notDeepEqual(orb.canvas.context.styles, idle);
    assert.equal(env.pending.size, 0);
  }
});
test("hidden and offscreen orbs stop scheduling frames and resume when visible", () => {
  const env = setup();
  const orb = env.mount({ mode: "working" });
  env.flush();
  env.visibility(true);
  env.flush(33);
  assert.equal(env.pending.size, 0);
  env.visibility(false);
  env.flush(50);
  assert.equal(env.pending.size, 1);
  env.observers[0].fn([{ isIntersecting: false }]);
  env.flush(66);
  assert.equal(env.pending.size, 0);
  env.observers[0].fn([{ isIntersecting: true }]);
  env.flush(83);
  assert.equal(env.pending.size, 1);
  env.unmount(orb);
  env.flush(100);
  assert.equal(env.pending.size, 0);
  assert.equal(env.observers[0].disconnected, true);
});

test("thinking and analysis produce distinct, stronger surface movement than idle", () => {
  const movement = (mode) => {
    const env = setup();
    const orb = env.mount({ mode });
    const points = [];
    // Compare the rendered surface movement over two seconds.
    for (let i = 1; i <= 120; i++) {
      env.flush(i * (1000 / 60));
      points.push(orb.canvas.context.points.slice(0, 2));
    }
    const distance = points
      .slice(1)
      .reduce(
        (sum, [x, y], i) =>
          sum + Math.hypot(x - points[i][0], y - points[i][1]),
        0,
      );
    return { points, distance };
  };
  const idle = movement("idle"),
    thinking = movement("thinking"),
    working = movement("working");
  assert.ok(thinking.distance > idle.distance * 1.5);
  assert.ok(working.distance > idle.distance * 1.5);
  assert.notDeepEqual(thinking.points, working.points);
});
