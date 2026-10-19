import { useState } from "react";
import type { FormEvent } from "react";
import { api } from "./api";
import type { User } from "./types";

export function PasswordChangeForm() {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const values = Object.fromEntries(new FormData(form));
    setError("");
    setMessage("");
    if (values.new_password !== values.confirm_password) {
      setError("Fjalëkalimet e reja nuk përputhen.");
      return;
    }
    setBusy(true);
    try {
      await api("/auth/password", {
        method: "POST",
        body: JSON.stringify({
          current_password: values.current_password,
          new_password: values.new_password,
        }),
      });
      form.reset();
      setMessage("Fjalëkalimi u ndryshua. Seancat e tjera u mbyllën.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="account-password-form" onSubmit={submit}>
      <h3>Ndrysho fjalëkalimin</h3>
      <p>
        Ruani punën përpara ndryshimit. Përgjigjet dhe raportet në proces do të
        ndalen dhe seancat e tjera do të mbyllen.
      </p>
      <label>
        Fjalëkalimi aktual
        <input
          name="current_password"
          type="password"
          required
          autoComplete="current-password"
          maxLength={256}
        />
      </label>
      <label>
        Fjalëkalimi i ri
        <input
          name="new_password"
          type="password"
          required
          minLength={12}
          maxLength={256}
          autoComplete="new-password"
        />
      </label>
      <label>
        Përsërit fjalëkalimin e ri
        <input
          name="confirm_password"
          type="password"
          required
          minLength={12}
          maxLength={256}
          autoComplete="new-password"
        />
      </label>
      {error && (
        <p className="error-box" role="alert">
          {error}
        </p>
      )}
      {message && <p role="status">{message}</p>}
      <button className="button primary" disabled={busy}>
        {busy ? "Duke ruajtur…" : "Ruaj fjalëkalimin"}
      </button>
    </form>
  );
}

export function RecoveryForm({ onBack }: { onBack: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const values = Object.fromEntries(new FormData(form));
    if (values.password !== values.confirm_password) {
      setError("Fjalëkalimet e reja nuk përputhen.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api("/auth/password-reset", {
        method: "POST",
        body: JSON.stringify({
          email: values.email,
          token: values.token,
          password: values.password,
        }),
      });
      form.reset();
      setDone(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="auth-page">
      <section className="auth-card">
        <h1>Rikupero llogarinë</h1>
        {done ? (
          <p role="status">
            Fjalëkalimi u rivendos. Hyni me fjalëkalimin e ri.
          </p>
        ) : (
          <>
            <p>
              Kërkojini Devs një kod rikuperimi. Kodi përdoret vetëm një herë
              dhe skadon pas 30 minutash.
            </p>
            <form onSubmit={submit}>
              <label>
                Adresa e emailit
                <input
                  name="email"
                  type="email"
                  required
                  autoComplete="username"
                />
              </label>
              <label>
                Kodi i rikuperimit
                <input
                  name="token"
                  required
                  autoComplete="off"
                  maxLength={256}
                />
              </label>
              <label>
                Fjalëkalimi i ri
                <input
                  name="password"
                  type="password"
                  required
                  minLength={12}
                  maxLength={256}
                  autoComplete="new-password"
                />
              </label>
              <label>
                Përsërit fjalëkalimin e ri
                <input
                  name="confirm_password"
                  type="password"
                  required
                  minLength={12}
                  maxLength={256}
                  autoComplete="new-password"
                />
              </label>
              {error && (
                <p className="error-box" role="alert">
                  {error}
                </p>
              )}
              <button className="button primary wide" disabled={busy}>
                {busy ? "Duke ruajtur…" : "Rivendos fjalëkalimin"}
              </button>
            </form>
          </>
        )}
        <button
          type="button"
          className="text-button"
          onClick={onBack}
          disabled={busy}
        >
          Kthehu te hyrja
        </button>
      </section>
    </div>
  );
}

export function MemberRecovery({ member }: { member: User }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<{
    token: string;
    expires_at: number;
  } | null>(null);
  async function issue() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      setResult(
        await api(`/admin/users/${member.id}/password-reset`, {
          method: "POST",
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="account-password-form">
      <p>
        Krijoni një kod rikuperimi për {member.email} dhe jepjani privatisht
        anëtarit. Kodi i mëparshëm bëhet i pavlefshëm. Qasja në databaza dhe
        kompani ruhet.
      </p>
      {error && (
        <p className="error-box" role="alert">
          {error}
        </p>
      )}
      {result && (
        <>
          <label>
            Kodi i rikuperimit
            <input
              readOnly
              value={result.token}
              onFocus={(e) => e.target.select()}
            />
          </label>
          <p role="status">
            Skadon më{" "}
            {new Date(result.expires_at * 1000).toLocaleString("sq-AL")}.
            Anëtari zgjedh “Harrova fjalëkalimin” te hyrja.
          </p>
        </>
      )}
      <button
        className="button primary"
        onClick={() => void issue()}
        disabled={busy}
      >
        {busy
          ? "Duke krijuar…"
          : result
            ? "Krijo kod të ri"
            : "Krijo kod rikuperimi"}
      </button>
    </div>
  );
}
