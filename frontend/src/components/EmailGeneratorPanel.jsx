import { useState } from "react";
import { createEmailDraft, generateEmail } from "../api/client";
import { EMAIL_TYPES } from "../constants";

export default function EmailGeneratorPanel({ companyId, contacts, initialContactId = "", onDraftSaved }) {
  const [emailType, setEmailType] = useState(EMAIL_TYPES[0].value);
  const [contactId, setContactId] = useState(initialContactId);
  const [email, setEmail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [notConfigured, setNotConfigured] = useState(false);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);
  const [draftSaved, setDraftSaved] = useState(false);

  // Hand the generated text to the email workflow (review -> send) as a draft.
  const handleSaveDraft = async () => {
    if (!email) return;
    try {
      await createEmailDraft({
        company_id: companyId,
        contact_id: contactId ? Number(contactId) : null,
        email_type: emailType,
        subject: email.subject,
        body: email.body,
      });
      setDraftSaved(true);
      onDraftSaved?.();
    } catch (err) {
      setError(err.message);
    }
  };

  const generate = async () => {
    setLoading(true);
    setError(null);
    setNotConfigured(false);
    setCopied(false);
    setDraftSaved(false);
    try {
      const result = await generateEmail(companyId, {
        emailType,
        contactId: contactId || null,
      });
      if (!result.configured) {
        setNotConfigured(true);
        setEmail(null);
      } else if (!result.subject) {
        setError("Could not generate an email right now. Try again.");
        setEmail(null);
      } else {
        setEmail({ subject: result.subject, body: result.body });
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleCopy = async () => {
    if (!email) return;
    await navigator.clipboard.writeText(`Subject: ${email.subject}\n\n${email.body}`);
    setCopied(true);
  };

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <h3 className="mb-2 text-sm font-medium text-slate-800">AI Email Generator</h3>

      <div className="mb-3 flex flex-wrap gap-2">
        <select
          value={emailType}
          onChange={(e) => setEmailType(e.target.value)}
          className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
        >
          {EMAIL_TYPES.map((type) => (
            <option key={type.value} value={type.value}>
              {type.label}
            </option>
          ))}
        </select>
        <select
          value={contactId}
          onChange={(e) => setContactId(e.target.value)}
          className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
        >
          <option value="">No specific contact</option>
          {contacts.map((contact) => (
            <option key={contact.id} value={contact.id}>
              {contact.name}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={generate}
          disabled={loading}
          className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-60"
        >
          {loading ? "Generating…" : email ? "Regenerate" : "Generate Email"}
        </button>
      </div>

      {error && <p className="text-xs text-rose-600">{error}</p>}
      {notConfigured && (
        <p className="text-xs text-slate-400">
          Email generation needs GEMINI_API_KEY set on the backend.
        </p>
      )}

      {email && (
        <div className="space-y-2">
          <input
            value={email.subject}
            onChange={(e) => setEmail({ ...email, subject: e.target.value })}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium"
          />
          <textarea
            value={email.body}
            onChange={(e) => setEmail({ ...email, body: e.target.value })}
            rows={8}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
          <p className="text-xs text-slate-400">
            This is a draft — review and edit before sending. The app never sends email on its own.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={handleCopy}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
            >
              {copied ? "Copied!" : "Copy Email"}
            </button>
            <button
              type="button"
              onClick={handleSaveDraft}
              disabled={draftSaved}
              className="rounded-lg border border-emerald-300 px-3 py-1.5 text-xs font-medium text-emerald-700 hover:bg-emerald-50 disabled:opacity-60"
            >
              {draftSaved ? "Saved - see Emails" : "Save as draft"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
