import {
  Children,
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { X } from "lucide-react";

export const ERROR_TIMEOUT = 10_000;

/**
 * An error that closes itself after ten seconds or with its X button. While
 * the pointer or keyboard focus is on it the countdown pauses, so a long
 * message can still be read. With `onDismiss` the owner clears its error
 * state; without it the notice only hides itself until the message changes.
 */
export function ErrorNotice({
  children,
  onDismiss,
  className = "error-box",
  timeout = ERROR_TIMEOUT,
}: {
  children: ReactNode;
  onDismiss?: () => void;
  className?: string;
  timeout?: number;
}) {
  const [hidden, setHidden] = useState(false);
  const [paused, setPaused] = useState(false);
  const dismissRef = useRef(onDismiss);
  dismissRef.current = onDismiss;
  const timer = useRef<number | undefined>(undefined);
  const remaining = useRef(timeout);
  const started = useRef(0);
  // A new message restarts the countdown and shows the notice again.
  const signature = Children.toArray(children)
    .filter((part) => typeof part === "string" || typeof part === "number")
    .join("");

  const dismiss = useCallback(() => {
    window.clearTimeout(timer.current);
    setHidden(true);
    dismissRef.current?.();
  }, []);
  const resume = useCallback(() => {
    window.clearTimeout(timer.current);
    started.current = Date.now();
    timer.current = window.setTimeout(dismiss, Math.max(remaining.current, 0));
  }, [dismiss]);
  const pause = () => {
    window.clearTimeout(timer.current);
    remaining.current -= Date.now() - started.current;
  };

  useEffect(() => {
    setHidden(false);
    setPaused(false);
    remaining.current = timeout;
    resume();
    return () => window.clearTimeout(timer.current);
  }, [signature, timeout, resume]);

  if (hidden) return null;
  const hold = () => {
    if (paused) return;
    setPaused(true);
    pause();
  };
  const release = () => {
    if (!paused) return;
    setPaused(false);
    resume();
  };
  return (
    <div
      className={`${className} error-notice${paused ? " is-paused" : ""}`}
      role="alert"
      style={{ "--error-timeout": `${timeout}ms` } as CSSProperties}
      onMouseEnter={hold}
      onMouseLeave={release}
      onFocus={hold}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) release();
      }}
    >
      <div className="error-notice-body">{children}</div>
      <button
        type="button"
        className="error-notice-close"
        aria-label="Mbyll gabimin"
        data-tooltip="Mbyll gabimin"
        onClick={dismiss}
      >
        <X size={16} />
      </button>
      <span key={signature} className="error-notice-timer" aria-hidden="true" />
    </div>
  );
}
