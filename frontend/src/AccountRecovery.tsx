import { useState } from "react";
import type { FormEvent } from "react";
import { ErrorNotice } from "./ErrorNotice";
import { api } from "./api";
import { errorMessage } from "./locale";
import type { User } from "./types";

export function RecoveryForm({ onBack }: { onBack: () => void }) {
  return (
    <div className="auth-page">
      <section className="auth-card">
        <h1>Ndihmë për hyrjen</h1>
        <p>
          Fjalëkalimet menaxhohen vetëm nga administratorët e kompanisë.
          Kontaktoni IT-në ose administratorin Devs për rivendosjen e
          fjalëkalimit.
        </p>
        <button type="button" className="text-button" onClick={onBack}>
          Kthehu te hyrja
        </button>
      </section>
    </div>
  );
}

export function MemberRecovery({ member }: { member: User }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    const password = data.get("password");
    if (password !== data.get("confirm_password")) {
      setError("Fjalëkalimet nuk përputhen.");
      return;
    }
    setBusy(true);
    setError("");
    setDone(false);
    try {
      await api(`/admin/users/${member.id}/password`, {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      form.reset();
      setDone(true);
    } catch (e) {
      setError(errorMessage((e as Error).message));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="account-password-form" onSubmit={submit}>
      <p>
        Vendosni fjalëkalimin e ri për {member.email}. Seancat dhe puna në
        proces e këtij anëtari do të mbyllen. Qasja në databaza dhe raportet e
        ruajtura ruhen.
      </p>
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
        Përsërit fjalëkalimin
        <input
          name="confirm_password"
          type="password"
          required
          minLength={12}
          maxLength={256}
          autoComplete="new-password"
        />
      </label>
      {error && <ErrorNotice onDismiss={() => setError("")}>{error}</ErrorNotice>}
      {done && (
        <p role="status">
          Fjalëkalimi u rivendos. Jepjani privatisht anëtarit.
        </p>
      )}
      <button className="button primary" disabled={busy}>
        {busy ? "Duke ruajtur…" : "Rivendos fjalëkalimin"}
      </button>
    </form>
  );
}
