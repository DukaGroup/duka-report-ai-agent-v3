import { ChevronRight, CircleCheck, LoaderCircle } from "lucide-react";
import type { ProgressStep } from "./types";

export function ActivityTimeline({
  steps,
  active,
}: {
  steps: ProgressStep[];
  active: boolean;
}) {
  if (!steps.length) return null;
  return (
    <details className="activity-timeline" open={active || undefined}>
      <summary>
        {/* Points right when closed and turns down when opened. */}
        <ChevronRight size={14} className="activity-chevron" />
        {active ? "Hapat e punës" : "Shiko hapat e punës"}{" "}
        <span>{steps.length}</span>
      </summary>
      <ol>
        {steps.map((step, index) => (
          <li key={step.id}>
            {active && index === steps.length - 1 ? (
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
