import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { deleteCompany, getCompany } from "../api/client";
import StatusBadge from "../components/StatusBadge";
import StatusPanel from "../components/StatusPanel";
import ContactsSection from "../components/ContactsSection";
import NotesSection from "../components/NotesSection";
import DiscoverContactsPanel from "../components/DiscoverContactsPanel";
import LeadScoreBadge from "../components/LeadScoreBadge";
import AIPanel from "../components/AIPanel";
import TagsSection from "../components/TagsSection";
import DocumentsSection from "../components/DocumentsSection";
import ProposalsSection from "../components/ProposalsSection";
import ActivityTimeline from "../components/ActivityTimeline";

export default function CompanyDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [company, setCompany] = useState(null);
  const [error, setError] = useState(null);

  const refresh = useCallback(() => {
    getCompany(id)
      .then(setCompany)
      .catch((err) => setError(err.message));
  }, [id]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleDelete = async () => {
    if (!window.confirm(`Delete ${company.name}? This also removes its contacts and notes.`)) {
      return;
    }
    await deleteCompany(id);
    navigate("/");
  };

  if (error) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-8">
        <p className="rounded-lg bg-rose-50 px-4 py-2 text-sm text-rose-700">{error}</p>
        <Link to="/" className="mt-4 inline-block text-sm text-emerald-700 hover:underline">
          ← Back to companies
        </Link>
      </div>
    );
  }

  if (!company) {
    return <div className="mx-auto max-w-3xl px-4 py-8 text-slate-400">Loading…</div>;
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <Link to="/" className="text-sm text-emerald-700 hover:underline">
        ← Back to companies
      </Link>

      <header className="mt-3 mb-6 flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold text-slate-900">{company.name}</h1>
            <StatusBadge status={company.status} />
          </div>
          <p className="text-sm text-slate-500">
            {[company.industry, company.city, company.state].filter(Boolean).join(" · ") || "—"}
          </p>
          {company.website && (
            <a
              href={company.website}
              target="_blank"
              rel="noreferrer"
              className="text-sm text-emerald-700 hover:underline"
            >
              {company.website}
            </a>
          )}
          {company.csr_report_url && (
            <a
              href={company.csr_report_url}
              target="_blank"
              rel="noreferrer"
              className="block text-sm text-emerald-700 hover:underline"
            >
              CSR report ↗
            </a>
          )}
          <div className="mt-2">
            <LeadScoreBadge companyId={company.id} leadScore={company.lead_score} />
          </div>
          <div className="mt-3">
            <TagsSection companyId={company.id} tags={company.tags} onChanged={refresh} />
          </div>
        </div>
        <button
          type="button"
          onClick={handleDelete}
          className="rounded-lg border border-rose-200 px-3 py-1.5 text-sm font-medium text-rose-600 hover:bg-rose-50"
        >
          Delete company
        </button>
      </header>

      <div className="mb-6 grid grid-cols-2 gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:grid-cols-4">
        <Stat label="CSR focus" value={company.csr_focus || "—"} />
        <Stat
          label="CSR spending"
          value={company.csr_spending != null ? `₹${company.csr_spending.toLocaleString()}` : "—"}
        />
        <Stat
          label="Revenue"
          value={company.revenue != null ? `₹${company.revenue.toLocaleString()}` : "—"}
        />
        <Stat
          label="Employees"
          value={company.employee_count != null ? company.employee_count.toLocaleString() : "—"}
        />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <ContactsSection companyId={company.id} contacts={company.contacts} onChanged={refresh} />
          <DiscoverContactsPanel company={company} onChanged={refresh} />
          <NotesSection companyId={company.id} notes={company.notes} onChanged={refresh} />
          <ProposalsSection companyId={company.id} proposals={company.proposals} onChanged={refresh} />
          <DocumentsSection companyId={company.id} documents={company.documents} onChanged={refresh} />
        </div>
        <div className="space-y-6">
          <StatusPanel company={company} onUpdated={setCompany} />
          <AIPanel company={company} />
          <ActivityTimeline activity={company.activity_logs} />
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-slate-400">{label}</p>
      <p className="text-sm font-medium text-slate-800">{value}</p>
    </div>
  );
}
