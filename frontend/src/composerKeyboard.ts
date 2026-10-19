/** Only ordinary typing outside another editing surface belongs in the composer. */
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
  return (
    !target.closest(
      'input, textarea, select, [contenteditable]:not([contenteditable="false"]), ' +
        '[role="textbox"], [role="combobox"], [role="listbox"], [role="menu"], [role="slider"]',
    ) &&
    !(
      event.key === " " &&
      target.closest('button, a, [role="button"], [role="checkbox"]')
    )
  );
}
