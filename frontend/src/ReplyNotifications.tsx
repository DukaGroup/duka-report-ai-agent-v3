import { ArrowUpRight, Check, X } from "lucide-react";
import { useLayoutEffect, useRef } from "react";
import type { ReplyNotification } from "./replyNotifications";
import { fromScreen } from "./uiScale";

export function ReplyNotifications({
  items,
  onOpen,
  onDismiss,
  disabled,
  layoutKey,
}: {
  items: ReplyNotification[];
  onOpen: (item: ReplyNotification) => void;
  onDismiss: (id: string) => void;
  disabled: boolean;
  layoutKey?: string;
}) {
  const container = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const header = document.querySelector("header.topbar");
    const composer = document.querySelector(".composer-wrap");
    const position = () => {
      if (!container.current) return;
      const viewport = window.visualViewport;
      const viewportTop = viewport?.offsetTop || 0;
      const top =
        Math.max(header?.getBoundingClientRect().bottom || 64, viewportTop) +
        12;
      const bottom =
        Math.min(
          viewportTop + (viewport?.height || window.innerHeight),
          composer?.getBoundingClientRect().top ?? Infinity,
        ) - 12;
      // Screen pixels → CSS pixels (the interface may be zoomed).
      container.current.style.top = `${fromScreen(top)}px`;
      container.current.style.maxHeight = `${fromScreen(Math.max(0, bottom - top))}px`;
    };
    position();
    const observer = new ResizeObserver(position);
    if (header) observer.observe(header);
    if (composer) observer.observe(composer);
    window.addEventListener("resize", position);
    window.visualViewport?.addEventListener("resize", position);
    window.visualViewport?.addEventListener("scroll", position);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", position);
      window.visualViewport?.removeEventListener("resize", position);
      window.visualViewport?.removeEventListener("scroll", position);
    };
  }, [items.length, layoutKey]);
  return (
    <aside
      ref={container}
      className="reply-notifications"
      aria-label="Njoftimet e bisedave"
      aria-live="polite"
      aria-relevant="additions"
    >
      {items.map((item) => (
        <div className="reply-notification" key={item.id}>
          <span className="reply-notification-icon" aria-hidden="true">
            <Check size={22} />
          </span>
          <button
            type="button"
            className="reply-notification-open"
            disabled={disabled}
            onClick={() => onOpen(item)}
            aria-label={`Hap përgjigjen: ${item.title}`}
          >
            <strong>
              {item.kind === "report"
                ? "Raporti është gati"
                : "Përgjigjja përfundoi"}
            </strong>
            <span>{item.title}</span>
            <small>
              Hap bisedën <ArrowUpRight size={14} aria-hidden="true" />
            </small>
          </button>
          <button
            type="button"
            className="icon-button reply-notification-dismiss"
            aria-label={`Mbyll njoftimin: ${item.title}`}
            data-tooltip="Mbyll njoftimin"
            onClick={() => onDismiss(item.id)}
          >
            <X size={17} />
          </button>
        </div>
      ))}
    </aside>
  );
}
