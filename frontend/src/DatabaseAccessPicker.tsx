import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { errorMessage, SERVICE_UNAVAILABLE } from "./locale";
import { ChevronDown, ChevronUp } from "lucide-react";

export type DatabaseGrant = {
  source_id: string;
  database: string;
  all_companies: boolean;
  company_ids: string[];
};
export type MemberDataAccess = {
  databases: DatabaseGrant[];
  preserve_legacy_source_ids: string[];
};
export const emptyDataAccess = (): MemberDataAccess => ({
  databases: [],
  preserve_legacy_source_ids: [],
});
type SourceCatalog = {
  id: string;
  name: string;
  databases: { name: string }[];
  error?: string;
  catalog_complete: boolean;
};
type CompanyCatalog = {
  companies: { id: string; name: string; schema: string }[];
  warnings: string[];
  note?: string;
};

function GrantCheck({
  partial = false,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement> & { partial?: boolean }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = partial;
  }, [partial]);
  return <input {...props} ref={ref} type="checkbox" />;
}

export function DatabaseAccessPicker({
  value,
  onChange,
  allAccess = false,
  disabled = false,
  technical = false,
}: {
  value: MemberDataAccess;
  onChange: (value: MemberDataAccess) => void;
  allAccess?: boolean;
  disabled?: boolean;
  // Devs see the actual errors; Presidents one calm message.
  technical?: boolean;
}) {
  const shown = (text: string) => (technical ? text : SERVICE_UNAVAILABLE);
  const [sources, setSources] = useState<SourceCatalog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [companies, setCompanies] = useState<Record<string, CompanyCatalog>>(
    {},
  );
  const [companySearch, setCompanySearch] = useState<Record<string, string>>(
    {},
  );
  const [companyErrors, setCompanyErrors] = useState<Record<string, string>>(
    {},
  );
  const [companyLoading, setCompanyLoading] = useState<Record<string, boolean>>(
    {},
  );
  const key = (source: string, database: string) =>
    JSON.stringify([source, database]);
  useEffect(() => {
    let active = true;
    api<{ sources: SourceCatalog[] }>("/admin/access-catalog")
      .then((result) => {
        if (active) setSources(result.sources);
      })
      .catch((e) => {
        if (active) setError(errorMessage(e.message));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);
  const legacy = (id: string) => value.preserve_legacy_source_ids.includes(id);
  const selected = (source: string, database: string) =>
    value.databases.find(
      (g) => g.source_id === source && g.database === database,
    ) ||
    (legacy(source)
      ? { source_id: source, database, all_companies: true, company_ids: [] }
      : undefined);
  function materialize(source: SourceCatalog): MemberDataAccess {
    return legacy(source.id)
      ? {
          databases: [
            ...value.databases.filter((g) => g.source_id !== source.id),
            ...source.databases.map((d) => ({
              source_id: source.id,
              database: d.name,
              all_companies: true,
              company_ids: [],
            })),
          ],
          preserve_legacy_source_ids: value.preserve_legacy_source_ids.filter(
            (id) => id !== source.id,
          ),
        }
      : value;
  }
  function setDatabase(
    source: SourceCatalog,
    database: string,
    grant?: DatabaseGrant,
  ) {
    const next = materialize(source);
    onChange({
      ...next,
      databases: [
        ...next.databases.filter(
          (g) => !(g.source_id === source.id && g.database === database),
        ),
        ...(grant ? [grant] : []),
      ],
    });
  }
  function setSource(source: SourceCatalog, checked: boolean) {
    onChange({
      databases: [
        ...value.databases.filter((g) => g.source_id !== source.id),
        ...(checked
          ? source.databases.map((d) => ({
              source_id: source.id,
              database: d.name,
              all_companies: true,
              company_ids: [],
            }))
          : []),
      ],
      preserve_legacy_source_ids: value.preserve_legacy_source_ids.filter(
        (id) => id !== source.id,
      ),
    });
  }
  async function toggleCompanies(source: SourceCatalog, database: string) {
    const id = key(source.id, database);
    setExpanded((e) => ({ ...e, [id]: !e[id] }));
    if (companies[id] || companyLoading[id]) return;
    setCompanyLoading((v) => ({ ...v, [id]: true }));
    setCompanyErrors((v) => ({ ...v, [id]: "" }));
    try {
      const result = await api<CompanyCatalog>(
        `/admin/access-catalog/${source.id}/companies?database=${encodeURIComponent(database)}`,
      );
      setCompanies((v) => ({ ...v, [id]: result }));
    } catch (e) {
      setCompanyErrors((v) => ({
        ...v,
        [id]: errorMessage((e as Error).message),
      }));
    } finally {
      setCompanyLoading((v) => ({ ...v, [id]: false }));
    }
  }
  return (
    <section
      className="database-access-picker"
      aria-label="Qasja në databaza dhe kompani"
    >
      <h3>Databazat dhe kompanitë</h3>
      <p>
        {allAccess
          ? "President dhe Devs kanë automatikisht qasje në të gjitha databazat dhe kompanitë."
          : "Zgjidhni databazat dhe kompanitë që ky Manager mund të përdorë."}
      </p>
      {loading && <p role="status">Duke ngarkuar databazat…</p>}
      {error && (
        <p role="alert" className="message-warning">
          {shown(error)}
        </p>
      )}
      {!loading && !error && !sources.length && (
        <p>Nuk ka ende burime databazash të konfiguruara.</p>
      )}
      {sources.map((source) => {
        const count = source.databases.filter(
          (d) => !!selected(source.id, d.name),
        ).length;
        const sourceSelected =
          allAccess ||
          legacy(source.id) ||
          (source.databases.length > 0 && count === source.databases.length);
        return (
          <fieldset className="access-source" key={source.id}>
            <legend>
              <label>
                <GrantCheck
                  aria-label={`Të gjitha databazat: ${source.name}`}
                  checked={sourceSelected}
                  partial={
                    !allAccess &&
                    !legacy(source.id) &&
                    count > 0 &&
                    count < source.databases.length
                  }
                  disabled={disabled || allAccess || !source.databases.length}
                  onChange={(e) => setSource(source, e.target.checked)}
                />
                {source.name}
              </label>
            </legend>
            {source.error && (
              <p className="message-warning">
                {shown(errorMessage(source.error))}
              </p>
            )}
            {legacy(source.id) && !source.catalog_complete && (
              <p>Qasja ekzistuese ruhet. Katalogu nuk u ngarkua plotësisht.</p>
            )}
            {source.databases.map((database) => {
              const id = key(source.id, database.name),
                grant = selected(source.id, database.name),
                catalog = companies[id];
              return (
                <div className="access-database" key={database.name}>
                  <div className="access-database-heading">
                    <label>
                      <GrantCheck
                        aria-label={`Databaza ${database.name} në ${source.name}`}
                        checked={allAccess || !!grant}
                        disabled={disabled || allAccess}
                        onChange={(e) =>
                          setDatabase(
                            source,
                            database.name,
                            e.target.checked
                              ? {
                                  source_id: source.id,
                                  database: database.name,
                                  all_companies: true,
                                  company_ids: [],
                                }
                              : undefined,
                          )
                        }
                      />
                      {database.name}
                    </label>
                    <button
                      type="button"
                      className="text-button"
                      aria-label={`${expanded[id] ? "Mbyll" : "Shfaq"} kompanitë në ${database.name}`}
                      data-tooltip={`${expanded[id] ? "Mbyll" : "Shfaq"} kompanitë në ${database.name}`}
                      aria-expanded={!!expanded[id]}
                      onClick={() =>
                        void toggleCompanies(source, database.name)
                      }
                    >
                      Kompanitë
                      {grant && !grant.all_companies
                        ? ` (${grant.company_ids.length})`
                        : ""}
                      {expanded[id] ? (
                        <ChevronUp size={18} />
                      ) : (
                        <ChevronDown size={18} />
                      )}
                    </button>
                  </div>
                  {expanded[id] && (
                    <div className="access-companies">
                      {companyLoading[id] && (
                        <p role="status">Duke verifikuar kompanitë…</p>
                      )}
                      {companyErrors[id] && (
                        <p className="message-warning" role="alert">
                          {shown(companyErrors[id])}
                        </p>
                      )}
                      {catalog && (
                        <>
                          <label>
                            <GrantCheck
                              aria-label={`Të gjitha kompanitë në ${database.name}`}
                              checked={allAccess || !!grant?.all_companies}
                              disabled={disabled || allAccess}
                              onChange={(e) =>
                                setDatabase(
                                  source,
                                  database.name,
                                  e.target.checked
                                    ? {
                                        source_id: source.id,
                                        database: database.name,
                                        all_companies: true,
                                        company_ids: [],
                                      }
                                    : undefined,
                                )
                              }
                            />
                            Të gjitha kompanitë
                          </label>
                          {catalog.companies.length > 8 && (
                            <input
                              type="search"
                              aria-label={`Kërko kompani në ${database.name}`}
                              placeholder="Kërko kompani…"
                              value={companySearch[id] || ""}
                              onChange={(e) =>
                                setCompanySearch((v) => ({
                                  ...v,
                                  [id]: e.target.value,
                                }))
                              }
                            />
                          )}
                          <div className="access-company-list">
                            {catalog.companies
                              .filter((company) =>
                                company.name
                                  .toLocaleLowerCase()
                                  .replace(/\s/g, "")
                                  .includes(
                                    (companySearch[id] || "")
                                      .toLocaleLowerCase()
                                      .replace(/\s/g, ""),
                                  ),
                              )
                              .map((company) => (
                                <label key={company.id}>
                                  <GrantCheck
                                    aria-label={`${company.name} në ${database.name}`}
                                    checked={
                                      allAccess ||
                                      !!grant?.all_companies ||
                                      !!grant?.company_ids.includes(company.id)
                                    }
                                    disabled={disabled || allAccess}
                                    onChange={(e) => {
                                      const ids = new Set(
                                        grant?.all_companies
                                          ? catalog.companies.map((c) => c.id)
                                          : grant?.company_ids || [],
                                      );
                                      if (e.target.checked) ids.add(company.id);
                                      else ids.delete(company.id);
                                      setDatabase(
                                        source,
                                        database.name,
                                        ids.size
                                          ? {
                                              source_id: source.id,
                                              database: database.name,
                                              all_companies: false,
                                              company_ids: [...ids],
                                            }
                                          : undefined,
                                      );
                                    }}
                                  />
                                  {company.name}
                                  <small>{company.schema}</small>
                                </label>
                              ))}
                          </div>
                          {!catalog.companies.length && (
                            <p>
                              Nuk u gjet katalog kompanish. Zgjedhja e databazës
                              jep qasje në të gjithë databazën.
                            </p>
                          )}
                          {catalog.warnings.map((warning) => (
                            <p className="message-warning" key={warning}>
                              {errorMessage(warning)}
                            </p>
                          ))}
                        </>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </fieldset>
        );
      })}
    </section>
  );
}
