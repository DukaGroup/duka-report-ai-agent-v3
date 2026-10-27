/** Route typing from the chat background to the composer, never from a focused control. */
export function shouldCaptureTyping(
  event: KeyboardEvent,
  selection: string,
  modalOpen: boolean,
) {
  if (
    modalOpen ||
    selection ||
    event.defaultPrevented ||
    event.isComposing ||
    event.ctrlKey ||
    event.metaKey ||
    event.altKey ||
    event.key.length !== 1
  )
    return false;
  const target = event.target;
  if (!(target instanceof Element)) return false;
  return !target.closest(
    'input, textarea, select, [contenteditable]:not([contenteditable="false"]), ' +
      'button, a, [role="button"], [role="checkbox"], [role="radio"], ' +
      '[role="switch"], [role="textbox"], [role="combobox"], ' +
      '[role="listbox"], [role="menu"], [role="slider"]',
  );
}

/** Plain Enter submits the chat form; Shift+Enter remains a newline. */
export function shouldSubmitComposerOnEnter(
  event: Pick<
    KeyboardEvent,
    | "key"
    | "shiftKey"
    | "ctrlKey"
    | "metaKey"
    | "altKey"
    | "isComposing"
    | "repeat"
  >,
) {
  return (
    event.key === "Enter" &&
    !event.shiftKey &&
    !event.ctrlKey &&
    !event.metaKey &&
    !event.altKey &&
    !event.isComposing &&
    !event.repeat
  );
}
