import { useLayoutEffect, useRef } from "react";

const focusableSelector =
  'button, a[href], input:not([type="hidden"]), textarea, select, [tabindex]:not([tabindex="-1"])';

function available(element: HTMLElement): boolean {
  return (
    !element.matches(":disabled") &&
    element.getAttribute("aria-disabled") !== "true" &&
    element.getClientRects().length > 0
  );
}

function focusable(modal: HTMLElement): HTMLElement[] {
  return Array.from(modal.querySelectorAll<HTMLElement>(focusableSelector)).filter(
    available,
  );
}

function initialTarget(modal: HTMLElement): HTMLElement | undefined {
  const elements = focusable(modal);
  return (
    elements.find((element) => element.hasAttribute("data-modal-default")) ||
    elements.find(
      (element) =>
        element.closest("form") &&
        element.matches('input:not([type="checkbox"]):not([type="radio"]), textarea'),
    ) ||
    elements.find(
      (element) =>
        element.closest("form") && element.matches('select, [role="combobox"]'),
    ) ||
    [...elements].reverse().find((element) => element.closest(".modal-actions")) ||
    elements.find(
      (element) =>
        element.closest("form") &&
        element.matches('button[type="submit"], button:not([type])'),
    ) ||
    elements.find(
      (element) => element.getAttribute("aria-label") === "Mbyll dritaren",
    ) ||
    elements[0]
  );
}

/** Give each dialog a useful Enter action and keep keyboard focus inside it. */
export function useModalKeyboard(open = true) {
  const ref = useRef<HTMLElement>(null);

  useLayoutEffect(() => {
    const modal = ref.current;
    if (!open || !modal) return;

    const previous = document.activeElement;
    (initialTarget(modal) || modal).focus({ preventScroll: true });

    function onKeyDown(event: KeyboardEvent) {
      if (!modal) return;
      const dialogs = document.querySelectorAll('[role="dialog"][aria-modal="true"]');
      if (dialogs[dialogs.length - 1] !== modal) return;

      if (event.key === "Tab") {
        const items = focusable(modal);
        if (!items.length) {
          event.preventDefault();
          modal.focus();
        } else if (!modal.contains(document.activeElement)) {
          event.preventDefault();
          items[0].focus();
        } else if (event.shiftKey && document.activeElement === items[0]) {
          event.preventDefault();
          items[items.length - 1].focus();
        } else if (
          !event.shiftKey &&
          document.activeElement === items[items.length - 1]
        ) {
          event.preventDefault();
          items[0].focus();
        }
      } else if (
        event.key === "Enter" &&
        !event.repeat &&
        !event.isComposing &&
        event.target === modal
      ) {
        const target = initialTarget(modal);
        if (target instanceof HTMLButtonElement || target instanceof HTMLAnchorElement) {
          event.preventDefault();
          target.click();
        } else if (target) {
          target.focus();
        }
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      if (previous instanceof HTMLElement && previous.isConnected)
        previous.focus({ preventScroll: true });
    };
  }, [open]);

  return ref;
}
