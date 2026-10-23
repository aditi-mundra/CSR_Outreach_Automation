import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  cancelFollowup,
  getCompany,
  getEmail,
  getEmailAccount,
  getEmailSettings,
  listEmails,
  listFollowups,
  listMeetings,
  syncEmail,
  updateMeeting,
} from "../api/client";
import EmailComposer from "../components/EmailComposer";
import Modal from "../components/Modal";
import ReplyClassification from "../components/ReplyClassification";
import { EMAIL_STATUS_STYLES, THREAD_STATUS_STYLES } from "../constants";
import { formatDateTime, useEmailMeta } from "../utils/emailMeta";

const TABS = [
  { key: "drafts", label: "Drafts" },
  { key: "sent", label: "Sent" },
  { key: "replies", label: "Replies" },
  { key: "followups", label: "Follow-ups" },
  { key: "meetings", label: "Meetings" },
];

function load(tab) {
  switch (tab) {
    case "drafts":
      return Promise.all([listEmails({ status: "draft" }), listEmails({ status: "failed" })]).then(([a, b]) => [...b, ...a]);
    case "sent":
      return listEmails({ status: "sent", direction: "outbound" });
    case "replies":
      return listEmails({ direction: "inbound", status: "received" });
    case "followups":
      return listFollowups();
    default:
      return listMeetings();
  }
}

function EmailRow({ email, meta, onOpen, onChanged }) {
  const when = email.received_at || email.sent_at || email.updated_at;
  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${EMAIL_STATUS_STYLES[email.status] ?? ""}`}>
          {email.direction === "inbound" ? "reply" : email.status}
        </span>
        <button type="button" onClick={() => onOpen(email)} className="min-w-0 flex-1 truncate text-left text-sm font-medium text-slate-900 hover:text-emerald-700">
          {email.subject || "(no subject)"}
        </button>
        {email.thread_status && (
          <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${THREAD_STATUS_STYLES[email.thread_status] ?? ""}`}>
            {meta?.thread_statuses?.[email.thread_status] ?? email.thread_status}
          </span>
        )}
        <span className="text-xs text-slate-400">{formatDateTime(when)}</span>
      </div>
      <p className="mt-0.5 text-xs text-slate-500">
        <Link to={`/companies/${email.company_id}`} className="text-emerald-700 hover:underline">
          {email.company_name}
        </Link>
        {email.direction === "inbound"
          ? ` · from ${email.from_name || email.from_email}`
          : email.to_email
            ? ` · to ${email.contact_name || email.to_name || ""} <${email.to_email}>`
            : " · no recipient yet"}
      </p>
      {email.status === "failed" && <p className="mt-0.5 text-xs text-rose-600">{email.error}</p>}
      {email.direction === "inbound" && <ReplyClassification email={email} meta={meta} onChanged={onChanged} />}
    </li>
  );
}

export default function EmailsPage() {
  const meta = useEmailMeta();
  const [params, setParams] = useSearchParams();
  const tab = TABS.some((t) => t.key === params.get("tab")) ? params.get("tab") : "drafts";
  const [rows, setRows] = useState({ tab: null, items: [] });
  const [account, setAccount] = useState(null);
  const [settings, setSettings] = useState(null);
  const [open, setOpen] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState(null);

  const reload = useCallback(() => {
    load(tab)
      .then((items) => setRows({ tab, items }))
      .catch((err) => setError(err.message));
  }, [tab]);

  useEffect(() => {
    reload();
  }, [reload]);

  useEffect(() => {
    getEmailAccount().then(setAccount).catch(() => {});
    getEmailSettings().then(setSettings).catch(() => {});
  }, []);

  const openEmail = async (email) => {
    try {
      const company = await getCompany(email.company_id);
      setOpen({ email, contacts: company.contacts });
    } catch (err) {
      setError(err.message);
    }
  };

  const checkReplies = async () => {
    setSyncing(true);
    setNotice(null);
    setError(null);
    try {
      const result = await syncEmail();
      const parts = [];
      if (!result.connected) parts.push("No Gmail account connected - only due follow-up drafts were prepared.");
      else parts.push(`Checked ${result.threads_checked} conversation(s): ${result.new_replies} new repl${result.new_replies === 1 ? "y" : "ies"}`);
      if (result.bounces) parts.push(`${result.bounces} bounce(s)`);
      if (result.followups_drafted) parts.push(`${result.followups_drafted} follow-up draft(s) ready to review`);
      if (result.errors.length) parts.push(`problems: ${result.errors.join("; ")}`);
      setNotice(parts.join(" · "));
      reload();
      getEmailAccount().then(setAccount).catch(() => {});
    } catch (err) {
      setError(err.message);
    } finally {
      setSyncing(false);
    }
  };

  const items = rows.tab === tab ? rows.items : null;
  const connected = account?.account?.status === "connected";

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <header className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Emails</h1>
          <p className="text-sm text-slate-500">
            {account
              ? connected
                ? `Sending as ${account.account.email_address}. Nothing is sent without your approval.`
                : "No Gmail account connected - drafts work, sending needs Gmail."
              : "Drafts, sent emails, replies and follow-ups across all companies."}{" "}
            {!connected && account && (
              <Link to="/settings" className="font-medium text-emerald-700 hover:underline">
                Connect Gmail →
              </Link>
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={checkReplies}
          disabled={syncing}
          className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-60"
        >
          {syncing ? "Checking…" : "Check for replies"}
        </button>
      </header>

      {notice && <p className="mb-4 rounded-lg bg-sky-50 px-4 py-2 text-sm text-sky-800">{notice}</p>}
      {error && <p className="mb-4 rounded-lg bg-rose-50 px-4 py-2 text-sm text-rose-700">{error}</p>}

      <div className="mb-4 flex gap-1 overflow-x-auto border-b border-slate-200">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setParams({ tab: t.key })}
            className={`-mb-px whitespace-nowrap border-b-2 px-4 py-2 text-sm font-medium ${tab === t.key ? "border-emerald-600 text-emerald-700" : "border-transparent text-slate-500 hover:text-slate-700"}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        {items === null && <p className="px-4 py-6 text-center text-sm text-slate-400">Loading…</p>}
        {items?.length === 0 && (
          <p className="px-4 py-6 text-center text-sm text-slate-400">
            Nothing here yet. Generate emails from a company&apos;s page or a contact&apos;s profile.
          </p>
        )}
        {items && ["drafts", "sent", "replies"].includes(tab) && (
          <ul className="divide-y divide-slate-100">
            {items.map((email) => (
              <EmailRow key={email.id} email={email} meta={meta} onOpen={openEmail} onChanged={reload} />
            ))}
          </ul>
        )}
        {items && tab === "followups" && (
          <ul className="divide-y divide-slate-100">
            {items.map((f) => {
              const overdue = ["scheduled", "drafted"].includes(f.status) && f.due_date < new Date().toISOString().slice(0, 10);
              return (
                <li key={f.id} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
                  <span className={`font-medium ${overdue ? "text-rose-600" : "text-slate-700"}`}>{f.due_date}</span>
                  <Link to={`/companies/${f.company_id}`} className="text-emerald-700 hover:underline">
                    {f.company_name}
                  </Link>
                  <span className="text-slate-500">{f.contact_name || ""}</span>
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                    {f.status === "drafted" ? "draft ready" : f.status}
                    {f.cancel_reason ? ` - ${f.cancel_reason}` : ""}
                  </span>
                  <span className="ml-auto flex gap-3">
                    {f.status === "drafted" && f.draft_email_id && (
                      <button
                        type="button"
                        onClick={async () => openEmail(await getEmail(f.draft_email_id))}
                        className="text-xs font-medium text-emerald-700 hover:underline"
                      >
                        Review draft
                      </button>
                    )}
                    {["scheduled", "drafted"].includes(f.status) && (
                      <button type="button" onClick={() => cancelFollowup(f.id).then(reload)} className="text-xs text-slate-400 hover:text-rose-600">
                        Cancel
                      </button>
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
        {items && tab === "meetings" && (
          <ul className="divide-y divide-slate-100">
            {items.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
                <span className="font-medium text-slate-900">{m.title}</span>
                <Link to={`/companies/${m.company_id}`} className="text-emerald-700 hover:underline">
                  {m.company_name}
                </Link>
                <span className="text-slate-500">{m.scheduled_at ? formatDateTime(m.scheduled_at) : "date TBC"}</span>
                {m.location && <span className="text-slate-500">{m.location}</span>}
                <select
                  value={m.status}
                  onChange={(e) => updateMeeting(m.id, { status: e.target.value }).then(reload)}
                  className="ml-auto rounded-lg border border-slate-300 px-2 py-1 text-xs"
                >
                  {(meta?.meeting_statuses ?? ["requested", "scheduled", "completed", "cancelled"]).map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </li>
            ))}
          </ul>
        )}
      </div>

      {open && (
        <Modal title={open.email.direction === "inbound" ? "Reply" : "Email"} onClose={() => setOpen(null)} size="wide">
          <EmailComposer
            key={open.email.id}
            email={open.email}
            contacts={open.contacts}
            account={account}
            settings={settings}
            onChanged={(email, { open: reopen } = {}) => {
              if (reopen && email) openEmail(email);
              reload();
            }}
            onClose={() => setOpen(null)}
          />
        </Modal>
      )}
    </div>
  );
}
