import { useState } from "react";
import { scrapeCompany, enrichCompany, addContact } from "../api/client";

export default function DiscoverContactsPanel({ company, onChanged }) {
  const [candidates, setCandidates] = useState([]);
  const [names, setNames] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [notConfigured, setNotConfigured] = useState(false);
  const [searched, setSearched] = useState(false);
  const [duplicates, setDuplicates] = useState({});

  const hasWebsite = Boolean(company.website);

  const reset = () => {
    setError(null);
    setNotConfigured(false);
    setCandidates([]);
    setNames({});
    setDuplicates({});
  };

  const runScrape = async () => {
    reset();
    setLoading(true);
    try {
      const result = await scrapeCompany(company.id);
      setCandidates(result.contacts);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      setSearched(true);
    }
  };

  const runEnrich = async () => {
    reset();
    setLoading(true);
    try {
      const result = await enrichCompany(company.id);
      if (!result.configured) {
        setNotConfigured(true);
      } else {
        setCandidates(result.contacts);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      setSearched(true);
    }
  };

  const handleAdd = async (index, force = false) => {
    const candidate = candidates[index];
    const name = (names[index] ?? candidate.name ?? "").trim();
    if (!name) return;
    try {
      await addContact(
        company.id,
        {
          name,
          designation: candidate.designation,
          email: candidate.email,
          phone: candidate.phone,
          linkedin_url: candidate.linkedin_url,
          source_url: candidate.source_url,
        },
        { force },
      );
    } catch (err) {
      // Re-scanning a site surfaces the same email again, so a duplicate
      // here is routine - warn on the row and let staff decide, rather
      // than failing the whole panel.
      if (err.status === 409 && err.detail?.existing_contact_id) {
        setDuplicates({ ...duplicates, [index]: err.detail });
      } else {
        setError(err.message);
      }
      return;
    }
    // Removing a candidate shifts the rest down, so index-keyed warnings
    // would end up pointing at the wrong row - clear them all instead.
    setDuplicates({});
    setCandidates(candidates.filter((_, i) => i !== index));
    onChanged();
  };

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-900">Find CSR contacts</h2>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={runScrape}
            disabled={loading || !hasWebsite}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Scan website
          </button>
          <button
            type="button"
            onClick={runEnrich}
            disabled={loading || !hasWebsite}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Enrich (Hunter/Apollo)
          </button>
        </div>
      </div>

      {!hasWebsite && (
        <p className="text-sm text-slate-400">
          Add a website to this company to enable contact discovery.
        </p>
      )}

      {loading && <p className="text-sm text-slate-400">Searching…</p>}
      {error && <p className="text-sm text-rose-600">{error}</p>}
      {notConfigured && (
        <p className="text-sm text-slate-400">
          Enrichment isn't configured on the backend yet — set HUNTER_API_KEY or
          APOLLO_API_KEY.
        </p>
      )}
      {!loading && searched && candidates.length === 0 && !notConfigured && !error && (
        <p className="text-sm text-slate-400">No public contacts found.</p>
      )}

      <ul className="space-y-2">
        {candidates.map((candidate, index) => (
          <li key={index} className="rounded-lg bg-slate-50 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <input
                value={names[index] ?? candidate.name ?? ""}
                onChange={(e) => setNames({ ...names, [index]: e.target.value })}
                placeholder="Name (required to add)"
                className="min-w-40 flex-1 rounded-lg border border-slate-300 px-2 py-1 text-sm"
              />
              <button
                type="button"
                onClick={() => handleAdd(index)}
                disabled={!(names[index] ?? candidate.name ?? "").trim()}
                className="rounded-lg bg-emerald-600 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
              >
                Add contact
              </button>
            </div>
            <p className="mt-1 text-xs text-slate-500">
              {[candidate.designation, candidate.email, candidate.phone]
                .filter(Boolean)
                .join(" · ") || "—"}
            </p>
            {candidate.linkedin_url && (
              <a
                href={candidate.linkedin_url}
                target="_blank"
                rel="noreferrer"
                className="text-xs text-emerald-700 hover:underline"
              >
                LinkedIn
              </a>
            )}
            {candidate.source_url && (
              <p className="truncate text-xs text-slate-400">Source: {candidate.source_url}</p>
            )}
            {duplicates[index] && (
              <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
                Already saved as <strong>{duplicates[index].existing_contact_name}</strong>
                {duplicates[index].existing_contact_email
                  ? ` (${duplicates[index].existing_contact_email})`
                  : ""}
                .
                <button
                  type="button"
                  onClick={() => handleAdd(index, true)}
                  className="ml-2 font-medium text-amber-900 hover:underline"
                >
                  Add anyway
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
