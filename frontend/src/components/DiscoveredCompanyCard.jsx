import { useState } from "react";
import { Link } from "react-router-dom";
import { checkCsrFocus, saveDiscoveredCompany } from "../api/client";
import { displayHost, formatInr } from "../utils/format";
import FindContactsButton from "./FindContactsButton";
import ProvenanceBadge from "./ProvenanceBadge";

const IDENTIFIER_LABELS = {
  wikidata: "Wikidata",
  cin: "CIN",
  isin: "ISIN",
  nse_symbol: "NSE symbol",
  bse_code: "BSE code",
};

const SAVE_FIELDS = [
  "name",
  "industry",
  "city",
  "state",
  "website",
  "csr_report_url",
  "csr_focus",
  "csr_spending",
  "employee_count",
  "provenance",
  "identifiers",
  "listed_on",
  "details",
  "sources",
];

// Location shows city + state together, so its badge is the weaker of the
// two: inferred if either part was inferred.
function combinedProvenance(...items) {
  const present = items.filter((item) => item && item.status !== "unavailable");
  if (present.length === 0) return { status: "unavailable" };
  const inferred = present.find((item) => item.status === "inferred");
  const sources = [...new Set(present.map((item) => item.source).filter(Boolean))].join("; ");
  return {
    status: inferred ? "inferred" : "verified",
    source: sources,
    source_url: (inferred ?? present[0]).source_url,
  };
}

function Field({ label, provenance, children }) {
  return (
    <div className="min-w-0">
      <div className="mb-0.5 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-400">
        {label}
        <ProvenanceBadge provenance={provenance} />
      </div>
      <div className="truncate text-sm text-slate-700">{children}</div>
    </div>
  );
}

export default function DiscoveredCompanyCard({ company, onChange }) {
  const [saving, setSaving] = useState(false);
  const [duplicate, setDuplicate] = useState(null);
  const [error, setError] = useState(null);
  const [checking, setChecking] = useState(false);
  const [focusMessage, setFocusMessage] = useState(null);
  const [showDetails, setShowDetails] = useState(false);

  const p = company.provenance || {};
  const location = [company.city, company.state].filter(Boolean).join(", ");
  const locationProvenance = combinedProvenance(p.city, p.state);

  const savePayload = Object.fromEntries(SAVE_FIELDS.map((key) => [key, company[key]]));

  const save = async (force = false) => {
    setSaving(true);
    setError(null);
    try {
      const created = await saveDiscoveredCompany(savePayload, { force });
      setDuplicate(null);
      onChange({ ...company, saved_company_id: created.id });
    } catch (err) {
      if (err.status === 409 && err.detail?.existing_company_id) {
        setDuplicate(err.detail);
      } else {
        setError(err.message);
      }
    } finally {
      setSaving(false);
    }
  };

  const handleCheckFocus = async () => {
    setChecking(true);
    setFocusMessage(null);
    try {
      const result = await checkCsrFocus(company.website);
      const updated = { ...company, provenance: { ...company.provenance } };
      if (result.csr_focus) {
        updated.csr_focus = result.csr_focus;
        updated.provenance.csr_focus = {
          status: "inferred",
          source: "keywords on the company's own CSR web pages",
          source_url: result.source_urls[0] ?? null,
        };
      } else {
        setFocusMessage(result.message || "No CSR focus areas found on the company's website.");
      }
      if (result.csr_report_url && !company.csr_report_url) {
        updated.csr_report_url = result.csr_report_url;
        updated.provenance.csr_report_url = {
          status: "inferred",
          source: "report link found on the company's website",
          source_url: result.csr_report_url,
        };
      }
      onChange(updated);
    } catch (err) {
      setFocusMessage(`Could not check the website: ${err.message}`);
    } finally {
      setChecking(false);
    }
  };

  const identifiers = Object.entries(company.identifiers || {});
  const details = Object.entries(company.details || {});

  return (
    <li className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold text-slate-900">{company.name}</h3>
            {company.listed_on.map((exchange) => (
              <span
                key={exchange}
                className="rounded bg-indigo-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-indigo-700"
              >
                {exchange}
              </span>
            ))}
          </div>
          {company.description && <p className="mt-0.5 text-sm text-slate-500">{company.description}</p>}
        </div>

        <div className="flex shrink-0 flex-col items-end gap-1">
          {company.saved_company_id ? (
            <Link
              to={`/companies/${company.saved_company_id}`}
              className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-sm font-medium text-emerald-700 hover:bg-emerald-100"
            >
              ✓ Saved · Open lead →
            </Link>
          ) : (
            <button
              type="button"
              onClick={() => save(false)}
              disabled={saving}
              className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-emerald-700 disabled:opacity-60"
            >
              {saving ? "Saving…" : "Save as lead"}
            </button>
          )}
          <FindContactsButton
            company={company}
            savePayload={savePayload}
            onSaved={(companyId) => onChange({ ...company, saved_company_id: companyId })}
            variant="small"
          />
        </div>
      </div>

      {duplicate && (
        <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
          <span>
            Already saved as <strong>{duplicate.existing_company_name}</strong>.
          </span>
          <Link
            to={`/companies/${duplicate.existing_company_id}`}
            className="font-medium text-amber-900 underline"
          >
            View existing
          </Link>
          <button
            type="button"
            onClick={() => save(true)}
            disabled={saving}
            className="font-medium text-amber-900 underline disabled:opacity-60"
          >
            Save anyway
          </button>
        </div>
      )}
      {error && <p className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>}

      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Industry" provenance={p.industry}>
          {company.industry || <span className="text-slate-400">—</span>}
        </Field>
        <Field label="Location" provenance={locationProvenance}>
          {location || <span className="text-slate-400">—</span>}
        </Field>
        <Field label="Website" provenance={p.website}>
          {company.website ? (
            <a
              href={company.website}
              target="_blank"
              rel="noreferrer"
              className="text-emerald-700 hover:underline"
            >
              {displayHost(company.website)} ↗
            </a>
          ) : (
            <span className="text-slate-400">—</span>
          )}
        </Field>
        <Field label="CSR focus" provenance={p.csr_focus}>
          {company.csr_focus ? (
            <span title={company.csr_focus}>{company.csr_focus}</span>
          ) : company.website ? (
            <button
              type="button"
              onClick={handleCheckFocus}
              disabled={checking}
              className="text-sm font-medium text-emerald-700 hover:text-emerald-800 disabled:opacity-60"
              title="Reads the company's own CSR pages (respecting robots.txt) and looks for Schedule VII focus areas"
            >
              {checking ? "Checking website…" : "Check CSR focus"}
            </button>
          ) : (
            <span className="text-slate-400">—</span>
          )}
        </Field>
      </div>

      {(company.csr_spending || company.csr_report_url || company.employee_count) && (
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {company.csr_spending ? (
            <Field label="CSR spending" provenance={p.csr_spending}>
              {formatInr(company.csr_spending)}
              {company.details?.["CSR spend year"] && (
                <span className="text-slate-400"> ({company.details["CSR spend year"]})</span>
              )}
            </Field>
          ) : null}
          {company.csr_report_url ? (
            <Field label="CSR report" provenance={p.csr_report_url}>
              <a
                href={company.csr_report_url}
                target="_blank"
                rel="noreferrer"
                className="text-emerald-700 hover:underline"
              >
                Open report ↗
              </a>
            </Field>
          ) : null}
          {company.employee_count ? (
            <Field label="Employees" provenance={p.employee_count}>
              {company.employee_count.toLocaleString("en-IN")}
            </Field>
          ) : null}
        </div>
      )}

      {focusMessage && <p className="mt-2 text-xs text-slate-500">{focusMessage}</p>}

      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-slate-100 pt-2 text-xs text-slate-500">
        <span>Sources:</span>
        {company.sources.map((source) =>
          source.url ? (
            <a
              key={source.name}
              href={source.url}
              target="_blank"
              rel="noreferrer"
              className="text-slate-600 underline decoration-slate-300 hover:text-slate-800"
            >
              {source.name} ↗
            </a>
          ) : (
            <span key={source.name} className="text-slate-600">
              {source.name}
            </span>
          ),
        )}
        {(identifiers.length > 0 || details.length > 0) && (
          <button
            type="button"
            onClick={() => setShowDetails((v) => !v)}
            className="ml-auto font-medium text-slate-500 hover:text-slate-700"
          >
            {showDetails ? "Hide details" : "More details"}
          </button>
        )}
      </div>

      {showDetails && (
        <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
          {identifiers.map(([key, value]) => (
            <div key={key} className="flex gap-2">
              <dt className="text-slate-400">{IDENTIFIER_LABELS[key] ?? key}</dt>
              <dd className="text-slate-700">{value}</dd>
            </div>
          ))}
          {details
            .filter(([key]) => key !== "CSR spend year")
            .map(([key, value]) => (
              <div key={key} className="flex gap-2">
                <dt className="text-slate-400">{key}</dt>
                <dd className="text-slate-700">{value}</dd>
              </div>
            ))}
          {company.aliases.length > 0 && (
            <div className="flex gap-2 sm:col-span-2">
              <dt className="text-slate-400">Also known as</dt>
              <dd className="text-slate-700">{company.aliases.join(", ")}</dd>
            </div>
          )}
        </dl>
      )}
    </li>
  );
}
