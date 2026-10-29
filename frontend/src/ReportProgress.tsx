import { Check } from "lucide-react";
import type { CSSProperties } from "react";
import { label } from "./locale";

const STEPS = [
  { id: "gathering", label: "Të dhënat" },
  { id: "analyzing", label: "Analiza" },
  { id: "excel", label: "Excel-i" },
  { id: "completed", label: "Gati" },
];

// Which step a report is on. Checking and fixing happen while the Excel is
// being prepared, so they count as that step.
function stepIndex(stage?: string | null) {
  if (stage === "analyzing") return 1;
  if (stage === "excel" || stage === "validating" || stage === "repairing")
    return 2;
  if (stage === "completed") return 3;
  return 0;
}

/** A small step bar that fills as a report moves toward being ready. */
export function ReportProgress({ stage }: { stage?: string | null }) {
  const current = stepIndex(stage);
  const waiting = !stage || stage === "queued" || stage === "recovering";
  return (
    <div
      className={`report-progress${waiting ? " waiting" : ""}`}
      style={{ "--progress": current / (STEPS.length - 1) } as CSSProperties}
      role="progressbar"
      aria-label="Përparimi i raportit"
      aria-valuemin={0}
      aria-valuemax={STEPS.length - 1}
      aria-valuenow={current}
      aria-valuetext={label(stage || "queued")}
    >
      <div className="report-progress-track" aria-hidden="true">
        <span className="report-progress-fill" />
      </div>
      <ol aria-hidden="true">
        {STEPS.map((step, index) => (
          <li
            key={step.id}
            className={
              index < current ? "done" : index === current ? "current" : ""
            }
          >
            <span className="report-progress-dot">
              {index < current && <Check size={10} strokeWidth={3} />}
            </span>
            <small>{step.label}</small>
          </li>
        ))}
      </ol>
      <p className="report-progress-label">{label(stage || "gathering")}</p>
    </div>
  );
}
