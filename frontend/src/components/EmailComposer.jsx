import { useState } from "react";
import { Link } from "react-router-dom";
import { deleteEmailDraft, duplicateEmail, saveEmailDraft, sendEmail } from "../api/client";
import { EMAIL_STATUS_STYLES } from "../constants";
import { formatDateTime } from "../utils/emailMeta";

const INPUT =
  "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500";

// Edit a draft, then send it in two explicit steps: "Review & send" shows
// exactly what will go out and from which account, "Confirm & send" sends.
// Sent emails and replies open read-only.
export default function EmailComposer({ email, contacts, account, settings, onChanged, onClose }) {
  const editable = email.direction === "outbound" && ["draft", "failed"].includes(email.status);
  const withEmail = contacts.filter((c) => c.email);
  const [contactId, setContactId] = useState(email.contact_id ?? "");
  const [subject, setSubject] = useState(email.subject);
  const [body, setBody] = useState(email.body);
  const [reviewing, setReviewing] = useState(false);
  const [followupDays, setFollowupDays] = useState(settings?.default_followup_days ?? 7);
  const [scheduleFollowup, setScheduleFollowup] = useState(true);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(email.status === "failed" ? `Last attempt failed: ${email.error}` : null);
  const [saved, setSaved] = useState(false);

  const contact = contacts.find((c) => c.id === Number(contactId));
  const toEmail = contact?.email ?? email.to_email ?? "";
  const connected = account?.account?.status === "connected";
  const dirty = subject !== email.subject || body !== email.body || Number(contactId || 0) !== (email.contact_id ?? 0);

  const run = async (label, action) => {
    setBusy(label);
    setError(null);
    try {
      return await action();
    } catch (err) {
      setError(err.message);
      return null;
    } finally {
      setBusy(null);
    }
  };

  const save = () =>
    run("save", async () => {
      const updated = await saveEmailDraft(email.id, { subject, body, contact_id: contactId ? Number(contactId) : null });
      setSaved(true);
      onChanged(updated);
      return updated;
    });

  const send = () =>
    run("send", async () => {
      const sent = await sendEmail(email.id, {
        toEmail,
        subject,
        body,
        followupDays: scheduleFollowup ? Number(followupDays) : null,
      });
      onChanged(sent);
      onClose();
    });

  const remove = () => {
    if (!window.confirm("Delete this draft?")) return;
    run("delete", async () => {
      await deleteEmailDraft(email.id);
      onChanged(null);
      onClose();
    });
  };

  const duplicate = () =>
    run("duplicate", async () => {
      const copy = await duplicateEmail(email.id, contactId ? Number(contactId) : null);
      onChanged(copy, { open: true });
    });

  if (!editable) {
    return (
      <div className="space-y-3 pb-2">
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <span className={`rounded-full px-2 py-0.5 font-medium ${EMAIL_STATUS_STYLES[email.status] ?? ""}`}>
            {email.status}
          </span>
          {email.direction === "inbound" ? (
            <span>
              From {email.from_name ? `${email.from_name} <${email.from_email}>` : email.from_email} ·{" "}
              {formatDateTime(email.received_at)}
            </span>
          ) : (
            <span>
              To {email.to_name ? `${email.to_name} <${email.to_email}>` : email.to_email} · sent{" "}
              {formatDateTime(email.sent_at)} from {email.from_email}
            </span>
          )}
        </div>
        <h3 className="text-base font-semibold text-slate-900">{email.subject}</h3>
        <pre className="max-h-[50vh] overflow-y-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-3 font-sans text-sm text-slate-800">
          {email.body}
        </pre>
        {email.direction === "outbound" && (
          <div className="flex justify-end">
            <button
              type="button"
              onClick={duplicate}
              disabled={busy}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              Duplicate as new draft
            </button>
          </div>
        )}
        {error && <p className="text-sm text-rose-600">{error}</p>}
      </div>
    );
  }

  if (reviewing) {
    return (
      <div className="space-y-4 pb-2">
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          This sends a real email from <strong>{account?.account?.email_address}</strong> to{" "}
          <strong>
            {contact?.name} &lt;{toEmail}&gt;
          </strong>
          . Check it carefully - it can&apos;t be unsent.
        </div>
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Subject</p>
          <p className="text-sm font-semibold text-slate-900">{subject}</p>
        </div>
        <pre className="max-h-[40vh] overflow-y-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-3 font-sans text-sm text-slate-800">
          {body}
        </pre>
        <label className="flex flex-wrap items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={scheduleFollowup}
            onChange={(e) => setScheduleFollowup(e.target.checked)}
            className="accent-emerald-600"
          />
          Remind me to follow up in
          <select
            value={followupDays}
            disabled={!scheduleFollowup}
            onChange={(e) => setFollowupDays(e.target.value)}
            className="rounded-lg border border-slate-300 px-2 py-1 text-sm"
          >
            {(settings?.followup_intervals ?? [3, 7, 14, 30]).map((days) => (
              <option key={days} value={days}>
                {days} days
              </option>
            ))}
          </select>
          <span className="text-xs text-slate-400">(a follow-up draft is prepared then - you still approve it)</span>
        </label>
        {error && <p className="text-sm text-rose-600">{error}</p>}
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={() => setReviewing(false)}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Back to editing
          </button>
          <button
            type="button"
            onClick={send}
            disabled={busy === "send"}
            className="rounded-lg bg-emerald-600 px-4 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-emerald-700 disabled:opacity-60"
          >
            {busy === "send" ? "Sending…" : "Confirm & send"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3 pb-2">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_2fr]">
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-600">To</label>
          <select value={contactId} onChange={(e) => setContactId(e.target.value)} className={INPUT}>
            <option value="">Choose a contact…</option>
            {withEmail.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} - {c.email}
              </option>
            ))}
          </select>
          {withEmail.length === 0 && (
            <p className="mt-1 text-xs text-amber-700">No contact at this company has an email address yet.</p>
          )}
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-600">Subject</label>
          <input value={subject} onChange={(e) => setSubject(e.target.value)} className={INPUT} />
        </div>
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium text-slate-600">Message</label>
        <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={14} className={INPUT} />
        <p className="mt-1 text-xs text-slate-400">
          {email.generated_by === "ai" ? "Drafted by AI" : email.generated_by === "template" ? "From a template" : "Draft"}
          {" - review and edit before sending. Emails are never sent automatically."}
        </p>
      </div>

      {!connected && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
          No mailbox connected - you can save drafts, but sending needs Gmail.{" "}
          <Link to="/settings" className="font-medium underline">
            Connect Gmail in Settings
          </Link>
        </p>
      )}
      {error && <p className="text-sm text-rose-600">{error}</p>}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex gap-2">
          <button
            type="button"
            onClick={remove}
            disabled={busy}
            className="rounded-lg border border-rose-200 px-3 py-1.5 text-sm font-medium text-rose-600 hover:bg-rose-50 disabled:opacity-50"
          >
            Delete draft
          </button>
          <button
            type="button"
            onClick={duplicate}
            disabled={busy}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Duplicate
          </button>
        </div>
        <div className="flex items-center gap-2">
          {saved && !dirty && <span className="text-xs text-emerald-700">Saved</span>}
          <button
            type="button"
            onClick={save}
            disabled={busy || !dirty}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            {busy === "save" ? "Saving…" : "Save draft"}
          </button>
          <button
            type="button"
            onClick={async () => {
              if (dirty && !(await save())) return;
              setReviewing(true);
            }}
            disabled={busy || !connected || !toEmail || !subject.trim() || !body.trim()}
            className="rounded-lg bg-emerald-600 px-4 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Review &amp; send…
          </button>
        </div>
      </div>
    </div>
  );
}
