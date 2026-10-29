import { useEffect, useRef, useState } from "react";

/**
 * IDs of items that finished while the user was watching (queued/running →
 * completed), for a short celebration. Items already complete on load are not
 * celebrated.
 */
export function useJustCompleted(
  items: { id: string; status: string }[],
  duration = 4000,
) {
  const previous = useRef(new Map<string, string>());
  const [fresh, setFresh] = useState<ReadonlySet<string>>(new Set());
  useEffect(() => {
    const done: string[] = [];
    for (const item of items) {
      const before = previous.current.get(item.id);
      if (
        (before === "queued" || before === "running") &&
        item.status === "completed"
      )
        done.push(item.id);
      previous.current.set(item.id, item.status);
    }
    if (!done.length) return;
    setFresh((current) => new Set([...current, ...done]));
    window.setTimeout(
      () =>
        setFresh((current) => {
          const next = new Set(current);
          done.forEach((id) => next.delete(id));
          return next;
        }),
      duration,
    );
  });
  return fresh;
}
