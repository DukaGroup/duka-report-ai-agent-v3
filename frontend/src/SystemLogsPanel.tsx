import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Download,
  Pause,
  Play,
  RefreshCw,
} from "lucide-react";
import { api } from "./api";
import { IconButton } from "./IconButton";
import { errorMessage } from "./locale";
import { Select } from "./Select";

type LogEvent = {
  id: number;
  created_at: string;
  level: string;
  component: string;
  event: string;
  message: string;
  source_name: string | null;
  details: Record<string, unknown>;
};
type LogPage = {
  events: LogEvent[];
  next_before: number | null;
  capacity: number | null;
};
const levels: Record<string, string> = {
  info: "Informacion",
  warning: "Paralajmërim",
  error: "Gabim",
};
const components: Record<string, string> = {
  application: "Aplikacioni",
  database: "Databazat",
  model: "Modeli",
  reports: "Raportet",
};

export function SystemLogsPanel({ eventId }: { eventId?: number }) {
  useEffect(() => {
    if (eventId) {
      setBefore(eventId + 1);
      setLive(false);
    }
  }, [eventId]);
  const [data, setData] = useState<LogPage | null>(null);
  const [level, setLevel] = useState("");
  const [component, setComponent] = useState("");
  const [before, setBefore] = useState(0);
  const [live, setLive] = useState(true);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const generation = useRef(0);
  const request = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    const current = generation.current;
    setLoading(true);
    try {
      const query = new URLSearchParams({
        level,
        component,
        before: String(before),
        limit: "100",
      });
      const result = await api<LogPage>(`/admin/system-logs?${query}`, {
        signal: controller.signal,
      });
      if (current === generation.current && !controller.signal.aborted) {
        setData(result);
        setError("");
      }
    } catch {
      if (current === generation.current && !controller.signal.aborted)
        setError("Regjistrat nuk u ngarkuan. Provoni përsëri.");
    } finally {
      if (request.current === controller) {
        request.current = null;
        setLoading(false);
      }
    }
  }, [level, component, before]);

  useEffect(() => {
    generation.current += 1;
    setData(null);
    setLoading(false);
    void refresh();
    const timer = window.setInterval(() => {
      if (live && !before && !request.current) void refresh();
    }, 5000);
    return () => {
      generation.current += 1;
      request.current?.abort();
      window.clearInterval(timer);
    };
  }, [refresh, live, before]);

  function download() {
    if (!data) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "hana-system-logs.json";
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  return (
    <section className="panel system-log-panel">
      <div className="panel-heading">
        <h3>Regjistrat e sistemit</h3>
        <div className="traffic-actions">
          <IconButton
            label="Rifresko regjistrat"
            disabled={loading}
            onClick={() => void refresh()}
          >
            <RefreshCw size={18} />
          </IconButton>
          <IconButton
            label={live ? "Ndalo rifreskimin" : "Aktivizo rifreskimin"}
            onClick={() => setLive(!live)}
          >
            {live ? <Pause size={18} /> : <Play size={18} />}
          </IconButton>
          <IconButton
            label="Shkarko faqen e regjistrave"
            disabled={!data?.events.length}
            onClick={download}
          >
            <Download size={18} />
          </IconButton>
        </div>
      </div>
      <p className="muted">
        Vetëm për Devs. Kontrolloni një lidhje te Burimet e të dhënave për të
        regjistruar rezultatin këtu. Ngjarjet ruhen pa kufi numri dhe nuk
        fshihen automatikisht. Shkarkimi përmban vetëm faqen e shfaqur.
      </p>
      <div className="system-log-filters">
        <label>
          Niveli
          <Select
            aria-label="Niveli i regjistrave"
            value={level}
            onChange={(e) => {
              setLevel(e.target.value);
              setBefore(0);
            }}
            options={[
              { value: "", label: "Të gjitha nivelet" },
              ...Object.entries(levels).map(([value, label]) => ({
                value,
                label,
              })),
            ]}
          />
        </label>
        <label>
          Komponenti
          <Select
            aria-label="Komponenti i regjistrave"
            value={component}
            onChange={(e) => {
              setComponent(e.target.value);
              setBefore(0);
            }}
            options={[
              { value: "", label: "Të gjithë komponentët" },
              ...Object.entries(components).map(([value, label]) => ({
                value,
                label,
              })),
            ]}
          />
        </label>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Koha</th>
              <th>Niveli</th>
              <th>Komponenti / burimi</th>
              <th>Mesazhi</th>
            </tr>
          </thead>
          <tbody>
            {data?.events.map((event) => (
              <tr key={event.id}>
                <td>{new Date(event.created_at).toLocaleString("sq-AL")}</td>
                <td>{levels[event.level] || event.level}</td>
                <td>
                  {components[event.component] || event.component}
                  {event.source_name && <div>{event.source_name}</div>}
                </td>
                <td>
                  {errorMessage(event.message)}
                  <details>
                    <summary>Hollësi</summary>
                    <pre>
                      {JSON.stringify(
                        { event: event.event, ...event.details },
                        null,
                        2,
                      )}
                    </pre>
                  </details>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!data?.events.length && !loading && !error && (
        <p className="muted">Nuk ka ngjarje për këtë filtër.</p>
      )}
      <div className="traffic-pagination">
        <IconButton
          label="Ngjarjet më të fundit"
          disabled={!before}
          onClick={() => setBefore(0)}
        >
          <ArrowLeft size={18} />
        </IconButton>
        <IconButton
          label="Ngjarjet më të vjetra"
          disabled={!data?.next_before || loading}
          onClick={() => setBefore(data?.next_before || 0)}
        >
          <ArrowRight size={18} />
        </IconButton>
      </div>
      <p className="footnote">
        Regjistrat përmbajnë ngjarje të aplikacionit pa kredenciale. Gabimet
        para nisjes së backend-it dhe dalja e plotë e Nginx/systemd kontrollohen
        në terminalin e serverit.
      </p>
    </section>
  );
}
