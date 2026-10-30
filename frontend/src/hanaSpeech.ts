import type { MouthShape } from "./hanaFaceGeometry";

export type IntroMode = "presentation" | "greeting" | "farewell";

/** Moonrise, transformation and greeting have separate time budgets. */
export function transitionTiming(mode: IntroMode, still = false) {
  const rise = still || mode === "farewell" ? 0 : 1300;
  const transformation = still ? 0 : mode === "farewell" ? 1000 : 1200;
  const speechStart = mode === "farewell" ? 0 : rise + transformation;
  const speechEnd = speechStart + 1700;
  return {
    rise,
    transformation,
    speechStart,
    speechEnd,
    total: speechEnd + (still ? 0 : mode === "farewell" ? transformation : 250),
  };
}

/** Exact critically damped spring step; stable even when frames are delayed. */
export function stepSpring(
  position: number,
  velocity: number,
  target: number,
  stiffness: number,
  dt: number,
) {
  const offset = position - target;
  const impulse = (velocity + stiffness * offset) * dt;
  const decay = Math.exp(-stiffness * dt);
  return {
    position: target + (offset + impulse) * decay,
    velocity: (velocity - stiffness * impulse) * decay,
  };
}

/*
 * Speech planning. Each sentence is split into syllables, and every syllable
 * gets a smooth open-and-close curve: the vowel sets how wide the mouth opens,
 * m/b/p close the lips, and the last syllable before a pause is drawn out, the
 * way people slow down at the end of a phrase. Letters appear in time with it.
 */
const VOWEL_OPEN: Record<string, number> = {
  a: 1,
  o: 0.8,
  e: 0.66,
  u: 0.5,
  y: 0.42,
  i: 0.4,
  ë: 0.34,
};
// Lips round for o, u and y (like the German ü); spread for e and i.
const VOWEL_ROUND: Record<string, number> = {
  o: 0.75,
  u: 1,
  y: 0.7,
  ë: 0.15,
};
const isVowel = (c: string) => c.toLowerCase() in VOWEL_OPEN;
const isLetter = (c: string) => /[a-zçë]/i.test(c);
const closesLips = (c: string | undefined) => !!c && /[mbp]/i.test(c);

export type Pace = {
  syllable: number;
  word: number;
  comma: number;
  stop: number;
};
export const PACE: Record<IntroMode, Pace> = {
  presentation: { syllable: 115, word: 18, comma: 160, stop: 260 },
  greeting: { syllable: 105, word: 15, comma: 130, stop: 210 },
  farewell: { syllable: 110, word: 16, comma: 140, stop: 230 },
};

type Syllable = {
  start: number;
  end: number;
  open: number;
  round: number;
  closedStart: boolean;
  closedEnd: boolean;
  stressed: boolean;
};
export type Speech = {
  syllables: Syllable[];
  // When each character of the sentence appears (ms from its start).
  reveal: number[];
  // Moments for a stronger head movement ("!" and "?").
  emphasis: number[];
  total: number;
};

// Splits a word into syllables: one consonant between vowels starts the next
// syllable; with two or more, the first stays with the previous one.
export function syllables(word: string): [number, number][] {
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

export function planSpeech(text: string, pace: Pace): Speech {
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
        const weak =
          last && parts.length > 1 && /ë$/i.test(piece) && piece.length <= 2;
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
          round: vowel ? VOWEL_ROUND[vowel] || 0 : 0,
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
        round: 0,
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
  return {
    syllables: result,
    reveal,
    emphasis,
    total: Math.max(lastSound, time - pace.stop),
  };
}

const smooth = (x: number) => x * x * (3 - 2 * x);

type MouthKey = { time: number; open: number; round: number };
// Breaks longer than this (commas, full stops) let the lips close.
const PAUSE = 50;

/**
 * Key mouth shapes for a sentence. Each vowel is a peak; between syllables
 * the mouth only half closes, the way sounds run together in real speech,
 * and it shuts fully only for m, b and p and in pauses.
 */
function mouthKeys(speech: Speech): MouthKey[] {
  const keys: MouthKey[] = [];
  const list = speech.syllables;
  list.forEach((s, i) => {
    const previous = list[i - 1];
    const next = list[i + 1];
    const duration = s.end - s.start;
    if (!previous || s.start - previous.end > PAUSE)
      keys.push({ time: s.start, open: 0, round: 0 });
    else if (s.closedStart) keys.push({ time: s.start, open: 0, round: s.round * 0.5 });
    keys.push({ time: s.start + duration * 0.42, open: s.open * 0.92, round: s.round });
    if (!next || next.start - s.end > PAUSE)
      keys.push({ time: s.end, open: 0, round: 0 });
    else if (s.closedEnd) keys.push({ time: s.end, open: 0, round: (s.round + next.round) / 2 });
    else
      keys.push({
        time: s.end,
        open: 0.32 * Math.min(s.open, next.open),
        round: (s.round + next.round) / 2,
      });
  });
  return keys;
}
const keyCache = new WeakMap<Speech, MouthKey[]>();

/** How open and how rounded the mouth is at a moment of the sentence. */
export function mouthAt(speech: Speech, time: number): MouthShape {
  let keys = keyCache.get(speech);
  if (!keys) {
    keys = mouthKeys(speech);
    keyCache.set(speech, keys);
  }
  if (!keys.length || time <= keys[0].time || time >= keys[keys.length - 1].time)
    return { open: 0, round: 0 };
  let i = 1;
  while (keys[i].time < time) i++;
  const a = keys[i - 1],
    b = keys[i];
  const t = b.time > a.time ? smooth((time - a.time) / (b.time - a.time)) : 1;
  return {
    open: a.open + (b.open - a.open) * t,
    round: a.round + (b.round - a.round) * t,
  };
}
