import { useEffect, useRef, useState } from "react";
import { Check, Copy } from "lucide-react";

export function CopyMessageButton({ text }: { text: string }) {
  const [status, setStatus] = useState<"idle" | "copied" | "error">("idle");
  const mounted = useRef(true);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      clearTimeout(timer.current);
    };
  }, []);

  async function copy() {
    clearTimeout(timer.current);
    try {
      await navigator.clipboard.writeText(text);
      if (!mounted.current) return;
      setStatus("copied");
      timer.current = setTimeout(() => setStatus("idle"), 2000);
    } catch {
      if (mounted.current) setStatus("error");
    }
  }

  const label = status === "copied" ? "Mesazhi u kopjua" : "Kopjo mesazhin";
  return (
    <>
      <button
        type="button"
        className="icon-button"
        aria-label={label}
        data-tooltip={label}
        disabled={!text}
        onClick={() => void copy()}
      >
        {status === "copied" ? (
          <Check size={16} aria-hidden="true" />
        ) : (
          <Copy size={16} aria-hidden="true" />
        )}
      </button>
      <span
        role="status"
        className={status === "error" ? "message-copy-error" : "sr-only"}
      >
        {status === "copied"
          ? "Mesazhi u kopjua."
          : status === "error"
            ? "Kopjimi dështoi. Zgjidhni tekstin dhe kopjojeni manualisht."
            : ""}
      </span>
    </>
  );
}
