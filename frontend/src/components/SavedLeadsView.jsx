import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { listCompanies, createCompany, exportCompaniesUrl, importCompaniesCsv } from "../api/client";
import CompanyFilters from "./CompanyFilters";
import CompanyForm from "./CompanyForm";
import FindContactsButton from "./FindContactsButton";
import StatusBadge from "./StatusBadge";
import { PRIORITY_STYLES } from "../constants";

const PAGE_SIZE = 25;

// The NGO's own saved leads (the CRM list) - every company here was either
// saved from Discover, added by hand, or imported from CSV.
export default function SavedLeadsView() {
  const [filters, setFilters] = useState({});
  const [page, setPage] = useState(0);
  const [companies, setCompanies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [importResult, setImportResult] = useState(null);
  const [importing, setImporting] = useState(false);
  const fileInputRef = useRef(null);

  const updateFilters = (newFilters) => {
    setFilters(newFilters);
    setPage(0);
  };

  useEffect(() => {
    const timeout = setTimeout(() => {
      setLoading(true);
      listCompanies({ ...filters, skip: page * PAGE_SIZE, limit: PAGE_SIZE })
        .then(setCompanies)
        .catch((err) => setError(err.message))
        .finally(() => setLoading(false));
    }, 250); // debounce free-text filter typing

    return () => clearTimeout(timeout);
  }, [filters, page]);

  const reload = () => {
    listCompanies({ ...filters, skip: page * PAGE_SIZE, limit: PAGE_SIZE }).then(setCompanies);
  };

  const handleCreate = async (payload, { force = false } = {}) => {
    await createCompany(payload, { force });
    setShowForm(false);
    reload();
  };

  const handleImportFile = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = ""; // allow re-selecting the same file later
    if (!file) return;

    setImporting(true);
    setImportResult(null);
    try {
      const result = await importCompaniesCsv(file);
      setImportResult(result);
      updateFilters({});
    } catch (err) {
      setImportResult({ created: 0, skipped_duplicates: 0, errors: [err.message] });
    } finally {
      setImporting(false);
    }
  };

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-slate-500">
          Companies you have saved as leads. Lead scores, AI tools, contacts, notes and
          documents are on each company&apos;s page.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <a
            href={exportCompaniesUrl(filters)}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50"
          >
            Export CSV
          </a>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={importing}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-60"
          >
            {importing ? "Importing…" : "Import CSV"}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={handleImportFile}
          />
          <button
            type="button"
            onClick={() => setShowForm(true)}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-emerald-700"
          >
            + Add company
          </button>
        </div>
      </div>

      <div className="mb-6">
        <CompanyFilters filters={filters} onChange={updateFilters} onReset={() => updateFilters({})} />
      </div>

      {error && (
        <p className="mb-4 rounded-lg bg-rose-50 px-4 py-2 text-sm text-rose-700">{error}</p>
      )}

      {importResult && (
        <div className="mb-4 rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-slate-700">
              Import complete: <strong>{importResult.created}</strong> created,{" "}
              <strong>{importResult.skipped_duplicates}</strong> duplicate(s) skipped
              {importResult.errors.length > 0 && (
                <>
                  , <strong>{importResult.errors.length}</strong> row(s) with errors
                </>
              )}
              .
            </span>
            <button
              type="button"
              onClick={() => setImportResult(null)}
              className="text-slate-400 hover:text-slate-600"
            >
              ✕
            </button>
          </div>
          {importResult.errors.length > 0 && (
            <ul className="mt-2 list-inside list-disc text-xs text-rose-600">
              {importResult.errors.map((message, i) => (
                <li key={i}>{message}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3">Company</th>
              <th className="px-4 py-3">Industry</th>
              <th className="px-4 py-3">Location</th>
              <th className="px-4 py-3">CSR focus</th>
              <th className="px-4 py-3">Tags</th>
              <th className="px-4 py-3">Contacts</th>
              <th className="px-4 py-3">Lead Score</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading && (
              <tr>
                <td colSpan={9} className="px-4 py-6 text-center text-slate-400">
                  Loading…
                </td>
              </tr>
            )}
            {!loading && companies.length === 0 && (
              <tr>
                <td colSpan={9} className="px-4 py-6 text-center text-slate-400">
                  No saved leads match these filters. Use the &quot;Discover companies&quot; tab to
                  find real companies and save them as leads.
                </td>
              </tr>
            )}
            {!loading &&
              companies.map((company) => (
                <tr key={company.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <Link
                      to={`/companies/${company.id}`}
                      className="font-medium text-emerald-700 hover:underline"
                    >
                      {company.name}
                    </Link>
                    {company.website && (
                      <div className="text-xs text-slate-400">{company.website}</div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-slate-600">{company.industry || "—"}</td>
                  <td className="px-4 py-3 text-slate-600">
                    {[company.city, company.state].filter(Boolean).join(", ") || "—"}
                  </td>
                  <td className="px-4 py-3 text-slate-600">{company.csr_focus || "—"}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      {company.tags.length === 0
                        ? "—"
                        : company.tags.map((t) => (
                            <span
                              key={t.id}
                              className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600"
                            >
                              {t.name}
                            </span>
                          ))}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-slate-600">{company.contact_count}</td>
                  <td className="px-4 py-3">
                    {company.lead_score ? (
                      <span
                        className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${
                          PRIORITY_STYLES[company.lead_score.priority] ?? "bg-slate-100 text-slate-600"
                        }`}
                      >
                        {company.lead_score.score}/100 · {company.lead_score.priority}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={company.status} />
                  </td>
                  <td className="px-4 py-3 text-right">
                    <FindContactsButton company={company} onSaved={reload} variant="small" />
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>

      <div className="mt-4 flex items-center justify-between">
        <span className="text-sm text-slate-500">
          {loading ? "Loading…" : `Showing ${companies.length ? page * PAGE_SIZE + 1 : 0}–${page * PAGE_SIZE + companies.length}`}
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0 || loading}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            ← Previous
          </button>
          <button
            type="button"
            onClick={() => setPage((p) => p + 1)}
            disabled={companies.length < PAGE_SIZE || loading}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Next →
          </button>
        </div>
      </div>

      {showForm && (
        <CompanyForm onClose={() => setShowForm(false)} onSubmit={handleCreate} />
      )}
    </div>
  );
}
