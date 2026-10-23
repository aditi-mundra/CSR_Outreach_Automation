import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { searchContacts } from "../api/client";
import { CONTACT_PRIORITIES, confidenceStyle } from "../constants";

const PAGE_SIZE = 50;

const FIELDS = [
  { key: "company", label: "Company", placeholder: "e.g. Infosys" },
  { key: "name", label: "Name", placeholder: "e.g. Priya" },
  { key: "designation", label: "Designation", placeholder: "e.g. CSR, HR, Regional" },
  { key: "industry", label: "Industry", placeholder: "e.g. Pharma" },
  { key: "state", label: "State", placeholder: "e.g. Maharashtra" },
  { key: "city", label: "City", placeholder: "e.g. Pune" },
];

const INPUT_CLASS =
  "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500";

// Every saved contact across all leads - searchable by company, name,
// designation, industry, state and city.
export default function ContactsPage() {
  const [filters, setFilters] = useState({});
  const [page, setPage] = useState(0);
  const [contacts, setContacts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const timeout = setTimeout(() => {
      setLoading(true);
      searchContacts({ ...filters, skip: page * PAGE_SIZE, limit: PAGE_SIZE })
        .then((rows) => {
          setContacts(rows);
          setError(null);
        })
        .catch((err) => setError(err.message))
        .finally(() => setLoading(false));
    }, 250); // debounce free-text filter typing
    return () => clearTimeout(timeout);
  }, [filters, page]);

  const update = (key) => (event) => {
    setFilters({ ...filters, [key]: event.target.value });
    setPage(0);
  };

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <header className="mb-4">
        <h1 className="text-2xl font-semibold text-slate-900">Contacts</h1>
        <p className="text-sm text-slate-500">
          Decision makers saved across all your leads. Use <strong>Find contacts</strong> on a company to
          discover more.
        </p>
      </header>

      <div className="mb-6 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {FIELDS.map((field) => (
            <div key={field.key}>
              <label className="mb-1 block text-xs font-medium text-slate-600">{field.label}</label>
              <input
                type="text"
                value={filters[field.key] ?? ""}
                onChange={update(field.key)}
                placeholder={field.placeholder}
                className={INPUT_CLASS}
              />
            </div>
          ))}
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">Priority</label>
            <select value={filters.priority ?? ""} onChange={update("priority")} className={INPUT_CLASS}>
              <option value="">Any priority</option>
              {Object.entries(CONTACT_PRIORITIES).map(([value, tier]) => (
                <option key={value} value={value}>
                  {tier.label} · {tier.group}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-end">
            <button
              type="button"
              onClick={() => {
                setFilters({});
                setPage(0);
              }}
              className="text-sm font-medium text-slate-500 hover:text-slate-700"
            >
              Clear filters
            </button>
          </div>
        </div>
      </div>

      {error && <p className="mb-4 rounded-lg bg-rose-50 px-4 py-2 text-sm text-rose-700">{error}</p>}

      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3">Contact</th>
              <th className="px-4 py-3">Company</th>
              <th className="px-4 py-3">Location</th>
              <th className="px-4 py-3">Work email / phone</th>
              <th className="px-4 py-3">Priority</th>
              <th className="px-4 py-3">Confidence</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-slate-400">
                  Loading…
                </td>
              </tr>
            )}
            {!loading && contacts.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-slate-400">
                  No contacts match. Open a saved lead and click &quot;Find contacts&quot; to discover its CSR
                  decision makers.
                </td>
              </tr>
            )}
            {!loading &&
              contacts.map((contact) => {
                const tier = CONTACT_PRIORITIES[contact.priority];
                return (
                  <tr key={contact.id} className="hover:bg-slate-50">
                    <td className="px-4 py-3">
                      <Link to={`/contacts/${contact.id}`} className="font-medium text-emerald-700 hover:underline">
                        {contact.name}
                      </Link>
                      <div className="text-xs text-slate-500">{contact.designation || "—"}</div>
                    </td>
                    <td className="px-4 py-3">
                      <Link to={`/companies/${contact.company_id}`} className="text-slate-700 hover:underline">
                        {contact.company_name}
                      </Link>
                      {contact.company_industry && (
                        <div className="text-xs text-slate-400">{contact.company_industry}</div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-600">
                      {contact.office_location ||
                        [contact.company_city, contact.company_state].filter(Boolean).join(", ") ||
                        "—"}
                    </td>
                    <td className="px-4 py-3 text-slate-600">
                      <div>{contact.email || "—"}</div>
                      {contact.phone && <div className="text-xs text-slate-400">{contact.phone}</div>}
                    </td>
                    <td className="px-4 py-3">
                      {tier ? (
                        <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${tier.className}`}>
                          {tier.label}
                        </span>
                      ) : (
                        <span className="text-xs text-slate-400">Manual</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {contact.confidence != null ? (
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${confidenceStyle(contact.confidence)}`}
                        >
                          {contact.confidence}%
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                );
              })}
          </tbody>
        </table>
      </div>

      <div className="mt-4 flex items-center justify-end gap-2">
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
          disabled={contacts.length < PAGE_SIZE || loading}
          className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Next →
        </button>
      </div>
    </div>
  );
}
