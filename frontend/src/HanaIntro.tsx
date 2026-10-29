import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { ArrowRight, Sparkles } from "lucide-react";
import "./hana-intro.css";

type Phase = "sky" | "moon" | "transform" | "alive" | "setting" | "leaving";
export type IntroMode = "presentation" | "greeting" | "farewell";

// When each phase starts (ms). The everyday greeting is a shorter version.
const TIMELINE: Record<
  Exclude<IntroMode, "farewell">,
  [number, number, number]
> = {
  presentation: [350, 3100, 4600],
  greeting: [150, 1400, 2500],
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

/*
 * Speech planning. Each sentence is split into syllables, and every syllable
 * gets a smooth open-and-close curve: the vowel sets how wide the mouth opens,
 * m/b/p close the lips, and the last syllable before a pause is drawn out, the
 * way people slow down at the end of a phrase. Letters appear in time with it.
 */
const VOWEL_OPEN: Record<string, number> = {
  a: 1, o: 0.82, e: 0.68, u: 0.52, y: 0.42, i: 0.4, ë: 0.34,
};
const isVowel = (c: string) => c.toLowerCase() in VOWEL_OPEN;
const isLetter = (c: string) => /[a-zçë]/i.test(c);
const closesLips = (c: string | undefined) => !!c && /[mbp]/i.test(c);

type Pace = { syllable: number; word: number; comma: number; stop: number };
const PACE: Record<IntroMode, Pace> = {
  presentation: { syllable: 225, word: 45, comma: 420, stop: 720 },
  greeting: { syllable: 205, word: 40, comma: 360, stop: 600 },
  farewell: { syllable: 230, word: 45, comma: 420, stop: 700 },
};

type Syllable = {
  start: number;
  end: number;
  open: number;
  closedStart: boolean;
  closedEnd: boolean;
  stressed: boolean;
};
type Speech = {
  syllables: Syllable[];
  // When each character of the sentence appears (ms from its start).
  reveal: number[];
  // Moments for a stronger head movement ("!" and "?").
  emphasis: number[];
  total: number;
};

// Splits a word into syllables: one consonant between vowels starts the next
// syllable; with two or more, the first stays with the previous one.
function syllables(word: string): [number, number][] {
  const groups: [number, number][] = [];
  for (let i = 0; i < word.length; ) {
    if (isVowel(word[i])) {
      let j = i;
      while (j < word.length && isVowel(word[j])) j++;
      groups.push([i, j]);
      i = j;
    } else i++;
  }
  if (groups.length <= 1) return [[0, word.length]];
  const parts: [number, number][] = [];
  let begin = 0;
  for (let g = 0; g < groups.length - 1; g++) {
    const gap = groups[g + 1][0] - groups[g][1];
    const cut = groups[g][1] + (gap >= 2 ? 1 : 0);
    parts.push([begin, cut]);
    begin = cut;
  }
  parts.push([begin, word.length]);
  return parts;
}

function planSpeech(text: string, pace: Pace): Speech {
  const reveal = new Array<number>(text.length).fill(0);
  const result: Syllable[] = [];
  const emphasis: number[] = [];
  let time = 0;
  let i = 0;
  while (i < text.length) {
    const c = text[i];
    if (isLetter(c)) {
      let j = i;
      while (j < text.length && (isLetter(text[j]) || text[j] === "-")) j++;
      const word = text.slice(i, j);
      const parts = syllables(word);
      const next = text.slice(j).trimStart()[0] || "";
      const phraseEnd = /[,.!?…:;]/.test(next) || j >= text.length;
      parts.forEach(([a, b], index) => {
        const piece = word.slice(a, b);
        const vowel = [...piece].find(isVowel)?.toLowerCase();
        const last = index === parts.length - 1;
        // A final "ë" is barely spoken in Albanian.
        const weak = last && parts.length > 1 && /ë$/i.test(piece) && piece.length <= 2;
        // Stress usually falls on the second-to-last syllable.
        const stressed =
          parts.length === 1 ? piece.length > 3 : index === parts.length - 2;
        let duration =
          pace.syllable *
          (0.78 + Math.min(piece.length, 5) * 0.08) *
          (0.92 + Math.random() * 0.16);
        if (stressed) duration *= 1.12;
        if (weak) duration *= 0.6;
        if (last && phraseEnd) duration *= 1.3;
        let open = vowel ? VOWEL_OPEN[vowel] : 0.3;
        if (stressed) open = Math.min(1, open * 1.1);
        if (weak) open *= 0.45;
        open *= 0.85 + Math.random() * 0.15;
        const nextPiece = parts[index + 1]
          ? word.slice(parts[index + 1][0], parts[index + 1][1])
          : "";
        result.push({
          start: time,
          end: time + duration,
          open,
          closedStart: closesLips(piece[0]),
          closedEnd: closesLips(piece.at(-1)) || closesLips(nextPiece[0]),
          stressed,
        });
        for (let k = a; k < b; k++)
          reveal[i + k] = time + ((k - a) / piece.length) * duration * 0.85;
        time += duration;
      });
      i = j;
      continue;
    }
    reveal[i] = time;
    if (c === " ") time += pace.word;
    else if (/[.!?…]/.test(c)) {
      if (c === "!" || c === "?") emphasis.push(Math.max(0, time - 250));
      // "…" and several marks in a row only pause once.
      if (!/[.!?…]/.test(text[i + 1] || "")) time += pace.stop;
    } else if (/[,:;]/.test(c)) time += pace.comma;
    else if (/\d/.test(c)) {
      // Numbers are spoken like a short syllable each.
      result.push({
        start: time,
        end: time + pace.syllable,
        open: 0.55,
        closedStart: false,
        closedEnd: false,
        stressed: false,
      });
      time += pace.syllable;
    }
    i++;
  }
  // The final pause is handled between sentences instead.
  const lastSound = result.at(-1)?.end ?? 0;
  return { syllables: result, reveal, emphasis, total: Math.max(lastSound, time - pace.stop) };
}

const smooth = (x: number) => x * x * (3 - 2 * x);

// How open the mouth should be at a moment of the sentence.
function mouthAt(speech: Speech, time: number) {
  for (const s of speech.syllables) {
    if (time < s.start) return 0;
    if (time > s.end) continue;
    const p = (time - s.start) / (s.end - s.start);
    const from = s.closedStart ? 0 : 0.18;
    const to = s.closedEnd ? 0 : 0.24;
    // Open toward the vowel, hold it briefly, then ease into the next sound.
    const shape =
      p < 0.38
        ? from + (1 - from) * smooth(p / 0.38)
        : p < 0.62
          ? 1 - 0.08 * ((p - 0.38) / 0.24)
          : 0.92 + (to - 0.92) * smooth((p - 0.62) / 0.38);
    return s.open * shape;
  }
  return 0;
}

// Where her lips meet in the portrait (percent of the image), left to right.
const SEAM: [number, number][] = [
  [46.8, 45.65], [47.6, 45.85], [48.5, 45.98], [49.5, 45.9], [50.5, 45.8],
  [51.5, 45.74], [52.5, 45.58], [53.5, 45.28], [54.5, 45.0], [55.5, 44.72],
  [56.5, 44.38], [57.5, 43.9], [58.3, 43.4],
];
// How far the mouth opens at most, in percent of the portrait height.
const MAX_OPEN = 1.9;
const seamY = (x: number) => {
  for (let i = 1; i < SEAM.length; i++) {
    const [x0, y0] = SEAM[i - 1];
    const [x1, y1] = SEAM[i];
    if (x <= x1) return y0 + ((y1 - y0) * (x - x0)) / (x1 - x0);
  }
  return SEAM.at(-1)![1];
};
const point = ([x, y]: [number, number]) => `${x.toFixed(2)} ${y.toFixed(2)}`;

const MOUTH_LEFT = 47.3;
const MOUTH_RIGHT = 57.9;
// Closed at the lip corners, widest in the middle.
const opening = (x: number) => {
  const t = (x - MOUTH_LEFT) / (MOUTH_RIGHT - MOUTH_LEFT);
  return t <= 0 || t >= 1 ? 0 : Math.sin(Math.PI * t);
};
// The lower lip is cut into thin slices that drop by different amounts, so
// the middle opens most while the corners stay where they are.
const SLICES = Array.from({ length: 72 }, (_, index) => {
  const width = (59.6 - 46) / 72;
  const x = 46 + index * width;
  return { x, width, drop: opening(x + width / 2) };
});

// The opening between the lips: closed at the corners, widest in the middle.
function mouthPath(open: number) {
  const top: [number, number][] = [];
  const bottom: [number, number][] = [];
  for (let i = 0; i <= 24; i++) {
    const x = MOUTH_LEFT + ((MOUTH_RIGHT - MOUTH_LEFT) * i) / 24;
    const y = seamY(x) - 0.05;
    // The upper lip lifts a little; most of the opening is the jaw dropping.
    const shape = opening(x);
    top.push([x, y - open * 0.12 * shape]);
    bottom.push([x, y + 0.05 + open * shape]);
  }
  return `M${top.map(point).join("L")}L${bottom.reverse().map(point).join("L")}Z`;
}
// Upper teeth, just under the upper lip, only seen when the mouth is open.
function teethPath(open: number) {
  const height = Math.min(open * 0.42, 0.75);
  const top: [number, number][] = [];
  const bottom: [number, number][] = [];
  for (let i = 0; i <= 10; i++) {
    const x = 49 + (7.6 * i) / 10;
    const y = seamY(x) - open * 0.12;
    top.push([x, y]);
    bottom.push([x, y + height * Math.pow(Math.sin((Math.PI * i) / 10), 0.5)]);
  }
  return `M${top.map(point).join("L")}L${bottom.reverse().map(point).join("L")}Z`;
}
// The lower lip and the skin just under it; the soft mask hides its edges.
const JAW_CLIP = `M46.2 46.4L${SEAM.map(point).join("L")}L59.4 45.6L58.6 48.6L55.6 51L52 51.8L48.4 50.8L46.4 48.6Z`;

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
  const mouthTarget = useRef(0);
  const cavity = useRef<SVGPathElement>(null);
  const cavityClip = useRef<SVGPathElement>(null);
  const teeth = useRef<SVGPathElement>(null);
  const slices = useRef<(SVGGElement | null)[]>([]);
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

  // A soft spring follows the planned mouth shape every frame. It gives the
  // jaw a little weight, so it never snaps, like hand-drawn animation.
  useEffect(() => {
    if (still) return;
    let frame = 0;
    let current = 0;
    let velocity = 0;
    let drawn = -1;
    let previous = performance.now();
    const stiffness = 26; // Higher follows faster; lower is lazier.
    const draw = (now: number) => {
      const dt = Math.min(0.05, (now - previous) / 1000);
      previous = now;
      const target = mouthTarget.current;
      // Critically damped spring: smooth, with no wobble.
      const acceleration =
        stiffness * stiffness * (target - current) - 2 * stiffness * velocity;
      velocity += acceleration * dt;
      current = Math.max(0, Math.min(1.05, current + velocity * dt));
      if (Math.abs(current - drawn) > 0.002) {
        drawn = current;
        root.current?.style.setProperty("--mouth", current.toFixed(3));
        const open = current * MAX_OPEN;
        const d = mouthPath(open);
        cavity.current?.setAttribute("d", d);
        cavityClip.current?.setAttribute("d", d);
        teeth.current?.setAttribute("d", teethPath(open));
        teeth.current?.setAttribute(
          "opacity",
          Math.min(1, Math.max(0, (current - 0.25) / 0.35)).toFixed(2),
        );
        SLICES.forEach((slice, index) =>
          slices.current[index]?.setAttribute(
            "transform",
            `translate(0 ${(open * slice.drop).toFixed(3)})`,
          ),
        );
      }
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [still]);

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
        mouthTarget.current = 0;
        setChars(lines[line].length);
        return;
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      mouthTarget.current = 0;
    };
  }, [phase, line, still, speech, lines]);

  // Between sentences: a breath, a blink and a small nod, then the next one.
  const sentenceDone = chars >= lines[line].length;
  useEffect(() => {
    if (phase !== "alive" || still || !sentenceDone) return;
    if (line >= lines.length - 1) return;
    const gap = mode === "presentation" ? 1000 : mode === "farewell" ? 800 : 600;
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
        window.setTimeout(() => setPhase("setting"), 1700),
        window.setTimeout(() => {
          leaving.current = true;
          onDone();
        }, 4500),
      ];
      return () => timers.forEach(clearTimeout);
    }
    const timer = window.setTimeout(leave, 1800);
    return () => clearTimeout(timer);
  }, [finished]);

  function leave() {
    if (leaving.current) return;
    leaving.current = true;
    if (still) return onDone();
    setPhase("leaving");
    window.setTimeout(onDone, 900);
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
                      <svg
                        className="hana-mouth"
                        viewBox="0 0 100 100"
                        preserveAspectRatio="none"
                      >
                        <defs>
                          <clipPath id="hana-cavity-clip">
                            <path ref={cavityClip} d={mouthPath(0)} />
                          </clipPath>
                          <clipPath id="hana-jaw-clip">
                            <path d={JAW_CLIP} />
                          </clipPath>
                          {SLICES.map((slice, index) => (
                            <clipPath key={index} id={`hana-slice-${index}`}>
                              <rect
                                x={slice.x - 0.02}
                                y="40"
                                width={slice.width + 0.04}
                                height="16"
                              />
                            </clipPath>
                          ))}
                          <filter
                            id="hana-jaw-soft"
                            x="-20%"
                            y="-20%"
                            width="140%"
                            height="140%"
                          >
                            <feGaussianBlur stdDeviation="0.8" />
                          </filter>
                          <mask id="hana-jaw-mask">
                            <ellipse
                              cx="52.6"
                              cy="46.6"
                              rx="7"
                              ry="4.2"
                              fill="#fff"
                              transform="rotate(-11 52.6 46.6)"
                              filter="url(#hana-jaw-soft)"
                            />
                          </mask>
                          <radialGradient
                            id="hana-cavity-fill"
                            cx="50%"
                            cy="40%"
                            r="65%"
                          >
                            <stop offset="0%" stopColor="#1f0608" />
                            <stop offset="65%" stopColor="#4a1418" />
                            <stop offset="100%" stopColor="#8f3a3c" />
                          </radialGradient>
                          <linearGradient
                            id="hana-teeth-fill"
                            x1="0"
                            y1="0"
                            x2="0"
                            y2="1"
                          >
                            <stop offset="0%" stopColor="#fbf6f1" />
                            <stop offset="100%" stopColor="#d9cbc2" />
                          </linearGradient>
                        </defs>
                        {/* Inside of the mouth, revealed as the jaw drops. */}
                        <path
                          ref={cavity}
                          d={mouthPath(0)}
                          fill="url(#hana-cavity-fill)"
                        />
                        <g clipPath="url(#hana-cavity-clip)">
                          <ellipse
                            cx="52.6"
                            cy="47.6"
                            rx="3.6"
                            ry="1.3"
                            fill="#7a2c33"
                            opacity="0.8"
                          />
                          <path
                            ref={teeth}
                            d={teethPath(0)}
                            fill="url(#hana-teeth-fill)"
                            opacity="0"
                          />
                        </g>
                        {/* The lower lip, dropping most in the middle. */}
                        <g mask="url(#hana-jaw-mask)">
                          {SLICES.map((_, index) => (
                            <g
                              key={index}
                              ref={(element) => {
                                slices.current[index] = element;
                              }}
                            >
                              <g
                                clipPath={`url(#hana-slice-${index})`}
                              >
                                <g clipPath="url(#hana-jaw-clip)">
                                  <image
                                    href="/brand/hana-avatar.png"
                                    x="0"
                                    y="0"
                                    width="100"
                                    height="100"
                                    preserveAspectRatio="none"
                                  />
                                </g>
                              </g>
                            </g>
                          ))}
                        </g>
                      </svg>
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
