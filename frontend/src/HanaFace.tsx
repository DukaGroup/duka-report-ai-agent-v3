import { useEffect, useMemo, useRef, useState } from "react";
import {
  HanaMouth,
  useMouthSpring,
  type MouthHandle,
  type MouthShape,
} from "./HanaMouth";
import { mouthAt, PACE, planSpeech } from "./hanaSpeech";

const reducedMotion = () =>
  typeof window !== "undefined" &&
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/**
 * Hana's portrait that blinks by herself and, when given a line, says it with
 * the same natural mouth movement as her introduction. `onProgress` receives
 * how much of the line has been said, so a caption can follow along.
 */
export function HanaFace({
  line,
  delay = 600,
  onProgress,
}: {
  line?: string;
  delay?: number;
  onProgress?: (characters: number) => void;
}) {
  const still = useMemo(reducedMotion, []);
  const [blink, setBlink] = useState(false);
  const mouth = useRef<MouthHandle>(null);
  const target = useRef<MouthShape>({ open: 0, round: 0 });
  const progress = useRef(onProgress);
  progress.current = onProgress;

  useMouthSpring(mouth, target, undefined, !still);

  // Blink at irregular moments, sometimes twice.
  useEffect(() => {
    if (still) return;
    let timer = 0;
    const timers: number[] = [];
    const schedule = () => {
      timer = window.setTimeout(
        () => {
          setBlink(true);
          timers.push(window.setTimeout(() => setBlink(false), 160));
          if (Math.random() < 0.25) {
            timers.push(window.setTimeout(() => setBlink(true), 320));
            timers.push(window.setTimeout(() => setBlink(false), 480));
          }
          schedule();
        },
        2000 + Math.random() * 3500,
      );
    };
    schedule();
    return () => {
      clearTimeout(timer);
      timers.forEach(clearTimeout);
    };
  }, [still]);

  // Say the line once, with the caption following her voice.
  useEffect(() => {
    if (!line) return;
    if (still) {
      progress.current?.(line.length);
      return;
    }
    const plan = planSpeech(line, PACE.greeting);
    let frame = 0;
    let begin = 0;
    let shown = 0;
    const tick = (now: number) => {
      begin ||= now;
      const time = now - begin;
      let count = shown;
      while (count < plan.reveal.length && plan.reveal[count] <= time) count++;
      if (count !== shown) {
        shown = count;
        progress.current?.(count);
      }
      target.current = mouthAt(plan, time);
      if (time >= plan.total) {
        target.current = { open: 0, round: 0 };
        progress.current?.(line.length);
        return;
      }
      frame = requestAnimationFrame(tick);
    };
    const start = window.setTimeout(() => {
      frame = requestAnimationFrame(tick);
    }, delay);
    return () => {
      clearTimeout(start);
      cancelAnimationFrame(frame);
      target.current = { open: 0, round: 0 };
    };
  }, [line, delay, still]);

  return (
    <div className={`hana-face${blink ? " blink" : ""}`} aria-hidden="true">
      <img src="/brand/hana-avatar.png" alt="" draggable={false} />
      <HanaMouth ref={mouth} />
      <span className="hana-lid left" />
      <span className="hana-lid right" />
    </div>
  );
}
