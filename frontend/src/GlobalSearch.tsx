import { useEffect, useRef, useState } from "react";
import { Search, X } from "lucide-react";
import { api } from "./api";
import { SERVICE_UNAVAILABLE } from "./locale";

export type SearchResult = {
  kind: string;
  id: string;
  title: string;
  excerpt?: string;
  message_id?: string;
};
export function GlobalSearch({
  onSelect,
  navigation,
}: {
  onSelect: (result: SearchResult) => void;
  navigation: SearchResult[];
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (query.trim().length < 2) {
      setResults([]);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(false);
    const timer = setTimeout(() => {
      void api<{ results: SearchResult[] }>(
        `/search?q=${encodeURIComponent(query.trim())}`,
        { signal: controller.signal },
      )
        .then((data) => {
          if (!controller.signal.aborted) setResults(data.results);
        })
        .catch(() => {
          if (!controller.signal.aborted) setError(true);
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query]);
  useEffect(() => {
    const outside = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, []);
  const labels: Record<string, string> = {
    conversation: "Bisedë",
    report: "Raport",
    source: "Burim",
    navigation: "Shko te",
    member: "Anëtar",
    traffic: "Trafik",
    log: "Regjistri i sistemit",
  };
  const choices = [
    ...navigation.filter((item) =>
      item.title
        .toLocaleLowerCase("sq")
        .includes(query.toLocaleLowerCase("sq")),
    ),
    ...results,
  ];
  const pick = (item: SearchResult) => {
    setOpen(false);
    setQuery("");
    onSelect(item);
  };
  return (
    <div className="global-search" ref={ref}>
      <label>
        <Search size={17} />
        <input
          type="search"
          aria-label="Kërko në sistem"
          placeholder="Kërko biseda, mesazhe, raporte…"
          value={query}
          maxLength={200}
          onChange={(e) => {
            setQuery(e.target.value);
            setResults([]);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "Escape") setOpen(false);
            if (e.key === "Enter" && choices.length) {
              e.preventDefault();
              pick(choices[0]);
            }
          }}
        />
      </label>
      {query && (
        <button
          type="button"
          className="icon-button global-search-clear"
          aria-label="Pastro kërkimin"
          onClick={() => {
            setQuery("");
            setOpen(false);
          }}
        >
          <X size={15} />
        </button>
      )}
      {open && query.trim().length >= 2 && (
        <section
          className="global-search-results"
          aria-label="Rezultatet e kërkimit"
        >
          {loading && <p role="status">Duke kërkuar…</p>}
          {error && <p role="alert">{SERVICE_UNAVAILABLE}</p>}
          {!loading && !error && !choices.length && (
            <p>Nuk u gjetën rezultate.</p>
          )}
          {choices.map((item) => (
            <button
              type="button"
              key={`${item.kind}:${item.id}`}
              onClick={() => pick(item)}
            >
              <small>{labels[item.kind] || item.kind}</small>
              <strong>{item.title}</strong>
              {item.excerpt && <span>{item.excerpt}</span>}
            </button>
          ))}
        </section>
      )}
    </div>
  );
}
