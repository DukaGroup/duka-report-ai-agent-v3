import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { Sparkles } from "lucide-react";
import "./hana-intro.css";
import {
  HanaMouth,
  useMouthSpring,
  type MouthHandle,
  type MouthShape,
} from "./HanaMouth";
import {
  mouthAt,
  PACE,
  planSpeech,
  transitionTiming,
  type IntroMode,
} from "./hanaSpeech";
import { HANA_PORTRAIT } from "./hanaAvatar";
import { HanaEyes } from "./HanaEyes";
import { uiZoom } from "./uiScale";

export type { IntroMode };
type Phase =
  | "sky"
  | "moon"
  | "transform"
  | "alive"
  | "setting"
  | "leaving"
  | "docking"
  | "descending"
  | "arriving";

// After greeting, Hana flies into her place on the page below in this time.
const DOCK_HOLD = { presentation: 700, greeting: 250, farewell: 0 };
const DOCK_FLIGHT = 1150;
// Without a greeting she shows herself only briefly before flying off.
const QUIET_HOLD = 600;
// On sign-out the crescent moon drifts up, then sinks into the sign-in page,
// becoming Hana again during the last part of its fall.
const LAND_FLIGHT = 1300;
const LAND_BECOME = 700;
// How long the moon takes to become Hana (see transitionTiming).
const BECOME = transitionTiming("presentation").transformation;

/**
 * Moves the whole scene so it sits exactly on `slot`. The slot is framed like
 * the scene, so one translate and scale is enough. Screen coordinates are real
 * pixels while CSS lengths are zoomed, hence the division by the UI zoom.
 */
function flyTo(scene: HTMLElement, slot: Element, duration: number, arc = 0) {
  const from = scene.getBoundingClientRect();
  const to = slot.getBoundingClientRect();
  if (!from.width || !to.width) return null;
  const zoom = uiZoom();
  const x = (to.left + to.width / 2 - from.left - from.width / 2) / zoom;
  const y = (to.top + to.height / 2 - from.top - from.height / 2) / zoom;
  const scale = to.width / from.width;
  const end = `translate(${x}px, ${y}px) scale(${scale})`;
  const frames: Keyframe[] = arc
    ? [
        { transform: "none" },
        {
          offset: 0.3,
          transform: `translate(${x * 0.15}px, ${-arc}px) scale(${0.75 + scale * 0.25})`,
        },
        { transform: end },
      ]
    : [{ transform: "none" }, { transform: end }];
  return scene.animate(frames, {
    duration,
    easing: arc
      ? "cubic-bezier(0.45, 0, 0.3, 1)"
      : "cubic-bezier(0.65, 0, 0.25, 1)",
    fill: "forwards",
  });
}

const reducedMotion = () =>
  typeof window !== "undefined" &&
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

function timeGreeting() {
  const hour = new Date().getHours();
  return hour < 12 ? "Mirëmëngjes" : hour < 18 ? "Mirëdita" : "Mirëmbrëma";
}

function introLines(name: string, mode: IntroMode) {
  const first = name.trim().split(/\s+/)[0] || "";
  const who = first ? ", " + first : "";
  if (mode === "farewell") return [`Mirupafshim${who}!`];
  if (mode === "greeting") return [`Mirë se u kthyet${who}!`];
  return [
    `${first ? "Përshëndetje" : timeGreeting()}${who}!`,
    "Unë jam Hana, asistentja AI e Duka Group.",
  ];
}

function seeded(count: number, seed: number) {
  let value = seed;
  const next = () => {
    value = (value * 9301 + 49297) % 233280;
    return value / 233280;
  };
  return Array.from({ length: count }, () => [next(), next(), next(), next()]);
}

/**
 * A 0.7-second moonrise, half a second becoming Hana, then a short greeting.
 * With `dock`, Hana then flies into that element on the page below instead of
 * fading away. On farewell, `onLanding` swaps the page below to the sign-in
 * page while she, as the moon, sinks into `dock` and becomes Hana there.
 * A `quiet` intro skips the greeting: she flies off as soon as she appears.
 */
export default function HanaIntro({
  name,
  mode,
  dock,
  quiet = false,
  onLanding,
  onDone,
}: {
  name: string;
  mode: IntroMode;
  dock?: string;
  quiet?: boolean;
  onLanding?: () => void;
  onDone: () => void;
}) {
  const still = useMemo(reducedMotion, []);
  const farewell = mode === "farewell";
  const greeting = mode !== "presentation";
  const lines = useMemo(() => introLines(name, mode), [name, mode]);
  const [phase, setPhase] = useState<Phase>(
    still || farewell ? "alive" : "sky",
  );
  const [talking, setTalking] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const head = useRef<HTMLDivElement>(null);
  const gesture = useRef<HTMLDivElement>(null);
  const inhale = useRef<HTMLDivElement>(null);
  const mouth = useRef<MouthHandle>(null);
  const mouthTarget = useRef<MouthShape>({ open: 0, round: 0 });
  const scene = useRef<HTMLDivElement>(null);
  const done = useRef(onDone);
  done.current = onDone;
  const landing = useRef(onLanding);
  landing.current = onLanding;
  const stars = useMemo(() => seeded(90, 7), []);
  const sparks = useMemo(() => seeded(28, 31), []);
  const finished = phase === "setting" || phase === "leaving";
  // Her first blink comes shortly after she starts to speak.
  const firstBlink = transitionTiming(mode, still).speechStart + 700;

  useMouthSpring(
    mouth,
    mouthTarget,
    (level) => root.current?.style.setProperty("--mouth", level.toFixed(3)),
    !still,
  );

  useEffect(() => {
    let completed = false;
    let frame = 0;
    const timers: number[] = [];
    const timing = transitionTiming(mode, still);
    const docked = Boolean(dock) && !still;
    const departure = quiet
      ? timing.speechStart + QUIET_HOLD
      : timing.speechEnd + DOCK_HOLD[mode];
    const total = !docked
      ? timing.total
      : farewell
        ? timing.speechEnd +
          600 +
          Math.max(LAND_FLIGHT, LAND_BECOME + BECOME) +
          80
        : departure + DOCK_FLIGHT + 30;
    const finish = () => {
      if (completed) return;
      completed = true;
      cancelAnimationFrame(frame);
      mouthTarget.current = { open: 0, round: 0 };
      done.current();
    };
    // This deadline is independent of speech length, frame rate and renders.
    timers.push(window.setTimeout(finish, total));
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") finish();
    };
    window.addEventListener("keydown", key);
    if (!still) {
      if (!farewell) {
        for (const [time, next] of [
          [0, "moon"],
          [timing.rise, "transform"],
          [timing.speechStart, "alive"],
        ] as const)
          timers.push(window.setTimeout(() => setPhase(next), time));
      }
      if (!docked)
        timers.push(
          window.setTimeout(
            () => setPhase(farewell ? "setting" : "leaving"),
            timing.speechEnd,
          ),
        );
      else if (!farewell)
        timers.push(
          window.setTimeout(() => {
            const slot = document.querySelector(dock!);
            if (!scene.current || !slot) return setPhase("leaving");
            setPhase("docking");
            flyTo(scene.current, slot, DOCK_FLIGHT);
          }, departure),
        );
      else {
        timers.push(
          window.setTimeout(() => setPhase("setting"), timing.speechEnd),
          window.setTimeout(() => {
            // The sign-in page renders below; measure it on the next frames.
            landing.current?.();
            setPhase("descending");
            frame = requestAnimationFrame(() => {
              frame = requestAnimationFrame(() => {
                const slot = document.querySelector(dock!);
                if (!scene.current || !slot) return finish();
                flyTo(
                  scene.current,
                  slot,
                  LAND_FLIGHT,
                  (window.innerHeight * 0.12) / uiZoom(),
                );
                timers.push(
                  window.setTimeout(() => setPhase("arriving"), LAND_BECOME),
                );
              });
            });
          }, timing.speechEnd + 600),
        );
      }
    }
    if (!still && !quiet) {
      const plan = planSpeech(lines[0], PACE[mode]);
      const start = performance.now();
      const speechStart = timing.speechStart + 80;
      // Her natural pace; only a long name is hurried a little to fit.
      const speechLength = Math.min(plan.total, 1600);
      const tick = (now: number) => {
        const elapsed = now - start - speechStart;
        const active = elapsed >= 0 && elapsed < speechLength;
        setTalking(active);
        mouthTarget.current = active
          ? mouthAt(plan, (elapsed * plan.total) / speechLength)
          : { open: 0, round: 0 };
        if (!completed && now - start < timing.speechEnd)
          frame = requestAnimationFrame(tick);
      };
      frame = requestAnimationFrame(tick);
      head.current?.animate(
        [
          { transform: "none" },
          {
            transform: farewell
              ? "translateY(0.6%) rotate(0.4deg)"
              : "translateY(0.4%) rotate(-0.35deg)",
          },
          { transform: "none" },
        ],
        { duration: 1150, delay: timing.speechStart, easing: "ease-in-out" },
      );
    }
    return () => {
      completed = true;
      timers.forEach(clearTimeout);
      cancelAnimationFrame(frame);
      window.removeEventListener("keydown", key);
      mouthTarget.current = { open: 0, round: 0 };
    };
  }, [mode, still, lines, farewell, dock, quiet]);

  return (
    <div
      ref={root}
      className={`hana-intro mode-${mode} phase-${phase}${still ? " still" : ""}${talking ? " is-talking" : ""}${finished ? " is-done" : ""}${dock ? " is-docking" : ""}${quiet ? " is-quiet" : ""}`}
      role="dialog"
      aria-modal="true"
      aria-label={
        farewell
          ? "Hana ju përshëndet"
          : greeting
            ? "Përshëndetja e Hanës"
            : "Prezantimi i Hanës"
      }
    >
      <div className="intro-sky" aria-hidden="true">
        {stars.map(([x, y, size, delay], index) => (
          <span
            key={index}
            className="intro-star"
            style={
              {
                left: `${x * 100}%`,
                top: `${y * 100}%`,
                "--size": `${1 + size * 2.4}px`,
                "--delay": `${delay * 4}s`,
              } as CSSProperties
            }
          />
        ))}
        <span className="intro-shooting-star" />
        <span className="intro-shooting-star late" />
      </div>

      <div className="intro-stage">
        <div ref={scene} className="intro-scene" aria-hidden="true">
          <div className="intro-moon">
            <div className="moon-disc">
              <span className="moon-crater a" />
              <span className="moon-crater b" />
              <span className="moon-crater c" />
              <span className="moon-crater d" />
              <span className="moon-shadow" />
            </div>
          </div>
          <div className="intro-flash" />
          <div className="intro-burst">
            {sparks.map(([angle, distance, size, delay], index) => (
              <span
                key={index}
                style={
                  {
                    "--angle": `${angle * 360}deg`,
                    "--distance": `${110 + distance * 170}px`,
                    "--size": `${3 + size * 6}px`,
                    "--delay": `${delay * 0.35}s`,
                  } as CSSProperties
                }
              />
            ))}
          </div>
          <div className="intro-hana">
            <div className="hana-halo" />
            <div className="hana-look">
              <div className="hana-sway">
                <div ref={head} className="hana-nod">
                  <div ref={gesture} className="hana-gesture">
                    <div ref={inhale} className="hana-inhale">
                      <div className="hana-breathe">
                        <div
                          className={`hana-portrait${talking ? " talking" : ""}`}
                        >
                          <div className="hana-face-source">
                            <img src={HANA_PORTRAIT} alt="" draggable={false} />
                            <HanaMouth ref={mouth} />
                            <HanaEyes firstBlink={firstBlink} />
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <div className="hana-floaters">
              {sparks.slice(0, 10).map(([x, y, , delay], index) => (
                <span
                  key={index}
                  style={
                    {
                      left: `${8 + x * 84}%`,
                      top: `${10 + y * 70}%`,
                      "--delay": `${delay * 5}s`,
                    } as CSSProperties
                  }
                />
              ))}
            </div>
          </div>
        </div>

        {!quiet && (
          <section className="intro-speech" aria-live="polite">
            <span className="intro-speech-name">
              <Sparkles size={14} /> Hana
              <span className="intro-voice" aria-hidden="true">
                <i />
                <i />
                <i />
                <i />
              </span>
            </span>
            <div className="intro-lines">
              {lines.map((text, index) => (
                <p key={index} className={index === 0 ? "greeting" : "said"}>
                  {text}
                  {index === 0 && !farewell && (
                    <span className="intro-wave">👋</span>
                  )}
                </p>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
