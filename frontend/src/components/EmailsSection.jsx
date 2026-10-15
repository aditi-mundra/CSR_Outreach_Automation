import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { generateEmailDraft, getEmailAccount, getEmailSettings, listEmailThreads } from "../api/client";
import { useEmailMeta } from "../utils/emailMeta";
import ConversationCard from "./ConversationCard";
import EmailComposer from "./EmailComposer";
import Modal from "./Modal";

// Outreach emails for a company (or one contact): generate a draft, review
// and send it, and follow each conversation's replies and outcome.
export default function EmailsSection({ company, contacts, contactId, onChanged }) {
  const meta = useEmailMeta();
  const [threads, setThreads] = useState([]);
  const [account, setAccount] = useState(null);
  const [settings, setSettings] = useState(null);
  const [newContactId, setNewContactId] = useState(contactId ?? "");
  const [emailType, setEmailType] = useState("first_outreach");
  const [useAi, setUseAi] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [open, setOpen] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    const filter = contactId ? { contact_id: contactId } : { company_id: company.id };
    listEmailThreads(filter)
      .then(setThreads)
      .catch((err) => setError(err.message));
  }, [company.id, contactId]);

  useEffect(() => {
    load();
    getEmailAccount().then(setAccount).catch(() => {});
    getEmailSettings().then(setSettings).catch(() => {});
  }, [load]);

  const refresh = () => {
    load();
    onChanged?.();
  };

  const generate = async () => {
    setGenerating(true);
    setError(null);
    try {
      const draft = await generateEmailDraft({ companyId: company.id, contactId: newContactId, emailType, useAi });
      setOpen(draft);
      refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setGenerating(false);
    }
  };

  const handleChanged = (email, { open: reopen } = {}) => {
    if (reopen && email) setOpen(email);
    refresh();
  };

  const connected = account?.account?.status === "connected";

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-900">Emails ({threads.length})</h2>
        {account && (
          <span className="text-xs text-slate-500">
            {connected ? (
              <>Sending as {account.account.email_address}</>
            ) : (
              <Link to="/settings" className="text-amber-700 hover:underline">
                Connect Gmail to send →
              </Link>
            )}
          </span>
        )}
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg bg-slate-50 p-2">
        {!contactId && (
          <select
            value={newContactId}
            onChange={(e) => setNewContactId(e.target.value)}
            className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
          >
            <option value="">To… (choose a contact)</option>
            {contacts.map((c) => (
              <option key={c.id} value={c.id} disabled={!c.email}>
                {c.name}
                {c.email ? "" : " (no email)"}
              </option>
            ))}
          </select>
        )}
        <select
          value={emailType}
          onChange={(e) => setEmailType(e.target.value)}
          className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
        >
          {Object.entries(meta?.email_types ?? { first_outreach: "First Outreach" }).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-1.5 text-xs text-slate-600" title="Uses Gemini when configured; otherwise your template">
          <input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} className="accent-emerald-600" />
          Write with AI
        </label>
        <button
          type="button"
          onClick={generate}
          disabled={generating || !newContactId}
          className="ml-auto rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
        >
          {generating ? "Writing…" : "Generate email"}
        </button>
      </div>

      {error && <p className="mb-2 text-sm text-rose-600">{error}</p>}
      {threads.length === 0 && (
        <p className="text-sm text-slate-400">No emails yet. Generate one above - it&apos;s saved as a draft for you to review.</p>
      )}
      <ul className="space-y-3">
        {threads.map((thread) => (
          <ConversationCard
            key={thread.id}
            thread={thread}
            meta={meta}
            settings={settings}
            onOpenEmail={(email) => email && setOpen(email)}
            onChanged={refresh}
          />
        ))}
      </ul>

      {open && (
        <Modal
          title={open.direction === "inbound" ? "Reply" : open.status === "draft" || open.status === "failed" ? "Email draft" : "Sent email"}
          onClose={() => setOpen(null)}
          size="wide"
        >
          <EmailComposer
            key={open.id}
            email={open}
            contacts={contacts}
            account={account}
            settings={settings}
            onChanged={handleChanged}
            onClose={() => setOpen(null)}
          />
        </Modal>
      )}
    </div>
  );
}
