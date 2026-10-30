import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import ts from "../frontend/node_modules/typescript/lib/typescript.js";

const source = await readFile(
  new URL("../frontend/src/HanaStage.tsx", import.meta.url),
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
  const hooks = [],
    effects = [],
    timers = [];
  let index = 0;
  const HanaOrb = () => {};
  const react = {
    useState(initial) {
      const i = index++;
      hooks[i] ??= {
        value: typeof initial === "function" ? initial() : initial,
      };
      return [
        hooks[i].value,
        (value) => {
          hooks[i].value = value;
        },
      ];
    },
    useRef(value) {
      const i = index++;
      return (hooks[i] ??= { current: value });
    },
    useEffect(effect, deps) {
      const i = index++,
        old = hooks[i];
      if (!old || deps.some((value, k) => !Object.is(value, old.deps[k]))) {
        effects.push(() => {
          old?.cleanup?.();
          hooks[i] = { deps, cleanup: effect() };
        });
      }
    },
  };
  const module = { exports: {} };
  vm.runInNewContext(compiled, {
    module,
    exports: module.exports,
    Date: class extends Date {
      static now() {
        return 0;
      }
    },
    performance: { now: () => 0 },
    window: {
      matchMedia: () => ({ matches: false }),
      setTimeout(fn, delay) {
        timers.push({ fn, delay });
        return timers.length;
      },
    },
    clearTimeout() {},
    requestAnimationFrame: () => 1,
    cancelAnimationFrame() {},
    require(name) {
      if (name === "react") return react;
      if (name === "react/jsx-runtime")
        return {
          jsx: (type, props) => ({ type, props }),
          jsxs: (type, props) => ({ type, props }),
        };
      if (name === "./HanaOrb") return { HanaOrb };
      if (name === "./hanaSpeech")
        return { PACE: { greeting: 1 }, planSpeech: () => ({ reveal: [] }) };
      if (name.endsWith(".css")) return {};
      throw new Error(name);
    },
  });
  const findOrb = (node) => {
    if (node?.type === HanaOrb) return node;
    const children = node?.props?.children;
    for (const child of Array.isArray(children) ? children : [children]) {
      const found = child && typeof child === "object" && findOrb(child);
      if (found) return found;
    }
  };
  return {
    ...module.exports,
    timers,
    render(props) {
      index = 0;
      const tree = module.exports.HanaStage(props);
      while (effects.length) effects.shift()();
      return { tree, orb: findOrb(tree) };
    },
  };
}

test("thinking and analysis keep their movement while their status text is revealing", () => {
  const env = setup();
  for (const [state, mode] of Object.entries({
    thinking: "thinking",
    searching: "thinking",
    analyzing: "working",
    report: "working",
    writing: "speaking",
    listening: "listening",
    done: "done",
    error: "error",
  })) {
    assert.equal(env.orbModeForStage(state, true), mode);
  }
  assert.equal(env.orbModeForStage("greeting", true), "speaking");
});

test("a new request moves immediately even while the previous bubble is held", () => {
  const env = setup();
  env.render({ state: "greeting" });
  const { orb, tree } = env.render({ state: "thinking" });
  assert.equal(orb.props.mode, "thinking");
  assert.ok(tree.props.className.includes("busy"));
  assert.equal(env.timers.at(-1).delay, 0);
  const analyzing = env.render({ state: "analyzing" });
  assert.equal(analyzing.orb.props.mode, "working");
});

test("activity labels drive thinking, data analysis, search and answer motions", () => {
  const env = setup();
  for (const [activity, mode] of [
    ["Po mendoj…", "thinking"],
    ["Po analizoj të dhënat…", "working"],
    ["Po llogaris…", "working"],
    ["Po kërkoj në internet…", "thinking"],
    ["Po përgatis Excel-in…", "working"],
    ["Po shkruaj…", "speaking"],
  ])
    assert.equal(env.orbModeForStage(env.stageFromActivity(activity)), mode);
});
