import { Search } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Eye,
  RefreshCw,
  Pause,
  Play,
  X,
} from "lucide-react";
import { ErrorNotice } from "./ErrorNotice";
import { api } from "./api";
import { Select } from "./Select";
import { IconButton } from "./IconButton";

type Event = {
  id: number;
  created_at: string;
  direction: string;
  action: string;
  status: string;
  correlation_id: string | null;
  user_id: string | null;
  bytes: number;
  duration_ms: number | null;
  detail: Record<string, unknown>;
  has_payload: boolean;
  payload_truncated: boolean;
  payload?: unknown;
};
type Traffic = {
  events: Event[];
  next_before: number | null;
  capacity: number | null;
  summary: {
    direction: string;
    events: number;
    bytes: number;
    errors: number;
  }[];
};
const routes: Record<string, string> = {
  "frontend-backend": "Ndërfaqja → Backend",
  "backend-frontend": "Backend → Ndërfaqja",
  "backend-model": "Backend → Modeli",
  "model-backend": "Modeli → Backend",
  "backend-database": "Backend → Databaza",
  "database-backend": "Databaza → Backend",
  "backend-excel": "Backend → Excel",
  "excel-backend": "Excel → Backend",
};
const statuses: Record<string, string> = {
  started: "Nisur",
  sent: "Dërguar",
  received: "Marrë",
  ok: "Përfunduar",
  error: "Gabim",
  interrupted: "Ndërprerë",
};
const bytes = (value: number) =>
  value < 1024
    ? `${value} B`
    : value < 1024 * 1024
      ? `${(value / 1024).toFixed(1)} KB`
      : `${(value / 1024 / 1024).toFixed(1)} MB`;

export function TrafficPanel({ eventId }: { eventId?: number }) {
  useEffect(() => {
    if (eventId)
      void api<Event>(`/admin/traffic/${eventId}`)
        .then((item) => {
          setSelected(item);
          setLive(false);
        })
        .catch(() => setDetailError("Ngjarja nuk u ngarkua."));
  }, [eventId]);
  const [data, setData] = useState<Traffic | null>(null);
  const [direction, setDirection] = useState("");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setSearch(query), 250);
    return () => clearTimeout(timer);
  }, [query]);
  const [before, setBefore] = useState(0);
  const [live, setLive] = useState(true);
  const [selected, setSelected] = useState<Event | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const detailSerial = useRef(0);
  const detailPanel = useRef<HTMLElement>(null);
  const serial = useRef(0);
  useEffect(() => {
    if (selected) detailPanel.current?.scrollIntoView({ block: "start" });
  }, [selected?.id]);
  async function openEvent(event: Event) {
    const request = ++detailSerial.current;
    setSelected(event);
    setLive(false);
    setDetailLoading(true);
    setDetailError("");
    try {
      const result = await api<Event>(`/admin/traffic/${event.id}`);
      if (request === detailSerial.current) setSelected(result);
    } catch {
      if (request === detailSerial.current)
        setDetailError(
          "Përmbajtja nuk u ngarkua. Kontrolloni lidhjen dhe provoni përsëri.",
        );
    } finally {
      if (request === detailSerial.current) setDetailLoading(false);
    }
  }
  const load = useCallback(async () => {
    const id = ++serial.current;
    setLoading(true);
    try {
      const query = new URLSearchParams({
        direction,
        q: search,
        before: String(before),
        limit: "100",
      });
      const result = await api<Traffic>(`/admin/traffic?${query}`);
      if (id === serial.current) {
        setData(result);
        setError("");
      }
    } catch {
      if (id === serial.current)
        setError("Trafiku nuk u ngarkua. Provoni përsëri.");
    } finally {
      if (id === serial.current) setLoading(false);
    }
  }, [direction, before, search]);
  useEffect(() => {
    let pending = false;
    const refresh = async () => {
      if (pending) return;
      pending = true;
      try {
        await load();
      } finally {
        pending = false;
      }
    };
    void refresh();
    const timer = live ? setInterval(() => void refresh(), 2000) : undefined;
    return () => {
      clearInterval(timer);
      serial.current++;
    };
  }, [load, live]);
  const summary = data?.summary || [];
  const total = summary.reduce((sum, row) => sum + row.events, 0);
  return (
    <section className="traffic-panel">
      <div className="stats-grid">
        {[
          ["Mesazhe të regjistruara", total.toLocaleString("sq-AL")],
          ["Gabime", summary.reduce((sum, row) => sum + row.errors, 0)],
          [
            "Madhësia e mesazheve",
            bytes(summary.reduce((sum, row) => sum + row.bytes, 0)),
          ],
          ["Rrugë aktive", summary.length],
        ].map(([title, value]) => (
          <div className="stat-card" key={title}>
            <span>{title}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </div>
      <section className="panel">
        <div className="panel-heading traffic-controls">
          <div>
            <h3>Trafiku i aplikacionit</h3>
            <p>
              Ruhet e gjithë historia e trafikut, pa kufi prej 10.000 mesazhesh.
              Shfletoni faqet për mesazhet më të vjetra.
            </p>
          </div>
          <label className="traffic-search">
            <Search size={16} />
            <input
              type="search"
              aria-label="Kërko në trafik"
              placeholder="Kërko veprime, gabime, mesazhe…"
              value={query}
              maxLength={200}
              onChange={(event) => {
                setQuery(event.target.value);
                setBefore(0);
              }}
            />
          </label>
          <div className="traffic-actions">
            <Select
              aria-label="Rruga e trafikut"
              value={direction}
              onChange={(e) => {
                setDirection(e.target.value);
                setBefore(0);
              }}
              options={[
                { value: "", label: "Të gjitha rrugët" },
                ...Object.entries(routes).map(([value, label]) => ({
                  value,
                  label,
                })),
              ]}
            />
            <IconButton
              label={live ? "Ndalo rifreskimin" : "Nis rifreskimin"}
              aria-pressed={live}
              onClick={() => {
                setLive(!live);
                if (!live) setBefore(0);
              }}
            >
              {live ? <Pause size={15} /> : <Play size={15} />}
            </IconButton>
            <IconButton
              label="Rifresko trafikun"
              onClick={() => void load()}
              disabled={loading}
            >
              <RefreshCw size={18} className={loading ? "spin" : ""} />
            </IconButton>
          </div>
        </div>
        <p className="traffic-note">
          Ndërfaqja komunikon me modelin përmes backend-it. Këtu shfaqen
          kërkesat dhe përgjigjet HTTP, mesazhet e modelit, thirrjet e mjeteve,
          pyetjet SQL dhe kontrolli i Excel-it. Hapni një ngjarje për
          përmbajtjen. Kredencialet, tokenët, hyrja dhe konfigurimi i lidhjeve
          përjashtohen. Pamjet e përmbajtjes kufizohen në 64 KB, 100 elemente
          për listë dhe 20 000 karaktere për tekst; skedarët binarë nuk
          regjistrohen.
        </p>
        {error && <ErrorNotice onDismiss={() => setError("")}>{error}</ErrorNotice>}
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Koha</th>
                <th>Rruga</th>
                <th>Veprimi</th>
                <th>Gjendja</th>
                <th>Madhësia</th>
                <th>Kohëzgjatja</th>
                <th>Detaje</th>
              </tr>
            </thead>
            <tbody>
              {data?.events.map((event) => (
                <tr
                  key={event.id}
                  className={event.status === "error" ? "traffic-error" : ""}
                >
                  <td>
                    {new Date(event.created_at).toLocaleTimeString("sq-AL", {
                      timeZone: "Europe/Tirane",
                    })}
                  </td>
                  <td>{routes[event.direction]}</td>
                  <td className="traffic-action">{event.action}</td>
                  <td>{statuses[event.status] || event.status}</td>
                  <td>{bytes(event.bytes)}</td>
                  <td>
                    {event.duration_ms == null
                      ? "—"
                      : `${event.duration_ms.toLocaleString("sq-AL")} ms`}
                  </td>
                  <td>
                    <IconButton
                      label={`Hap detajet e mesazhit #${event.id}`}
                      onClick={() => void openEvent(event)}
                    >
                      <Eye size={18} />
                    </IconButton>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!data?.events.length && (
          <p className="traffic-note">
            {loading
              ? "Duke ngarkuar trafikun…"
              : "Nuk ka mesazhe për këtë filtër. Nisni një bisedë ose kontrolloni lidhjen me databazën."}
          </p>
        )}
        <div className="traffic-pagination">
          {!!before && (
            <IconButton
              label="Më të fundit"
              onClick={() => {
                setBefore(0);
                setLive(true);
              }}
            >
              <ArrowLeft size={18} />
            </IconButton>
          )}
          <IconButton
            label="Më të vjetra"
            disabled={!data?.next_before || loading}
            onClick={() => {
              setBefore(data!.next_before!);
              setLive(false);
            }}
          >
            <ArrowRight size={18} />
          </IconButton>
          <span>
            {live
              ? "Rifreskim automatik çdo 2 sekonda"
              : "Rifreskimi është ndalur"}
          </span>
        </div>
      </section>
      {selected && (
        <section className="panel traffic-detail" ref={detailPanel}>
          <div className="panel-heading">
            <h3>Detajet e mesazhit #{selected.id}</h3>
            <button
              className="icon-button"
              aria-label="Mbyll detajet"
              data-tooltip="Mbyll detajet"
              onClick={() => {
                detailSerial.current++;
                setSelected(null);
              }}
            >
              <X size={18} />
            </button>
          </div>
          <p>
            {routes[selected.direction]} · {selected.action} ·{" "}
            {new Date(selected.created_at).toLocaleString("sq-AL", {
              timeZone: "Europe/Tirane",
            })}
          </p>
          <h4>Përmbajtja e kërkesës / përgjigjes</h4>
          {detailLoading ? (
            <p role="status">Duke ngarkuar përmbajtjen…</p>
          ) : detailError ? (
            <ErrorNotice onDismiss={() => setDetailError("")}>
              {detailError}
            </ErrorNotice>
          ) : selected.payload == null ? (
            <p>
              Kjo ngjarje ka vetëm metadata. Përmbajtja nuk ishte regjistruar;
              ngjarjet e reja do ta përmbajnë kur lejohet.
            </p>
          ) : (
            <>
              {!!selected.payload_truncated && (
                <p className="notice">
                  Shfaqet një pamje e kufizuar e përmbajtjes. Të dhënat
                  origjinale të bisedës dhe raportit nuk ndryshojnë.
                </p>
              )}
              <pre className="traffic-payload">
                {JSON.stringify(selected.payload, null, 2)}
              </pre>
            </>
          )}
          <details>
            <summary>Metadata dhe identifikuesit e lidhjes</summary>
            <pre>
              {JSON.stringify(
                {
                  correlation_id: selected.correlation_id,
                  user_id: selected.user_id,
                  ...selected.detail,
                },
                null,
                2,
              )}
            </pre>
          </details>
        </section>
      )}
    </section>
  );
}
