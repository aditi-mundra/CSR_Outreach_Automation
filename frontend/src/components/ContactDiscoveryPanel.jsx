import { useEffect, useState } from "react";
import { findContacts, saveDiscoveredContacts } from "../api/client";
import { CONTACT_PRIORITIES, PROVENANCE_STYLES } from "../constants";
import { displayHost } from "../utils/format";
import DiscoveredContactCard from "./DiscoveredContactCard";

const SAVE_KEYS = [
  "name",
  "designation",
  "role_category",
  "priority",
  "office_location",
  "email",
  "phone",
  "linkedin_url",
  "source_url",
  "confidence",
  "provenance",
  "sources",
];

const toSavePayload = (contact) => Object.fromEntries(SAVE_KEYS.map((key) => [key, contact[key]]));

function ProvenanceLegend() {
  return (
    <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
      {Object.entries({
        verified: "published by the company / named source",
        inferred: "worked out by the app - double-check",
        unavailable: "not published anywhere we can read",
      }).map(([status, meaning]) => (
        <span key={status} className="inline-flex items-center gap-1">
          <span
            className={`rounded-full px-1.5 py-px text-[10px] font-medium ring-1 ring-inset ${PROVENANCE_STYLES[status].className}`}
          >
            {PROVENANCE_STYLES[status].label}
          </span>
          {meaning}
        </span>
      ))}
    </p>
  );
}

// Finds publicly listed CSR decision makers for a company - a saved lead
// (company.id) or a just-discovered one (savePayload is then used to save
// it as a lead when the first contact is saved).
export default function ContactDiscoveryPanel({ company, savePayload, onSaved }) {
  const [savedCompanyId, setSavedCompanyId] = useState(company.id ?? company.saved_company_id ?? null);
  // Each search request, with the company it targets fixed at request time:
  // once a contact is saved, later searches use the saved lead.
  const [run, setRun] = useState(() => ({
    n: 0,
    includeReports: false,
    refresh: false,
    target: savedCompanyId ? { id: savedCompanyId } : company,
  }));
  const [fetched, setFetched] = useState({ n: null, data: null, error: null });
  const [selected, setSelected] = useState(() => new Set());
  const [rows, setRows] = useState({});
  const [savingSelected, setSavingSelected] = useState(false);
  const [dropped, setDropped] = useState([]);

  useEffect(() => {
    let ignore = false;
    findContacts(run.target, { includeReports: run.includeReports, refresh: run.refresh })
      .then((data) => {
        if (!ignore) setFetched({ n: run.n, data, error: null });
      })
      .catch((err) => {
        if (!ignore) setFetched({ n: run.n, data: null, error: err.message });
      });
    return () => {
      ignore = true;
    };
  }, [run]);

  const loading = fetched.n !== run.n;
  const data = loading ? null : fetched.data;
  const contacts = data?.contacts ?? [];

  const rerun = (changes) => {
    setSelected(new Set());
    setRows({});
    setDropped([]);
    const target = savedCompanyId ? { id: savedCompanyId } : company;
    setRun((current) => ({ ...current, refresh: false, ...changes, target, n: current.n + 1 }));
  };

  const isSaved = (contact) => Boolean(rows[contact.candidate_id]?.savedId ?? contact.saved_contact_id);

  const toggle = (contact) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(contact.candidate_id)) next.delete(contact.candidate_id);
      else next.add(contact.candidate_id);
      return next;
    });
  };

  const save = async (batch, { force = false } = {}) => {
    const ids = batch.map((c) => c.candidate_id);
    setRows((current) => ({ ...current, ...Object.fromEntries(ids.map((id) => [id, { saving: true }])) }));
    try {
      const result = await saveDiscoveredContacts({
        companyId: savedCompanyId,
        companyPayload: savePayload ?? {
          name: company.name,
          website: company.website || null,
          city: company.city || null,
          state: company.state || null,
          industry: company.industry || null,
          csr_report_url: company.csr_report_url || null,
        },
        contacts: batch.map(toSavePayload),
        force,
      });
      const duplicates = Object.fromEntries(result.duplicates.map((d) => [d.index, d]));
      const savedQueue = [...result.saved];
      const updates = {};
      batch.forEach((contact, index) => {
        updates[contact.candidate_id] = duplicates[index]
          ? { duplicate: duplicates[index] }
          : { savedId: savedQueue.shift()?.id };
      });
      setRows((current) => ({ ...current, ...updates }));
      setSelected((current) => new Set([...current].filter((id) => !updates[id]?.savedId)));
      setDropped(result.dropped);
      setSavedCompanyId(result.company_id);
      onSaved?.(result.company_id, result);
    } catch (err) {
      setRows((current) => ({
        ...current,
        ...Object.fromEntries(ids.map((id) => [id, { error: err.message }])),
      }));
    }
  };

  const saveSelected = async () => {
    setSavingSelected(true);
    await save(contacts.filter((c) => selected.has(c.candidate_id)));
    setSavingSelected(false);
  };

  const selectable = contacts.filter((c) => !isSaved(c));
  const allSelected = selectable.length > 0 && selectable.every((c) => selected.has(c.candidate_id));
  const reportKnown = Boolean(company.csr_report_url || data?.report?.url || data?.report_links?.length);
  const groups = [1, 2, 3].map((priority) => ({
    priority,
    contacts: contacts.filter((c) => c.priority === priority),
  }));

  return (
    <div className="space-y-4 pb-2">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-600">
        <div>
          {company.website ? (
            <>
              Reads <strong>{displayHost(company.website)}</strong>&apos;s public leadership, CSR, committee,
              contact and press pages (respecting robots.txt).
            </>
          ) : (
            "No website is known for this company yet."
          )}
          {!savedCompanyId && (
            <span className="block text-xs text-slate-500">
              Saving a contact also saves {company.name} as a lead.
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label
            className={`flex items-center gap-1.5 text-xs ${reportKnown ? "text-slate-600" : "text-slate-400"}`}
            title="Reads the CSR Committee from the CSR / annual report PDF - slower (up to a minute)"
          >
            <input
              type="checkbox"
              checked={run.includeReports}
              disabled={loading || !reportKnown}
              onChange={(e) => rerun({ includeReports: e.target.checked })}
              className="accent-emerald-600"
            />
            Also scan CSR report (slower)
          </label>
          <button
            type="button"
            onClick={() => rerun({ refresh: true })}
            disabled={loading}
            className="rounded-lg border border-slate-300 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-white disabled:opacity-50"
          >
            Search again
          </button>
        </div>
      </div>

      <ProvenanceLegend />

      {loading && (
        <div className="rounded-xl border border-slate-200 px-6 py-10 text-center text-sm text-slate-500">
          Reading public pages… this usually takes 10–30 seconds
          {run.includeReports ? " (longer while the CSR report is scanned)" : ""}.
        </div>
      )}
      {!loading && fetched.error && (
        <p className="rounded-lg bg-rose-50 px-4 py-2 text-sm text-rose-700">{fetched.error}</p>
      )}

      {data && (
        <>
          <p className="text-xs text-slate-500">
            {data.pages_checked.length} page(s) read
            {data.pages_blocked.length > 0 && ` · ${data.pages_blocked.length} skipped by robots.txt`}
            {data.report.scanned &&
              ` · CSR report: ${data.report.pages_read} pages read, committee on page(s) ${
                data.report.relevant_pages.join(", ") || "none"
              }`}
            {data.duration_ms != null && ` · ${Math.max(1, Math.round(data.duration_ms / 1000))}s`}
            {data.cached && " · from a search in the last 10 minutes"}
          </p>

          {[...data.messages, data.report.message].filter(Boolean).length > 0 && (
            <ul className="space-y-1 rounded-lg border border-sky-100 bg-sky-50 px-4 py-2 text-sm text-sky-800">
              {[...data.messages, data.report.message].filter(Boolean).map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          )}
          {dropped.length > 0 && (
            <ul className="space-y-1 rounded-lg bg-amber-50 px-4 py-2 text-sm text-amber-800">
              {dropped.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          )}

          {contacts.length > 0 && (
            <div className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-white py-2">
              <label className="flex items-center gap-2 text-sm text-slate-600">
                <input
                  type="checkbox"
                  checked={allSelected}
                  disabled={selectable.length === 0}
                  onChange={() =>
                    setSelected(allSelected ? new Set() : new Set(selectable.map((c) => c.candidate_id)))
                  }
                  className="h-4 w-4 accent-emerald-600"
                />
                {contacts.length} contact{contacts.length === 1 ? "" : "s"} found · select all
              </label>
              <button
                type="button"
                onClick={saveSelected}
                disabled={selected.size === 0 || savingSelected}
                className="rounded-lg bg-emerald-600 px-4 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {savingSelected ? "Saving…" : `Save selected (${selected.size})`}
              </button>
            </div>
          )}

          {groups
            .filter((group) => group.contacts.length > 0)
            .map((group) => (
              <section key={group.priority}>
                <h3 className="mb-2 text-sm font-semibold text-slate-800">
                  {CONTACT_PRIORITIES[group.priority].label} · {CONTACT_PRIORITIES[group.priority].group}{" "}
                  <span className="font-normal text-slate-400">({group.contacts.length})</span>
                </h3>
                <ul className="space-y-3">
                  {group.contacts.map((contact) => (
                    <DiscoveredContactCard
                      key={contact.candidate_id}
                      contact={contact}
                      selected={selected.has(contact.candidate_id)}
                      onToggle={() => toggle(contact)}
                      onSave={() => save([contact])}
                      onForceSave={() => save([contact], { force: true })}
                      rowState={rows[contact.candidate_id]}
                    />
                  ))}
                </ul>
              </section>
            ))}

          {data.contact_points.length > 0 && (
            <section className="rounded-lg border border-slate-200 p-3">
              <h3 className="mb-1 text-sm font-semibold text-slate-800">Company contact points</h3>
              <p className="mb-2 text-xs text-slate-500">
                Official general inboxes and office lines published by the company - not a named person.
              </p>
              <ul className="space-y-1 text-sm">
                {data.contact_points.map((point) => (
                  <li key={point.value} className="flex flex-wrap items-center gap-2">
                    <span className="text-xs text-slate-400">{point.label}</span>
                    {point.kind === "email" ? (
                      <a href={`mailto:${point.value}`} className="text-emerald-700 hover:underline">
                        {point.value}
                      </a>
                    ) : (
                      <span className="text-slate-700">{point.value}</span>
                    )}
                    {point.source_url && (
                      <a
                        href={point.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs text-slate-400 underline decoration-slate-300 hover:text-slate-600"
                      >
                        source ↗
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="rounded-lg border border-slate-200 p-3">
            <h3 className="mb-1 text-sm font-semibold text-slate-800">Search further yourself</h3>
            <p className="mb-2 text-xs text-slate-500">
              These open in a new tab. The app never reads LinkedIn or search engines itself.
            </p>
            <ul className="flex flex-wrap gap-2">
              {data.suggested_searches.map((link) => (
                <li key={link.url}>
                  <a
                    href={link.url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-block rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-600 hover:border-emerald-300 hover:text-emerald-700"
                  >
                    {link.name} ↗
                  </a>
                </li>
              ))}
            </ul>
          </section>

          <details className="text-xs text-slate-500">
            <summary className="cursor-pointer font-medium text-slate-600">Sources checked</summary>
            <ul className="mt-2 space-y-1">
              {data.sources.map((source) => (
                <li key={source.key}>
                  <strong className="font-medium text-slate-600">{source.label}:</strong>{" "}
                  {source.used ? `${source.result_count} result(s)` : "not used"}
                  {source.message ? ` - ${source.message}` : ""}
                </li>
              ))}
              {data.pages_checked.map((url) => (
                <li key={url} className="truncate">
                  Read:{" "}
                  <a href={url} target="_blank" rel="noreferrer" className="underline decoration-slate-300">
                    {url}
                  </a>
                </li>
              ))}
              {data.pages_blocked.map((url) => (
                <li key={url} className="truncate">
                  Skipped (robots.txt): {url}
                </li>
              ))}
            </ul>
          </details>
        </>
      )}
    </div>
  );
}
