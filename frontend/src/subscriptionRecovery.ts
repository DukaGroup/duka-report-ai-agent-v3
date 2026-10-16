/** Retry temporary connection failures without overlapping requests or logging in. */
export function recoverSubscription(
  refresh: () => Promise<boolean>,
  delay = 5000,
  immediate = false,
) {
  let stopped = false;
  let pending = false;
  let timer: ReturnType<typeof setTimeout>;

  const schedule = () => {
    if (!stopped) timer = setTimeout(() => void retry(), delay);
  };
  const retry = async () => {
    if (stopped || pending) return;
    clearTimeout(timer);
    pending = true;
    let recovered = false;
    try {
      recovered = await refresh();
    } catch {
      // The network may still be offline; keep checking the saved session.
    } finally {
      pending = false;
      if (recovered) stopped = true;
      schedule();
    }
  };
  const online = () => void retry();
  const visible = () => {
    if (document.visibilityState === "visible") void retry();
  };
  window.addEventListener("online", online);
  document.addEventListener("visibilitychange", visible);
  if (immediate) void retry();
  else schedule();
  return () => {
    stopped = true;
    clearTimeout(timer);
    window.removeEventListener("online", online);
    document.removeEventListener("visibilitychange", visible);
  };
}
