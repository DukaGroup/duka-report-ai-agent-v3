import { useEffect, useMemo, useRef } from "react";
import {
  HanaMouth,
  useMouthSpring,
  type MouthHandle,
  type MouthShape,
} from "./HanaMouth";
import { mouthAt, PACE, planSpeech } from "./hanaSpeech";
import { HANA_PORTRAIT } from "./hanaAvatar";
import { HanaEyes } from "./HanaEyes";
import "./hana-intro.css";

const reducedMotion = () =>
  typeof window !== "undefined" &&
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/**
 * Hana's portrait that blinks by herself and, when given a line, says it with
 * the same mouth as her introduction. `onProgress` receives how much of the
 * line has been said, so a caption can follow along.
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
  const mouth = useRef<MouthHandle>(null);
  const pose = useRef<HTMLDivElement>(null);
  const target = useRef<MouthShape>({ open: 0, round: 0 });
  const progress = useRef(onProgress);
  progress.current = onProgress;

  useMouthSpring(mouth, target, undefined, !still);

  // Say the line once, with the caption following her voice.
  useEffect(() => {
    if (!line) return;
    if (still) {
      progress.current?.(line.length);
      return;
    }
    const plan = planSpeech(line, PACE.greeting);
    let animationFrame = 0;
    let begin = 0;
    let shown = 0;
    let syllable = 0;
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
      // A small nod lands on some stressed syllables, as people do.
      while (
        syllable < plan.syllables.length &&
        plan.syllables[syllable].start <= time
      ) {
        if (plan.syllables[syllable].stressed && syllable % 4 === 0)
          pose.current?.animate(
            [
              { transform: "none" },
              { transform: "translateY(0.25%) rotate(-0.3deg)" },
              { transform: "none" },
            ],
            { duration: 720, easing: "ease-in-out" },
          );
        syllable++;
      }
      if (time >= plan.total) {
        target.current = { open: 0, round: 0 };
        progress.current?.(line.length);
        return;
      }
      animationFrame = requestAnimationFrame(tick);
    };
    const start = window.setTimeout(() => {
      animationFrame = requestAnimationFrame(tick);
    }, delay);
    return () => {
      clearTimeout(start);
      cancelAnimationFrame(animationFrame);
      target.current = { open: 0, round: 0 };
    };
  }, [line, delay, still]);

  return (
    <div className="hana-face" aria-hidden="true">
      <div className="hana-face-source">
        <div ref={pose} className="hana-face-pose">
          <img src={HANA_PORTRAIT} alt="" draggable={false} />
          <HanaMouth ref={mouth} />
          <HanaEyes />
        </div>
      </div>
    </div>
  );
}

/**
 * Hana framed as she appears after the moonrise: a glowing, softly masked
 * circle. Her introduction flies into this slot and lands exactly on it, so
 * while `awaiting` she stays hidden and the flying Hana takes her place.
 */
export function HanaSlot({
  line,
  delay,
  awaiting = false,
  className = "",
  onProgress,
}: {
  line?: string;
  delay?: number;
  awaiting?: boolean;
  className?: string;
  onProgress?: (characters: number) => void;
}) {
  return (
    <div
      className={`hana-slot${awaiting ? " is-awaiting" : ""} ${className}`}
      role="img"
      aria-label="Hana"
    >
      <span className="hana-slot-orbit" aria-hidden="true" />
      <span className="hana-slot-orbit inner" aria-hidden="true" />
      <div className="hana-halo" />
      <div className="hana-slot-portrait">
        <HanaFace
          line={awaiting ? undefined : line}
          delay={delay}
          onProgress={onProgress}
        />
      </div>
    </div>
  );
}
