import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import {
  ArrowDown,
  ArrowUp,
  Plug,
  Plus,
  RotateCcw,
  Unplug,
  X,
} from "lucide-react";
import { api } from "./api";
import type { Login, Provider } from "./types";
import { Select } from "./Select";
import { IconButton } from "./IconButton";

type Account = {
  id: string;
  provider: Provider;
  label: string;
  position: number;
  enabled: number;
  connected: boolean;
  account?: { email?: string };
  login?: Login;
  unavailable_reason?: string;
  retry_at?: number;
  error?: string;
};

export function SubscriptionAccounts({
  onChange,
}: {
  onChange: () => Promise<unknown>;
}) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [login, setLogin] = useState<
    (Login & { subscription_id: string }) | null
  >(null);
  const [code, setCode] = useState("");

  async function refresh() {
    setAccounts(await api<Account[]>("/admin/subscriptions"));
  }
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const next = await api<Account[]>("/admin/subscriptions");
        if (!alive) return;
        setAccounts(next);
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
    };
    void poll();
    const timer = setInterval(() => void poll(), login ? 2000 : 30000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [login?.subscription_id]);
  useEffect(() => {
    if (!login) return;
    const result = accounts.find((a) => a.id === login.subscription_id);
    if (result?.connected) {
      setLogin(null);
      void onChange().catch((e) => setError((e as Error).message));
    } else if (result?.login?.status === "failed") {
      setError(result.login.error || "Hyrja nuk përfundoi.");
      setLogin(null);
    }
  }, [accounts, login?.subscription_id]);

  async function action(callback: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await callback();
      await refresh();
      await onChange();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const values = new FormData(e.currentTarget);
    await action(async () => {
      await api("/admin/subscriptions", {
        method: "POST",
        body: JSON.stringify({
          provider: values.get("provider"),
          label: values.get("label"),
        }),
      });
      setAdding(false);
    });
  }

  return (
    <div className="subscription-accounts">
      <div className="panel-heading">
        <h3>Abonimet e përbashkëta</h3>
        <IconButton label="Shto abonim" onClick={() => setAdding(true)}>
          <Plus size={18} />
        </IconButton>
      </div>
      <p className="footnote">
        Kur arrihet kufiri, provohet abonimi tjetër i të njëjtit ofrues, pastaj
        ofruesi tjetër. Kalimi te Claude përdor Opus 5.5. Konteksti ruhet
        automatikisht; pa një abonim të përdorshëm, përgjigjja ndalet me një
        mesazh gabimi.
      </p>
      {error && (
        <p role="alert" className="error-box">
          {error}
        </p>
      )}
      {(["chatgpt", "claude"] as Provider[]).map((provider) => (
        <section
          className="panel"
          key={provider}
          aria-label={`Abonimet ${provider === "chatgpt" ? "ChatGPT" : "Claude"}`}
        >
          <h3>{provider === "chatgpt" ? "ChatGPT" : "Claude"}</h3>
          {accounts
            .filter((a) => a.provider === provider)
            .map((account, index, group) => (
              <div className="subscription-account" key={account.id}>
                <div className="subscription-account-details">
                  <strong>
                    {index + 1}. {account.label}
                  </strong>
                  <span>{account.account?.email || "Llogari e palidhur"}</span>
                  <small>
                    {!account.enabled
                      ? "E çaktivizuar"
                      : account.unavailable_reason
                        ? "Kufiri u arrit / lidhja duhet kontrolluar"
                        : account.connected
                          ? "E lidhur"
                          : account.login?.status === "pending"
                            ? "Hyrja në proces"
                            : "E palidhur"}
                  </small>
                  {account.retry_at && account.retry_at > Date.now() / 1000 && (
                    <small>
                      Provohet pas{" "}
                      {new Date(account.retry_at * 1000).toLocaleString(
                        "sq-AL",
                      )}
                    </small>
                  )}
                  {account.error && <small>{account.error}</small>}
                </div>
                <div className="subscription-account-actions">
                  <label className="checkbox">
                    <input
                      type="checkbox"
                      aria-label={`Aktivizo ${account.label}`}
                      checked={!!account.enabled}
                      disabled={busy}
                      onChange={(e) =>
                        void action(() =>
                          api(`/admin/subscriptions/${account.id}`, {
                            method: "PATCH",
                            body: JSON.stringify({ enabled: e.target.checked }),
                          }),
                        )
                      }
                    />{" "}
                    Aktive
                  </label>
                  <IconButton
                    label={`${account.connected ? "Shkëput" : "Lidh"} abonimin: ${account.label}`}
                    disabled={busy}
                    onClick={() =>
                      void action(async () => {
                        if (account.connected) {
                          await api(
                            `/admin/subscriptions/${account.id}/disconnect`,
                            { method: "POST" },
                          );
                        } else {
                          setCode("");
                          setLogin(
                            await api(
                              `/admin/subscriptions/${account.id}/login`,
                              { method: "POST" },
                            ),
                          );
                        }
                      })
                    }
                  >
                    {account.connected ? (
                      <Unplug size={18} />
                    ) : (
                      <Plug size={18} />
                    )}
                  </IconButton>
                  {account.unavailable_reason && (
                    <IconButton
                      label={`Provo përsëri: ${account.label}`}
                      disabled={busy}
                      onClick={() =>
                        void action(() =>
                          api(`/admin/subscriptions/${account.id}/retry`, {
                            method: "POST",
                          }),
                        )
                      }
                    >
                      <RotateCcw size={18} />
                    </IconButton>
                  )}
                  {[-1, 1].map((direction) => (
                    <IconButton
                      key={direction}
                      label={`${direction < 0 ? "Ngri" : "Ul"} ${account.label}`}
                      disabled={busy || !group[index + direction]}
                      onClick={() =>
                        void action(async () => {
                          const ordered = [...group];
                          [ordered[index], ordered[index + direction]] = [
                            ordered[index + direction],
                            ordered[index],
                          ];
                          await api("/admin/subscription-order", {
                            method: "POST",
                            body: JSON.stringify({
                              provider,
                              account_ids: ordered.map((item) => item.id),
                            }),
                          });
                        })
                      }
                    >
                      {direction < 0 ? (
                        <ArrowUp size={18} />
                      ) : (
                        <ArrowDown size={18} />
                      )}
                    </IconButton>
                  ))}
                </div>
              </div>
            ))}
        </section>
      ))}
      {adding && (
        <div className="modal-scrim">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label="Shto abonim"
          >
            <div className="modal-title">
              <h2>Shto abonim</h2>
              <button
                className="icon-button"
                aria-label="Mbyll dritaren"
                onClick={() => setAdding(false)}
              >
                <X size={20} />
              </button>
            </div>
            <form onSubmit={(e) => void add(e)}>
              <label>
                Ofruesi
                <Select name="provider" aria-label="Ofruesi">
                  <option value="chatgpt">ChatGPT</option>
                  <option value="claude">Claude</option>
                </Select>
              </label>
              <label>
                Emri i abonimit
                <input
                  name="label"
                  required
                  maxLength={100}
                  placeholder="p.sh. ChatGPT 2"
                />
              </label>
              <p className="footnote">
                Pas ruajtjes, përdorni Lidh për t’u identifikuar me abonimin
                përkatës.
              </p>
              <button className="button primary" disabled={busy}>
                Ruaj
              </button>
            </form>
          </section>
        </div>
      )}
      {login && (
        <div className="modal-scrim">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label="Lidh abonimin"
          >
            <div className="modal-title">
              <h2>Lidh abonimin</h2>
              <button
                className="icon-button"
                aria-label="Mbyll dritaren"
                onClick={() => setLogin(null)}
              >
                <X size={20} />
              </button>
            </div>
            <p>
              Hyni me llogarinë që dëshironi të regjistroni për këtë abonim.
            </p>
            {login.verificationUrl && (
              <a
                className="button primary"
                href={login.verificationUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                Hap faqen e hyrjes
              </a>
            )}
            {login.userCode && (
              <p>
                Kodi i pajisjes: <strong>{login.userCode}</strong>
              </p>
            )}
            {login.requiresCode && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void action(async () => {
                    await api(
                      `/admin/subscriptions/${login.subscription_id}/login/code`,
                      {
                        method: "POST",
                        body: JSON.stringify({ login_id: login.loginId, code }),
                      },
                    );
                    setCode("");
                  });
                }}
              >
                <label>
                  Kodi i autorizimit
                  <input
                    autoComplete="off"
                    type="password"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    required
                  />
                </label>
                <button className="button primary" disabled={busy}>
                  Përfundo lidhjen
                </button>
              </form>
            )}
            <p className="footnote">
              Kjo dritare përditësohet automatikisht kur hyrja përfundon.
            </p>
          </section>
        </div>
      )}
    </div>
  );
}
