import { useEffect, useState } from "react";
import { api } from "./api";
import { SERVICE_UNAVAILABLE } from "./locale";

type Version = {
  id: string;
  created_at: string;
  message_count: number;
  preview: string;
};
export function ChatVersions({
  id,
  onRestore,
  technical = false,
}: {
  id: string;
  onRestore: () => Promise<void>;
  // Devs see the actual error; everyone else one calm message.
  technical?: boolean;
}) {
  const [versions, setVersions] = useState<Version[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [selected, setSelected] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    api<Version[]>(`/conversations/${id}/versions`)
      .then((v) => {
        if (active) setVersions(v);
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [id]);
  async function restore() {
    if (!selected || saving) return;
    setSaving(true);
    setError("");
    try {
      await api(`/conversations/${id}/versions/${selected}/restore`, {
        method: "POST",
      });
      await onRestore();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  return (
    <section className="chat-versions">
      <p>
        Riktheni një version të ruajtur para redaktimit. Biseda aktuale ruhet
        gjithashtu si version, që të mund të ktheheni sërish.
      </p>
      {loading && <p role="status">Duke ngarkuar versionet…</p>}
      {!loading && !versions.length && (
        <p>Nuk ka ende versione të mëparshme.</p>
      )}
      {versions.map((v, i) => (
        <label className="version-choice" key={v.id}>
          <input
            type="radio"
            name="chat-version"
            disabled={saving}
            checked={selected === v.id}
            onChange={() => setSelected(v.id)}
          />
          <span>
            <strong>
              Versioni {versions.length - i} · {v.message_count} mesazhe
            </strong>
            <small>{new Date(v.created_at).toLocaleString("sq-AL")}</small>
            <p>{v.preview}</p>
          </span>
        </label>
      ))}
      {error && (
        <p role="alert" className="error-box">
          {technical ? error : SERVICE_UNAVAILABLE}
        </p>
      )}
      {!!versions.length && (
        <button
          className="button primary"
          disabled={!selected || saving}
          onClick={() => void restore()}
        >
          {saving ? "Duke rikthyer…" : "Rikthe versionin"}
        </button>
      )}
    </section>
  );
}
