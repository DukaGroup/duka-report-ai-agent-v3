import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { ArrowRight, Sparkles } from "lucide-react";
import "./hana-intro.css";
import {
  HanaMouth,
  useMouthSpring,
  type MouthHandle,
  type MouthShape,
} from "./HanaMouth";
import { mouthAt, PACE, planSpeech, type IntroMode } from "./hanaSpeech";

export type { IntroMode };
type Phase = "sky" | "moon" | "transform" | "alive" | "setting" | "leaving";

// When each phase starts (ms). The everyday greeting is a shorter version.
const TIMELINE: Record<
  Exclude<IntroMode, "farewell">,
  [number, number, number]
> = {
  presentation: [200, 1500, 2600],
  greeting: [80, 800, 1500],
};

const reducedMotion = () =>
  typeof window !== "undefined" &&
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

function timeGreeting() {
  const hour = new Date().getHours();
  return hour < 12 ? "Mirëmëngjes" : hour < 18 ? "Mirëdita" : "Mirëmbrëma";
}

function introLines(name: string, mode: IntroMode) {
  const first = name.trim().split(/\s+/)[0] || "";
  if (mode === "farewell")
    return [
      `Mirupafshim${first ? ", " + first : ""}!`,
      "Faleminderit që punuat me mua sot.",
      "Ju pres sërish së shpejti. Kujdesuni!",
    ];
  if (mode === "greeting")
    return [
      `${timeGreeting()}${first ? ", " + first : ""}!`,
      "Mirë se u kthyet. Po ju hap hapësirën…",
    ];
  return [
    `Përshëndetje${first ? ", " + first : ""}!`,
    "Unë jam Hana, asistentja juaj në Duka Group.",
    "Më pyesni për shitjet, klientët, bilancet ose çdo shifër të biznesit. Unë i gjej dhe jua shpjegoj qartë.",
    "Kur ju duhet një raport, e përgatis në Excel brenda pak minutash.",
    "Shoh vetëm të dhënat ku keni qasje, ndaj gjithçka mbetet e sigurt.",
    "Gati? Le të fillojmë bashkë!",
  ];
}

// Deterministic pseudo-random values keep the sky identical between renders.
function seeded(count: number, seed: number) {
  let value = seed;
  const next = () => {
    value = (value * 9301 + 49297) % 233280;
    return value / 233280;
  };
  return Array.from({ length: count }, () => [next(), next(), next(), next()]);
}

/**
 * Hana after login: a full self-introduction the first time, and a short
 * greeting that continues to the workspace by itself on later logins.
 */
export default function HanaIntro({
  name,
  mode,
  onDone,
}: {
  name: string;
  mode: IntroMode;
  onDone: () => void;
}) {
  const still = useMemo(reducedMotion, []);
  const farewell = mode === "farewell";
  // Greeting and farewell are short and continue by themselves.
  const greeting = mode !== "presentation";
  const lines = useMemo(() => introLines(name, mode), [name, mode]);
  const speech = useMemo(
    () => lines.map((text) => planSpeech(text, PACE[mode])),
    [lines, mode],
  );
  const [phase, setPhase] = useState<Phase>(
    still || farewell ? "alive" : "sky",
  );
  const [line, setLine] = useState(still ? lines.length - 1 : 0);
  const [chars, setChars] = useState(still ? lines.at(-1)!.length : 0);
  const [blink, setBlink] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const continueButton = useRef<HTMLButtonElement>(null);
  const head = useRef<HTMLDivElement>(null);
  const gesture = useRef<HTMLDivElement>(null);
  const inhale = useRef<HTMLDivElement>(null);
  const mouth = useRef<MouthHandle>(null);
  const mouthTarget = useRef<MouthShape>({ open: 0, round: 0 });
  const leaving = useRef(false);
  const stars = useMemo(() => seeded(90, 7), []);
  const sparks = useMemo(() => seeded(28, 31), []);
  const finished = line === lines.length - 1 && chars >= lines[line].length;
  const talking = phase === "alive" && !finished && chars < lines[line].length;

  // Moon rises, changes phase, then turns into Hana.
  useEffect(() => {
    if (still || mode === "farewell") return;
    const [moon, transform, alive] = TIMELINE[mode];
    const timers = [
      window.setTimeout(() => setPhase("moon"), moon),
      window.setTimeout(() => setPhase("transform"), transform),
      window.setTimeout(() => setPhase("alive"), alive),
    ];
    return () => timers.forEach(clearTimeout);
  }, [still, mode]);

  // A soft spring follows the planned mouth shape every frame, so the jaw
  // has a little weight and never snaps, like hand-drawn animation.
  useMouthSpring(
    mouth,
    mouthTarget,
    (level) => root.current?.style.setProperty("--mouth", level.toFixed(3)),
    !still,
  );

  // Small head movements on stressed words, the way people talk with their head.
  function emphasise(strong: boolean) {
    const tilt = (Math.random() < 0.5 ? -1 : 1) * (strong ? 1.4 : 0.6);
    const lift = strong ? -0.7 : -0.3;
    gesture.current?.animate(
      [
        { transform: "none" },
        { transform: `translateY(${lift}%) rotate(${tilt}deg)` },
        { transform: `translateY(${lift / 3}%) rotate(${tilt / 3}deg)` },
        { transform: "none" },
      ],
      { duration: strong ? 900 : 520, easing: "ease-in-out" },
    );
  }

  // Speak the current sentence: letters appear and the mouth moves in time.
  useEffect(() => {
    if (phase !== "alive" || still) return;
    const plan = speech[line];
    const begin = performance.now();
    let frame = 0;
    let shown = 0;
    let syllable = 0;
    let emphasis = 0;
    const tick = (now: number) => {
      const time = now - begin;
      let count = shown;
      while (count < plan.reveal.length && plan.reveal[count] <= time) count++;
      if (count !== shown) {
        shown = count;
        setChars(count);
      }
      mouthTarget.current = mouthAt(plan, time);
      // A light nod on some stressed syllables, a clearer one on "!" and "?".
      while (
        syllable < plan.syllables.length &&
        plan.syllables[syllable].start <= time
      ) {
        if (plan.syllables[syllable].stressed && Math.random() < 0.18)
          emphasise(false);
        syllable++;
      }
      while (emphasis < plan.emphasis.length && plan.emphasis[emphasis] <= time) {
        emphasise(true);
        emphasis++;
      }
      if (time >= plan.total) {
        mouthTarget.current = { open: 0, round: 0 };
        setChars(lines[line].length);
        return;
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      mouthTarget.current = { open: 0, round: 0 };
    };
  }, [phase, line, still, speech, lines]);

  // Between sentences: a breath, a blink and a small nod, then the next one.
  const sentenceDone = chars >= lines[line].length;
  useEffect(() => {
    if (phase !== "alive" || still || !sentenceDone) return;
    if (line >= lines.length - 1) return;
    const gap = mode === "presentation" ? 550 : mode === "farewell" ? 450 : 350;
    const breath = window.setTimeout(
      () =>
        inhale.current?.animate(
          [
            { transform: "none" },
            { transform: "translateY(-0.5%) scale(1.006, 1.012)" },
            { transform: "none" },
          ],
          { duration: gap, easing: "ease-in-out" },
        ),
      gap * 0.15,
    );
    const timer = window.setTimeout(() => {
      setLine((n) => n + 1);
      setChars(0);
      // People often blink when they start a new thought.
      if (Math.random() < 0.6) {
        setBlink(true);
        window.setTimeout(() => setBlink(false), 160);
      }
      const tilt = Math.random() < 0.5 ? -1 : 1;
      head.current?.animate(
        [
          { transform: "rotate(0deg) translateY(0)" },
          { transform: `rotate(${tilt * 1.4}deg) translateY(0.5%)` },
          { transform: `rotate(${tilt * -0.4}deg) translateY(-0.2%)` },
          { transform: "rotate(0deg) translateY(0)" },
        ],
        { duration: 1200, easing: "ease-in-out" },
      );
    }, gap);
    return () => {
      clearTimeout(timer);
      clearTimeout(breath);
    };
  }, [phase, still, sentenceDone, line, lines, mode]);

  // Blink at irregular intervals, sometimes twice, like a real person.
  useEffect(() => {
    if (phase !== "alive" || still) return;
    let timer = 0;
    const schedule = () => {
      timer = window.setTimeout(
        () => {
          setBlink(true);
          window.setTimeout(() => setBlink(false), 170);
          if (Math.random() < 0.25) {
            window.setTimeout(() => setBlink(true), 330);
            window.setTimeout(() => setBlink(false), 500);
          }
          schedule();
        },
        2200 + Math.random() * 3200,
      );
    };
    schedule();
    return () => clearTimeout(timer);
  }, [phase, still]);

  // Hana turns slightly toward the pointer.
  useEffect(() => {
    if (still) return;
    const move = (event: PointerEvent) => {
      const x = event.clientX / window.innerWidth - 0.5;
      const y = event.clientY / window.innerHeight - 0.5;
      root.current?.style.setProperty("--look-x", x.toFixed(3));
      root.current?.style.setProperty("--look-y", y.toFixed(3));
    };
    window.addEventListener("pointermove", move);
    return () => window.removeEventListener("pointermove", move);
  }, [still]);

  useEffect(() => {
    if (!finished) return;
    // A slow, warm nod once she has finished speaking.
    if (!still)
      head.current?.animate(
        [
          { transform: "none" },
          { transform: "rotate(-1.2deg) translateY(0.9%)" },
          { transform: "rotate(-0.4deg) translateY(0.2%)" },
          { transform: "none" },
        ],
        { duration: 1300, easing: "ease-in-out", delay: 150 },
      );
    if (!greeting) return continueButton.current?.focus();
    // The greeting moves on to the workspace by itself.
    if (farewell && !still) {
      // Hana turns back into the moon, which sets below the horizon.
      // She finishes the goodbye, waits a moment, then sets like the moon.
      const timers = [
        window.setTimeout(() => setPhase("setting"), 900),
        window.setTimeout(() => {
          leaving.current = true;
          onDone();
        }, 2600),
      ];
      return () => timers.forEach(clearTimeout);
    }
    const timer = window.setTimeout(leave, 1100);
    return () => clearTimeout(timer);
  }, [finished]);

  function leave() {
    if (leaving.current) return;
    leaving.current = true;
    if (still) return onDone();
    setPhase("leaving");
    window.setTimeout(onDone, 600);
  }

  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") leave();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });

  return (
    <div
      ref={root}
      className={`hana-intro mode-${mode} phase-${phase}${still ? " still" : ""}${talking ? " is-talking" : ""}${finished ? " is-done" : ""}`}
      role="dialog"
      aria-modal="true"
      // The greeting can be skipped with a click; the goodbye always finishes.
      onClick={mode === "greeting" ? leave : undefined}
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

      <button type="button" className="intro-skip" onClick={leave}>
        {farewell ? "Dil" : greeting ? "Vazhdo" : "Kalo prezantimin"}
      </button>

      <div className="intro-stage">
        <div className="intro-scene" aria-hidden="true">
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
                      className={`hana-portrait${blink ? " blink" : ""}${talking ? " talking" : ""}`}
                    >
                      <img
                        src="/brand/hana-avatar.png"
                        alt=""
                        draggable={false}
                      />
                      <HanaMouth ref={mouth} />
                      <span className="hana-lid left" />
                      <span className="hana-lid right" />
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
            {lines.map((text, index) =>
              index < line && index >= line - 3 ? (
                <p key={index} className={`said${index ? "" : " greeting"}`}>
                  {text}
                  {index === 0 && <span className="intro-wave">👋</span>}
                </p>
              ) : null,
            )}
            <p className={`saying${line ? "" : " greeting"}`}>
              {lines[line].slice(0, Math.max(0, chars - 1))}
              {chars > 0 && (
                <span key={chars} className="intro-fresh">
                  {lines[line][chars - 1]}
                </span>
              )}
              {line === 0 && chars >= lines[0].length && (
                <span className="intro-wave">👋</span>
              )}
              {!finished && <span className="intro-caret" />}
            </p>
          </div>
          {!greeting && (
            <button
              ref={continueButton}
              type="button"
              className={`button primary intro-continue${finished ? " ready" : ""}`}
              onClick={leave}
              tabIndex={finished ? 0 : -1}
            >
              Fillojmë <ArrowRight size={17} />
            </button>
          )}
        </section>
      </div>
    </div>
  );
}
