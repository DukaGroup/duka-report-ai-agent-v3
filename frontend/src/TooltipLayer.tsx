import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  autoUpdate,
  flip,
  offset,
  shift,
  useFloating,
} from "@floating-ui/react-dom";

type ActiveTooltip = { anchor: HTMLElement; text: string };

const tooltipId = "app-tooltip";

function tooltipTarget(target: EventTarget | null): HTMLElement | null {
  return target instanceof Element
    ? target.closest<HTMLElement>("[data-tooltip]")
    : null;
}

export function TooltipLayer() {
  const [active, setActive] = useState<ActiveTooltip | null>(null);
  const activeAnchor = useRef<HTMLElement | null>(null);
  const pendingAnchor = useRef<HTMLElement | null>(null);
  const timer = useRef<number | null>(null);
  const { refs, floatingStyles, isPositioned } = useFloating({
    open: !!active,
    placement: "top",
    strategy: "fixed",
    transform: false,
    whileElementsMounted: autoUpdate,
    middleware: [offset(10), flip({ padding: 12 }), shift({ padding: 12 })],
  });

  useEffect(() => {
    refs.setReference(active?.anchor || null);
  }, [active?.anchor, refs.setReference]);

  useEffect(() => {
    function clearPending() {
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = null;
      pendingAnchor.current = null;
    }
    function hideTooltip() {
      clearPending();
      activeAnchor.current = null;
      setActive(null);
    }
    function showTooltip(anchor: HTMLElement | null, delay: number) {
      const text = anchor?.dataset.tooltip?.trim();
      if (!anchor || !text || activeAnchor.current === anchor) return;
      if (pendingAnchor.current === anchor && delay) return;
      clearPending();
      const show = () => {
        pendingAnchor.current = null;
        if (!anchor.isConnected) return;
        activeAnchor.current = anchor;
        setActive({ anchor, text });
      };
      if (delay) {
        pendingAnchor.current = anchor;
        timer.current = window.setTimeout(show, delay);
      } else show();
    }
    function onPointerOver(event: PointerEvent) {
      if (event.pointerType !== "touch")
        showTooltip(tooltipTarget(event.target), 240);
    }
    function onPointerOut(event: PointerEvent) {
      const anchor = tooltipTarget(event.target);
      if (
        anchor &&
        anchor !== tooltipTarget(event.relatedTarget) &&
        (anchor === activeAnchor.current || anchor === pendingAnchor.current)
      )
        hideTooltip();
    }
    function onFocusIn(event: FocusEvent) {
      showTooltip(tooltipTarget(event.target), 0);
    }
    function onFocusOut(event: FocusEvent) {
      const anchor = tooltipTarget(event.target);
      if (
        anchor &&
        anchor !== tooltipTarget(event.relatedTarget) &&
        (anchor === activeAnchor.current || anchor === pendingAnchor.current)
      )
        hideTooltip();
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") hideTooltip();
    }
    document.addEventListener("pointerover", onPointerOver);
    document.addEventListener("pointerout", onPointerOut);
    document.addEventListener("focusin", onFocusIn);
    document.addEventListener("focusout", onFocusOut);
    document.addEventListener("click", hideTooltip);
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("scroll", hideTooltip, true);
    return () => {
      clearPending();
      document.removeEventListener("pointerover", onPointerOver);
      document.removeEventListener("pointerout", onPointerOut);
      document.removeEventListener("focusin", onFocusIn);
      document.removeEventListener("focusout", onFocusOut);
      document.removeEventListener("click", hideTooltip);
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("scroll", hideTooltip, true);
    };
  }, []);

  useEffect(() => {
    if (!active) return;
    const previous = active.anchor.getAttribute("aria-describedby");
    active.anchor.setAttribute(
      "aria-describedby",
      previous ? `${previous} ${tooltipId}` : tooltipId,
    );
    return () => {
      if (previous === null) active.anchor.removeAttribute("aria-describedby");
      else active.anchor.setAttribute("aria-describedby", previous);
    };
  }, [active]);

  return active
    ? createPortal(
        <div
          id={tooltipId}
          ref={refs.setFloating}
          role="tooltip"
          className="app-tooltip"
          style={{
            ...floatingStyles,
            visibility: isPositioned ? "visible" : "hidden",
          }}
        >
          {active.text}
        </div>,
        document.body,
      )
    : null;
}
