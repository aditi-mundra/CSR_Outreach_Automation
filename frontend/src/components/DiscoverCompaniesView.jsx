import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { discoverCompanies, listDiscoverySources } from "../api/client";
import { PROVENANCE_STYLES } from "../constants";
import DiscoveredCompanyCard from "./DiscoveredCompanyCard";

const PAGE_SIZE = 20;

const FIELDS = [
  { key: "name", label: "Company name", placeholder: "e.g. Tata, Infosys, Cipla" },
  { key: "industry", label: "Industry", placeholder: "e.g. pharma, IT, steel, bank" },
  { key: "city", label: "City", placeholder: "e.g. Pune" },
  { key: "state", label: "State", placeholder: "e.g. Maharashtra" },
  { key: "csr_focus", label: "CSR focus area", placeholder: "e.g. Education" },
];
const FILTER_KEYS = FIELDS.map((f) => f.key);

const EXAMPLES = [
  { label: "Pharma companies in Maharashtra", filters: { industry: "pharma", state: "Maharashtra" } },
  { label: "IT companies in Pune", filters: { industry: "IT", city: "Pune" } },
  { label: "Banks in Mumbai", filters: { industry: "bank", city: "Mumbai" } },
  { label: "Tata group companies", filters: { name: "Tata" } },
];

const INPUT_CLASS =
  "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500";

function filtersFromParams(params) {
  return Object.fromEntries(FILTER_KEYS.map((key) => [key, params.get(key) ?? ""]));
}

function SourcesPanel({ sources }) {
  const [open, setOpen] = useState(false);
  if (!sources) return null;
  const active = sources.filter((s) => s.configured).length;

  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm shadow-sm">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between text-left text-slate-600"
      >
        <span>
          <strong className="font-medium text-slate-700">Data sources:</strong>{" "}
          {active} of {sources.length} active ·{" "}
          {sources.map((s) => `${s.label}${s.configured ? " ✓" : ""}`).join(" · ")}
        </span>
        <span className="text-slate-400">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <ul className="mt-2 space-y-2 border-t border-slate-100 pt-2">
          {sources.map((s) => (
            <li key={s.key}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-slate-700">{s.label}</span>
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                    s.configured ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"
                  }`}
                >
                  {s.configured ? "Active" : "Not set up"}
                </span>
                {s.requires_api_key && <span className="text-xs text-slate-400">needs a free API key</span>}
              </div>
              <p className="text-xs text-slate-500">{s.description}</p>
              {s.status && <p className="text-xs text-slate-500">Status: {s.status}</p>}
              {!s.configured && <p className="text-xs text-amber-700">Setup: {s.setup_hint}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function DiscoverCompaniesView() {
  const [params, setParams] = useSearchParams();
  const applied = useMemo(() => filtersFromParams(params), [params]);
  const page = Number(params.get("page") || 0);
  const hasSearch = FILTER_KEYS.some((key) => applied[key].trim());

  const [draft, setDraft] = useState(applied);
  const [draftFor, setDraftFor] = useState(applied);
  // The last finished request, tagged with the search it answers - loading
  // is simply "the URL's search isn't the one we have an answer for yet".
  const [fetched, setFetched] = useState({ key: null, data: null, error: null });
  const [sources, setSources] = useState(null);
  const searchKey = JSON.stringify({ applied, page });

  // Keep the form in sync when the URL changes (Back button, example chips).
  if (draftFor !== applied) {
    setDraftFor(applied);
    setDraft(applied);
  }

  useEffect(() => {
    listDiscoverySources().then(setSources).catch(() => {});
  }, []);

  useEffect(() => {
    if (!hasSearch) return undefined;
    let ignore = false;
    discoverCompanies(applied, { page, pageSize: PAGE_SIZE })
      .then((data) => {
        if (!ignore) setFetched({ key: searchKey, data, error: null });
      })
      .catch((err) => {
        if (!ignore) setFetched({ key: searchKey, data: null, error: err.message });
      });
    return () => {
      ignore = true;
    };
  }, [applied, page, hasSearch, searchKey]);

  const runSearch = (filters, nextPage = 0) => {
    const next = new URLSearchParams();
    FILTER_KEYS.forEach((key) => {
      if (filters[key]?.trim()) next.set(key, filters[key].trim());
    });
    if (nextPage) next.set("page", String(nextPage));
    setParams(next);
  };

  const handleSubmit = (event) => {
    event.preventDefault();
    runSearch(draft);
  };

  const updateResult = (updated) => {
    setFetched((current) => ({
      ...current,
      data: {
        ...current.data,
        results: current.data.results.map((r) => (r.result_id === updated.result_id ? updated : r)),
      },
    }));
  };

  const current = hasSearch && fetched.key === searchKey;
  const loading = hasSearch && !current;
  const error = current ? fetched.error : null;
  const shown = current ? fetched.data : null;
  const total = shown?.total ?? 0;
  const results = shown?.results ?? [];
  const sourceErrors = (shown?.sources ?? []).filter((s) => s.error);

  return (
    <div className="space-y-4">
      <form onSubmit={handleSubmit} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <p className="mb-3 text-sm text-slate-500">
          Search real Indian companies from public sources. Nothing is added to your list until you
          click <strong>Save as lead</strong>.
        </p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {FIELDS.map((field) => (
            <div key={field.key}>
              <label className="mb-1 block text-xs font-medium text-slate-600">{field.label}</label>
              <input
                type="text"
                value={draft[field.key]}
                onChange={(e) => setDraft({ ...draft, [field.key]: e.target.value })}
                placeholder={field.placeholder}
                className={INPUT_CLASS}
              />
            </div>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap gap-2">
            {EXAMPLES.map((example) => (
              <button
                key={example.label}
                type="button"
                onClick={() => runSearch(example.filters)}
                className="rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-600 hover:border-emerald-300 hover:text-emerald-700"
              >
                {example.label}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => runSearch({})}
              className="text-sm font-medium text-slate-500 hover:text-slate-700"
            >
              Clear
            </button>
            <button
              type="submit"
              disabled={!FILTER_KEYS.some((key) => draft[key].trim())}
              className="rounded-lg bg-emerald-600 px-5 py-2 text-sm font-medium text-white shadow-sm hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Search companies
            </button>
          </div>
        </div>
      </form>

      <SourcesPanel sources={sources} />

      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
        {Object.entries({
          verified: "stated by a named public source",
          inferred: "worked out by the app - double-check",
          unavailable: "no public source has it",
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

      {error && <p className="rounded-lg bg-rose-50 px-4 py-2 text-sm text-rose-700">{error}</p>}

      {shown?.notes?.length > 0 && (
        <ul className="space-y-1 rounded-lg border border-sky-100 bg-sky-50 px-4 py-2 text-sm text-sky-800">
          {shown.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
      {sourceErrors.length > 0 && (
        <p className="rounded-lg bg-amber-50 px-4 py-2 text-sm text-amber-800">
          Some sources could not be reached, so results may be incomplete:{" "}
          {sourceErrors.map((s) => `${s.label} (${s.error})`).join("; ")}
        </p>
      )}

      {!hasSearch && (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white px-6 py-10 text-center text-sm text-slate-500">
          Enter a company name, industry or location above - or try one of the examples - to find
          companies across India.
        </div>
      )}

      {hasSearch && loading && (
        <div className="rounded-xl border border-slate-200 bg-white px-6 py-10 text-center text-sm text-slate-500">
          Searching public sources… this can take a few seconds.
        </div>
      )}

      {shown && !loading && results.length === 0 && (
        <div className="rounded-xl border border-slate-200 bg-white px-6 py-10 text-center text-sm text-slate-500">
          No companies found. Try a broader search - for example just an industry or a state.
        </div>
      )}

      {hasSearch && !loading && results.length > 0 && (
        <>
          <p className="text-sm text-slate-500">
            {total.toLocaleString("en-IN")} compan{total === 1 ? "y" : "ies"} found · showing{" "}
            {page * PAGE_SIZE + 1}–{page * PAGE_SIZE + results.length}
          </p>
          <ul className="space-y-3">
            {results.map((company) => (
              <DiscoveredCompanyCard key={company.result_id} company={company} onChange={updateResult} />
            ))}
          </ul>
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => runSearch(applied, Math.max(0, page - 1))}
              disabled={page === 0}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              ← Previous
            </button>
            <button
              type="button"
              onClick={() => runSearch(applied, page + 1)}
              disabled={(page + 1) * PAGE_SIZE >= total}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Next →
            </button>
          </div>
        </>
      )}
    </div>
  );
}
