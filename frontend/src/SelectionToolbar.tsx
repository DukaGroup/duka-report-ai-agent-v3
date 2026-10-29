import { Trash2, X, LoaderCircle, RotateCcw } from "lucide-react";
import { IconButton } from "./IconButton";

type Props = {
  available: number;
  selected: number;
  busy: boolean;
  permanent?: boolean;
  kind?: "reports" | "conversations";
  onToggleAll: (checked: boolean) => void;
  onClear: () => void;
  onDelete: () => void;
  onRestore?: () => void;
  restoring?: boolean;
};
export function SelectionToolbar({
  available,
  selected,
  busy,
  permanent = false,
  kind = "reports",
  onToggleAll,
  onClear,
  onDelete,
  onRestore,
  restoring = false,
}: Props) {
  return (
    <div
      className="report-selection-toolbar"
      role="group"
      aria-label={
        kind === "conversations"
          ? "Përzgjedhja e bisedave"
          : permanent
            ? "Përzgjedhja në kosh"
            : "Përzgjedhja e raporteve"
      }
    >
      <label className="report-select-all">
        <input
          type="checkbox"
          checked={available > 0 && selected === available}
          ref={(node) => {
            if (node) node.indeterminate = selected > 0 && selected < available;
          }}
          disabled={!available || busy}
          onChange={(e) => onToggleAll(e.target.checked)}
        />
        Zgjidh të gjitha
      </label>
      <span className="report-selection-count" role="status">
        {selected} të zgjedhura
      </span>
      <div className="report-selection-actions">
        <IconButton
          label="Pastro përzgjedhjen"
          disabled={!selected || busy}
          onClick={onClear}
        >
          <X size={18} />
        </IconButton>
        {permanent && onRestore && (
          <IconButton
            label={
              kind === "conversations"
                ? "Rikthe bisedat e zgjedhura"
                : "Rikthe raportet e zgjedhura"
            }
            disabled={!selected || busy}
            onClick={onRestore}
          >
            {restoring ? (
              <LoaderCircle size={18} className="spin" />
            ) : (
              <RotateCcw size={18} />
            )}
          </IconButton>
        )}
        <button
          className="button danger small"
          disabled={!selected || busy}
          aria-label={
            kind === "conversations"
              ? permanent
                ? "Fshi përgjithmonë bisedat e zgjedhura"
                : "Fshi bisedat e zgjedhura"
              : permanent
                ? "Fshi përgjithmonë raportet e zgjedhura"
                : "Fshi raportet e zgjedhura"
          }
          onClick={onDelete}
        >
          {busy && !restoring ? (
            <LoaderCircle size={17} className="spin" />
          ) : (
            <Trash2 size={17} />
          )}{" "}
          {permanent ? "Fshi përgjithmonë" : "Fshi të zgjedhurat"}
        </button>
      </div>
    </div>
  );
}
