import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { addContactNote, deleteContact, deleteNote, getContactProfile } from "../api/client";
import ActivityTimeline from "../components/ActivityTimeline";
import EmailGeneratorPanel from "../components/EmailGeneratorPanel";
import ProvenanceBadge from "../components/ProvenanceBadge";
import StatusBadge from "../components/StatusBadge";
import { CONTACT_PRIORITIES, confidenceStyle } from "../constants";
import { displayHost } from "../utils/format";

const SOURCE_TYPES = {
  website: "Company website",
  csr_report: "CSR / annual report",
  third_party: "Contact-data provider",
};

function Detail({ label, provenance, showProvenance, children }) {
  return (
    <div className="min-w-0">
      <div className="mb-0.5 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-400">
        {label}
        {showProvenance && <ProvenanceBadge provenance={provenance} />}
      </div>
      <div className="truncate text-sm text-slate-800">{children}</div>
    </div>
  );
}

const DASH = <span className="text-slate-400">—</span>;

function linkedinSearch(contact) {
  const keywords = encodeURIComponent(`${contact.name} ${contact.company.name}`);
  return `https://www.linkedin.com/search/results/people/?keywords=${keywords}`;
}

export default function ContactProfilePage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [contact, setContact] = useState(null);
  const [error, setError] = useState(null);
  const [noteBody, setNoteBody] = useState("");
  const [savingNote, setSavingNote] = useState(false);

  const refresh = useCallback(() => {
    getContactProfile(id)
      .then(setContact)
      .catch((err) => setError(err.message));
  }, [id]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  if (error) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-8">
        <p className="rounded-lg bg-rose-50 px-4 py-2 text-sm text-rose-700">{error}</p>
        <Link to="/contacts" className="mt-4 inline-block text-sm text-emerald-700 hover:underline">
          ← Back to contacts
        </Link>
      </div>
    );
  }
  if (!contact) {
    return <div className="mx-auto max-w-3xl px-4 py-8 text-slate-400">Loading…</div>;
  }

  const p = contact.provenance || {};
  const discovered = contact.origin === "discovery";
  const tier = CONTACT_PRIORITIES[contact.priority];

  const handleAddNote = async (event) => {
    event.preventDefault();
    if (!noteBody.trim()) return;
    setSavingNote(true);
    try {
      await addContactNote(contact.id, noteBody.trim());
      setNoteBody("");
      refresh();
    } finally {
      setSavingNote(false);
    }
  };

  const handleDeleteNote = async (noteId) => {
    await deleteNote(noteId);
    refresh();
  };

  const handleDelete = async () => {
    if (!window.confirm(`Remove ${contact.name}? Notes about them stay on the company.`)) return;
    await deleteContact(contact.id);
    navigate(`/companies/${contact.company.id}`);
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <Link to="/contacts" className="text-sm text-emerald-700 hover:underline">
        ← Back to contacts
      </Link>

      <header className="mt-3 mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold text-slate-900">{contact.name}</h1>
            {tier && (
              <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${tier.className}`}>
                {tier.label} · {contact.role_category}
              </span>
            )}
            {contact.confidence != null && (
              <span
                className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${confidenceStyle(contact.confidence)}`}
              >
                Confidence {contact.confidence}%
              </span>
            )}
          </div>
          <p className="text-sm text-slate-600">{contact.designation || "No designation recorded"}</p>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-sm">
            <Link to={`/companies/${contact.company.id}`} className="font-medium text-emerald-700 hover:underline">
              {contact.company.name}
            </Link>
            <StatusBadge status={contact.company.status} />
          </p>
          <p className="mt-1 text-xs text-slate-400">
            {discovered ? "Saved from contact discovery" : "Added by hand"} on{" "}
            {new Date(contact.created_at).toLocaleDateString()}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {contact.source_url && (
            <a
              href={contact.source_url}
              target="_blank"
              rel="noreferrer"
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              View source ↗
            </a>
          )}
          <a
            href={contact.linkedin_url || linkedinSearch(contact)}
            target="_blank"
            rel="noreferrer"
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
            title={contact.linkedin_url ? "Open LinkedIn profile" : "Search LinkedIn for this person (opens LinkedIn)"}
          >
            {contact.linkedin_url ? "LinkedIn profile ↗" : "Search LinkedIn ↗"}
          </a>
          <button
            type="button"
            onClick={handleDelete}
            className="rounded-lg border border-rose-200 px-3 py-1.5 text-sm font-medium text-rose-600 hover:bg-rose-50"
          >
            Remove contact
          </button>
        </div>
      </header>

      <div className="mb-6 grid grid-cols-1 gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:grid-cols-2 lg:grid-cols-3">
        <Detail label="Company" provenance={p.company} showProvenance={discovered}>
          {contact.company.name}
        </Detail>
        <Detail label="Office location" provenance={p.office_location} showProvenance={discovered}>
          {contact.office_location || DASH}
        </Detail>
        <Detail label="Work email" provenance={p.email} showProvenance={discovered}>
          {contact.email ? (
            <a href={`mailto:${contact.email}`} className="text-emerald-700 hover:underline">
              {contact.email}
            </a>
          ) : (
            DASH
          )}
        </Detail>
        <Detail label="Company phone" provenance={p.phone} showProvenance={discovered}>
          {contact.phone || DASH}
        </Detail>
        <Detail label="LinkedIn" provenance={p.linkedin_url} showProvenance={discovered}>
          {contact.linkedin_url ? (
            <a href={contact.linkedin_url} target="_blank" rel="noreferrer" className="text-emerald-700 hover:underline">
              Profile ↗
            </a>
          ) : (
            DASH
          )}
        </Detail>
        <Detail label="Source" provenance={p.source_url} showProvenance={discovered}>
          {contact.source_url ? (
            <a href={contact.source_url} target="_blank" rel="noreferrer" className="text-emerald-700 hover:underline">
              {displayHost(contact.source_url)} ↗
            </a>
          ) : (
            DASH
          )}
        </Detail>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <EmailGeneratorPanel companyId={contact.company.id} contacts={[contact]} initialContactId={contact.id} />

          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="mb-3 text-sm font-semibold text-slate-900">Notes ({contact.notes.length})</h2>
            <form onSubmit={handleAddNote} className="mb-4 flex gap-2">
              <textarea
                value={noteBody}
                onChange={(e) => setNoteBody(e.target.value)}
                placeholder={`Add a note about ${contact.name} - a call, a reply, their interests…`}
                rows={2}
                className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
              />
              <button
                type="submit"
                disabled={savingNote}
                className="self-start rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-60"
              >
                Add
              </button>
            </form>
            {contact.notes.length === 0 && <p className="text-sm text-slate-400">No notes yet.</p>}
            <ul className="space-y-3">
              {contact.notes.map((note) => (
                <li key={note.id} className="rounded-lg bg-slate-50 p-3">
                  <p className="whitespace-pre-wrap text-sm text-slate-800">{note.body}</p>
                  <div className="mt-1 flex items-center justify-between">
                    <span className="text-xs text-slate-400">{new Date(note.created_at).toLocaleString()}</span>
                    <button
                      type="button"
                      onClick={() => handleDeleteNote(note.id)}
                      className="text-xs text-rose-500 hover:underline"
                    >
                      Delete
                    </button>
                  </div>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-xs text-slate-400">Notes here also appear on the company&apos;s page.</p>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="mb-3 text-sm font-semibold text-slate-900">Where this contact was found</h2>
            {contact.sources.length === 0 ? (
              <p className="text-sm text-slate-400">
                {discovered ? "No source pages recorded." : "Added by hand - no public source recorded."}
              </p>
            ) : (
              <ul className="space-y-2 text-sm">
                {contact.sources.map((source) => (
                  <li key={source.id} className="min-w-0">
                    <a
                      href={source.url}
                      target="_blank"
                      rel="noreferrer"
                      className="block truncate text-emerald-700 hover:underline"
                    >
                      {source.label || source.url} ↗
                    </a>
                    <span className="text-xs text-slate-500">
                      {SOURCE_TYPES[source.source_type] ?? source.source_type}
                      {source.fields ? ` · stated: ${source.fields}` : ""} · found{" "}
                      {new Date(source.found_at).toLocaleDateString()}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
        <div className="space-y-6">
          <ActivityTimeline activity={contact.activity_logs} />
        </div>
      </div>
    </div>
  );
}
