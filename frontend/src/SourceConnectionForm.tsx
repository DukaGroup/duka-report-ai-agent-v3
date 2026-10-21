import type { FormEvent } from "react";
import {
  Check,
  Database,
  LoaderCircle,
  Pencil,
  ShieldCheck,
  X,
} from "lucide-react";
import { Select } from "./Select";
import type { Source } from "./types";

type Props = {
  source: Source | null;
  kind: string;
  summary: boolean;
  discovery: boolean;
  saving: boolean;
  onKindChange: (kind: string) => void;
  onEdit: () => void;
  onCancelEdit: () => void;
  onDiscoveryChange: (checked: boolean) => void;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
};
const fieldLabels: Record<string, string> = {
  HOST: "Adresa e serverit",
  PORT: "Porti",
  USER: "Përdoruesi",
  PASSWORD: "Fjalëkalimi",
  DATABASE: "Databaza",
};

export function SourceConnectionForm({
  source,
  kind,
  summary,
  discovery,
  saving,
  onKindChange,
  onEdit,
  onCancelEdit,
  onDiscoveryChange,
  onClose,
  onSubmit,
}: Props) {
  const hana = kind === "saphana",
    prefix = hana ? "HANA" : "SQLSERVER";
  const supported = hana || kind === "sqlserver";
  const changingKind = !!source && source.kind !== kind;
  const keepFields = !!source;
  function field(name: string) {
    const port = name === "PORT",
      password = name === "PASSWORD";
    return (
      <label key={name}>
        {fieldLabels[name]}
        <input
          name={prefix + "_" + name}
          type={password ? "password" : port ? "number" : "text"}
          required={!keepFields || (port && changingKind)}
          min={port ? 1 : undefined}
          max={port ? 65535 : undefined}
          maxLength={password ? 1024 : 255}
          autoComplete={password ? "new-password" : "off"}
          defaultValue={port && !source ? (hana ? "30015" : "1433") : ""}
          placeholder={
            keepFields
              ? port
                ? "Pa ndryshim"
                : "Bosh = pa ndryshim"
              : port
                ? hana
                  ? "P.sh. 30015 ose 443"
                  : "1433"
                : name === "HOST"
                  ? "Emri DNS ose adresa IP"
                  : name === "USER"
                    ? "Përdoruesi i raporteve"
                    : "Fjalëkalimi"
          }
        />
      </label>
    );
  }
  return (
    <form className="source-config-form" onSubmit={onSubmit}>
      <div className="source-config-meta">
        <label>
          Emri i lidhjes
          <input
            name="name"
            required
            maxLength={120}
            defaultValue={source?.name || ""}
            placeholder="P.sh. GoTech ose Financë"
          />
        </label>
        <label>
          Lloji i databazës
          <Select
            name="kind"
            value={kind}
            disabled={
              summary ||
              (!!source && !["sqlserver", "saphana"].includes(source.kind))
            }
            onChange={(e) => onKindChange(e.target.value)}
          >
            {Object.entries({
              sqlserver: "SQL Server",
              saphana: "SAP HANA",
              postgresql: "PostgreSQL",
              mysql: "MySQL",
              sqlite: "SQLite",
              other: "Tjetër",
            }).map(([value, title]) => (
              <option key={value} value={value}>
                {title}
              </option>
            ))}
          </Select>
        </label>
      </div>
      {supported ? (
        <fieldset className="source-connection-fields" key={kind}>
          <legend>
            <Database size={17} />{" "}
            {hana ? "Lidhja SAP HANA" : "Lidhja SQL Server"}
          </legend>
          {summary ? (
            <>
              <div className="source-config-summary">
                <ShieldCheck size={22} aria-hidden="true" />
                <div>
                  <strong>Konfigurimi i lidhjes</strong>
                  <p>Kredencialet mbeten private në server.</p>
                </div>
                <button
                  type="button"
                  className="button outline small"
                  onClick={onEdit}
                  disabled={saving}
                >
                  <Pencil size={16} />
                  Ndrysho konfigurimin
                </button>
              </div>
              <dl className="source-config-status">
                {["HOST", "PORT", "USER", "PASSWORD", "DATABASE"].map(
                  (name) => {
                    const present =
                      !!source?.connection_fields?.[prefix + "_" + name];
                    return (
                      <div key={name}>
                        <dt>
                          {fieldLabels[name]}
                          <code>
                            {prefix}_{name}
                          </code>
                        </dt>
                        <dd>
                          <span
                            className={`badge ${present || name === "DATABASE" ? "good" : ""}`}
                          >
                            <span />
                            {present
                              ? "E konfiguruar"
                              : name === "DATABASE"
                                ? "Zbulim automatik"
                                : "Nuk është vendosur"}
                          </span>
                        </dd>
                      </div>
                    );
                  },
                )}
              </dl>
              {hana && (
                <div
                  className="source-tls-summary"
                  aria-label="Siguria e lidhjes"
                >
                  <span>
                    <ShieldCheck size={16} />
                    {source?.tls?.encrypt === false
                      ? "TLS i çaktivizuar"
                      : "TLS i aktivizuar"}
                  </span>
                  <span>
                    {source?.tls?.validate_certificate === false
                      ? "Pa verifikim certifikate"
                      : "Certifikata verifikohet"}
                  </span>
                  <span>
                    {source?.tls?.custom_ca ? "CA e ruajtur" : "CA e sistemit"}
                  </span>
                  {source?.tls?.server_name_configured && (
                    <span>Emri DNS i ruajtur</span>
                  )}
                </div>
              )}
            </>
          ) : (
            <>
              <div className="source-edit-intro">
                <p className="source-form-help">
                  {keepFields
                    ? "Plotësoni vetëm vlerat që doni të ndryshoni. Fushat bosh ruajnë vlerat aktuale."
                    : "Vendosni të dhënat e lidhjes. Kredencialet ruhen privatisht në server."}
                </p>
                {source && (
                  <button
                    type="button"
                    className="button outline small"
                    onClick={onCancelEdit}
                    disabled={saving}
                  >
                    <X size={15} />
                    Anulo ndryshimet e lidhjes
                  </button>
                )}
              </div>
              {changingKind && (
                <p className="source-form-help">
                  Vendosni portin SQL të llojit të ri. Databaza parazgjedhje
                  pastrohet për zbulim automatik.
                </p>
              )}
              <div className="source-fields-grid source-host-row">
                {field("HOST")}
                {field("PORT")}
              </div>
              <div className="source-fields-grid">
                {field("USER")}
                {field("PASSWORD")}
              </div>
              <div className="source-database-section">
                <label className="source-discovery-option">
                  <input
                    type="checkbox"
                    checked={discovery}
                    onChange={(e) => onDiscoveryChange(e.target.checked)}
                  />
                  Zbulo automatikisht databazat
                </label>
                {!discovery && (
                  <label>
                    {hana ? "Databaza tenant" : "Databaza parazgjedhje"}
                    <span className="source-optional">Opsionale</span>
                    <input
                      name={prefix + "_DATABASE"}
                      maxLength={128}
                      autoComplete="off"
                      placeholder={
                        keepFields ? "Bosh = pa ndryshim" : "Emri i databazës"
                      }
                    />
                  </label>
                )}
                <p className="source-form-help">
                  {discovery
                    ? "Zbulohen databazat që lejon përdoruesi i lidhjes."
                    : hana
                      ? "Vendosni emrin e tenant-it, jo skemën e kompanisë."
                      : "Bosh për zbulim automatik në një lidhje të re."}
                </p>
              </div>
              {hana && (
                <div className="source-security-section">
                  <div className="source-section-heading">
                    <ShieldCheck size={17} />
                    <strong>Siguria e lidhjes</strong>
                  </div>
                  <div className="source-fields-grid">
                    <label>
                      Kriptimi TLS
                      <Select
                        name="HANA_ENCRYPT"
                        aria-label="Kriptimi TLS"
                        defaultValue={
                          source?.tls?.encrypt === false ? "false" : "true"
                        }
                      >
                        <option value="true">I aktivizuar</option>
                        <option value="false">I çaktivizuar</option>
                      </Select>
                    </label>
                    <label>
                      Verifikimi i certifikatës
                      <Select
                        name="HANA_VALIDATE_CERTIFICATE"
                        aria-label="Verifikimi i certifikatës"
                        defaultValue={
                          source?.tls?.validate_certificate === false
                            ? "false"
                            : "true"
                        }
                      >
                        <option value="true">Verifiko certifikatën</option>
                        <option value="false">Pa verifikim</option>
                      </Select>
                    </label>
                  </div>
                  <details className="source-certificate-options">
                    <summary>
                      Certifikata CA dhe emri DNS <span>Opsionale</span>
                    </summary>
                    <div className="source-certificate-fields">
                      <label>
                        Certifikata CA e besuar (PEM)
                        <textarea
                          name="HANA_TLS_CA_CERTIFICATE"
                          rows={4}
                          maxLength={65536}
                          autoComplete="off"
                          spellCheck={false}
                          placeholder={
                            source?.tls?.custom_ca
                              ? "Certifikata është ruajtur. Bosh = pa ndryshim."
                              : "-----BEGIN CERTIFICATE-----\nCertifikata nga administratori SAP HANA\n-----END CERTIFICATE-----"
                          }
                        />
                      </label>
                      <label>
                        Emri DNS në certifikatën e serverit
                        <input
                          name="HANA_TLS_SERVER_NAME"
                          maxLength={253}
                          autoComplete="off"
                          placeholder={
                            source?.tls?.server_name_configured
                              ? "Emri është ruajtur. Bosh = pa ndryshim."
                              : "P.sh. hana.company.internal"
                          }
                        />
                      </label>
                      <p className="source-form-help">
                        Merren nga administratori SAP HANA. Mos vendosni çelësa
                        privatë.
                      </p>
                    </div>
                  </details>
                </div>
              )}
              {hana && (
                <p className="source-form-help">
                  Përdorni portin SQL të HANA. HANA Cloud zakonisht përdor 443
                  dhe TLS.
                </p>
              )}
            </>
          )}
          <div className="source-config-privacy">
            <p>Kredencialet ruhen në .env dhe nuk i dërgohen modelit.</p>
            {source?.env_prefix && (
              <p>
                Profili: <code>{source.env_prefix}</code>
              </p>
            )}
          </div>
        </fieldset>
      ) : (
        <p className="source-form-help">
          Ky lloj databaze mund të përcaktohet, por lidhja e tij nuk është
          implementuar ende.
        </p>
      )}
      <label>
        Përshkrimi <span className="source-optional">Opsionale</span>
        <textarea
          name="description"
          rows={2}
          defaultValue={source?.description || ""}
          placeholder="Çfarë të dhënash ofron ky burim?"
        />
      </label>
      <div className="source-config-footer">
        <button
          type="button"
          className="button outline"
          disabled={saving}
          onClick={onClose}
        >
          Anulo
        </button>
        <button className="button primary" disabled={saving}>
          {saving ? (
            <LoaderCircle size={17} className="spin" />
          ) : (
            <Check size={17} />
          )}
          {saving ? "Duke ruajtur…" : source ? "Ruaj lidhjen" : "Shto lidhjen"}
        </button>
      </div>
    </form>
  );
}
