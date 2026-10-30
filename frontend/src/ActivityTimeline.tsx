import { ChevronRight, CircleCheck, LoaderCircle } from "lucide-react";
import type { ProgressStep } from "./types";

export function ActivityTimeline({
  steps,
  active,
  technical = false,
}: {
  steps: ProgressStep[];
  active: boolean;
  technical?: boolean;
}) {
  // Protect history already loaded in an open browser as well as new replies.
  if (!technical || !steps.length) return null;
  const visibleSteps: ProgressStep[] = [];
  let previousLabel: string | null = null;
  for (const step of steps) {
    const label = step.label.trim().replace(/\s+/g, " ");
    if (label === previousLabel) continue;
    visibleSteps.push(step);
    previousLabel = label;
  }
  return (
    // Closed by default, even while Hana works: the steps show only when the
    // user opens them.
    <details className="activity-timeline">
      <summary>
        {/* Points right when closed and turns down when opened. */}
        <ChevronRight size={14} className="activity-chevron" />
        {active ? "Hapat e punës" : "Shiko hapat e punës"}{" "}
        <span>{visibleSteps.length}</span>
      </summary>
      <ol>
        {visibleSteps.map((step, index) => (
          <li key={step.id}>
            {active && index === visibleSteps.length - 1 ? (
              <LoaderCircle size={13} className="spin" />
            ) : (
              <CircleCheck size={13} />
            )}
            <span>{step.label}</span>
          </li>
        ))}
      </ol>
    </details>
  );
}
