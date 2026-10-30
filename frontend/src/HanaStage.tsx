import { useEffect, useRef, useState } from "react";
import { HanaOrb, type OrbMode } from "./HanaOrb";
import { PACE, planSpeech } from "./hanaSpeech";
import "./hana-stage.css";

export type StageState =
  | "idle"
  | "greeting"
  | "listening"
  | "thinking"
  | "analyzing"
  | "searching"
  | "report"
  | "writing"
  | "done"
  | "error";

// What Hana says for each state when no more specific activity is known.
const DEFAULT_LINES: Record<StageState, string> = {
  idle: "Si mund t'ju ndihmoj?",
  greeting: "Përshëndetje! Jam këtu për ju.",
  listening: "Po ju dëgjoj…",
  thinking: "Po mendoj…",
  analyzing: "Po analizoj të dhënat…",
  searching: "Po kërkoj në internet…",
  report: "Po përgatis raportin…",
  writing: "Po shkruaj përgjigjen…",
  done: "Gati! Ja përgjigjja.",
  error: "Diçka nuk shkoi…",
};

/** Picks Hana's state from the activity text the chat already shows. */
export function stageFromActivity(activity: string): StageState {
  const text = activity.toLowerCase();
  if (/internet|faqen/.test(text)) return "searching";
  if (/raport|excel/.test(text)) return "report";
  if (/shkruaj/.test(text)) return "writing";
  if (/analizoj|kontrolloj|llogaris|lexoj|mbledh/.test(text))
    return "analyzing";
  return "thinking";
}

// A state is shown for at least this long, so quick tool calls do not make
// the orb flicker between moods.
const MIN_HOLD = 600;

const ORB_MODE: Record<StageState, OrbMode> = {
  idle: "idle",
  greeting: "idle",
  listening: "listening",
  thinking: "thinking",
  searching: "thinking",
  analyzing: "working",
  report: "working",
  writing: "speaking",
  done: "done",
  error: "error",
};

function isBusy(state: StageState) {
  return ["thinking", "analyzing", "searching", "report", "writing"].includes(
    state,
  );
}

/** Activity takes priority over the decorative reveal of a status line. */
export function orbModeForStage(state: StageState, revealing = false): OrbMode {
  if (revealing && (state === "idle" || state === "greeting"))
    return "speaking";
  return ORB_MODE[state];
}

/** Reveals a line at Hana's speaking pace; returns how much is shown. */
function useSpokenLine(line: string, animate: boolean) {
  const [said, setSaid] = useState(0);
  useEffect(() => {
    setSaid(0);
    if (
      !animate ||
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
    ) {
      setSaid(line.length);
      return;
    }
    const { reveal } = planSpeech(line, PACE.greeting);
    let frame = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const time = now - start;
      let count = 0;
      while (count < reveal.length && reveal[count] <= time) count++;
      setSaid(count);
      if (count < line.length) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [line, animate]);
  return said;
}

/**
 * Hana beside the chat: an orb whose shapes move with what she is doing
 * (thinking, working, speaking…) and a speech bubble with what she says.
 */
export function HanaStage({
  state,
  line,
}: {
  state: StageState;
  line?: string;
}) {
  const wanted = {
    state,
    line: line || DEFAULT_LINES[state],
  };
  const [shown, setShown] = useState(wanted);
  const since = useRef(Date.now());

  useEffect(() => {
    if (wanted.state === shown.state && wanted.line === shown.line) return;
    // Starting work and finishing it respond immediately. Only smooth out
    // rapid changes between active phases in the status bubble.
    const wait =
      isBusy(shown.state) && isBusy(wanted.state)
        ? Math.max(0, MIN_HOLD - (Date.now() - since.current))
        : 0;
    const timer = window.setTimeout(() => {
      since.current = Date.now();
      setShown(wanted);
    }, wait);
    return () => clearTimeout(timer);
  }, [wanted.state, wanted.line, shown.state, shown.line]);

  const busy = isBusy(wanted.state);
  const said = useSpokenLine(
    shown.line,
    !busy && wanted.state !== "done" && wanted.state !== "error",
  );
  const visibleCharacters =
    busy || wanted.state === "done" || wanted.state === "error"
      ? shown.line.length
      : said;
  const speaking = visibleCharacters < shown.line.length;
  return (
    <aside
      className={`hana-stage state-${shown.state}${busy ? " busy" : ""}`}
      aria-label="Hana"
    >
      <div className="stage-center">
        <div
          className="stage-bubble"
          role="status"
          aria-live="polite"
          key={shown.line}
        >
          <span className="stage-bubble-name">
            <i className="stage-live" /> Hana
          </span>
          <p>
            {shown.line.slice(0, visibleCharacters)}
            {speaking && <span className="stage-caret" />}
          </p>
          {busy && (
            <span className="stage-dots" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
          )}
        </div>
        <div className="stage-orb">
          <HanaOrb mode={orbModeForStage(wanted.state, speaking)} />
        </div>
      </div>
    </aside>
  );
}
