import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  disconnectEmailAccount,
  getAccessToken,
  getEmailAccount,
  getEmailSettings,
  listEmailTemplates,
  resetEmailTemplates,
  setAccessToken,
  startEmailOAuth,
  updateEmailSettings,
  updateEmailTemplate,
} from "../api/client";
import { formatDateTime, useEmailMeta } from "../utils/emailMeta";

const INPUT =
  "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500";
const CARD = "rounded-xl border border-slate-200 bg-white p-5 shadow-sm";

function GmailCard({ status, onChanged, notice }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const gmail = status?.providers.find((p) => p.key === "gmail");
  const account = status?.account;

  const connect = async () => {
    setBusy(true);
    setError(null);
    try {
      const { authorization_url: url } = await startEmailOAuth("gmail");
      window.location.assign(url);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  const disconnect = async () => {
    if (!window.confirm("Disconnect Gmail? Sending and reply tracking stop until you reconnect.")) return;
    setBusy(true);
    try {
      await disconnectEmailAccount();
      onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={CARD}>
      <h2 className="text-base font-semibold text-slate-900">Gmail account</h2>
      <p className="mb-3 text-sm text-slate-500">
        Emails are sent from this account, only when you click <strong>Confirm &amp; send</strong> on a draft. Replies
        to those emails are read to track the conversation.
      </p>
      {notice}
      {!status && <p className="text-sm text-slate-400">Loading…</p>}
      {status && (
        <div className="space-y-3">
          {account ? (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-slate-50 px-3 py-2">
              <div>
                <p className="text-sm font-medium text-slate-900">{account.email_address}</p>
                <p className={`text-xs ${account.status === "connected" ? "text-emerald-700" : "text-rose-600"}`}>
                  {account.status === "connected" ? "Connected" : `Needs reconnecting: ${account.last_error}`}
                  {account.last_sync_at && ` · replies last checked ${formatDateTime(account.last_sync_at)}`}
                </p>
              </div>
              <div className="flex gap-2">
                {account.status !== "connected" && (
                  <button type="button" onClick={connect} disabled={busy} className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50">
                    Reconnect
                  </button>
                )}
                <button type="button" onClick={disconnect} disabled={busy} className="rounded-lg border border-rose-200 px-3 py-1.5 text-sm font-medium text-rose-600 hover:bg-rose-50 disabled:opacity-50">
                  Disconnect
                </button>
              </div>
            </div>
          ) : (
            <button
              type="button"
              onClick={connect}
              disabled={busy || !gmail?.configured || !status.encryption_configured}
              className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy ? "Opening Google…" : "Connect Gmail"}
            </button>
          )}
          {gmail && !gmail.configured && (
            <p className="text-sm text-amber-700">Not set up on the server yet: {gmail.setup_hint}</p>
          )}
          {!status.encryption_configured && (
            <p className="text-sm text-amber-700">
              TOKEN_ENCRYPTION_KEY isn&apos;t set on the server, so Gmail can&apos;t be connected securely yet.
            </p>
          )}
          {gmail && (
            <ul className="list-inside list-disc text-xs text-slate-500">
              {gmail.capabilities.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
              <li>
                Replies are checked{" "}
                {status.sync_minutes > 0 ? `every ${status.sync_minutes} minutes while the app is running` : "only when you click Check for replies"}
                ; at most {status.max_emails_per_hour} emails can be sent per hour.
              </li>
            </ul>
          )}
          {error && <p className="text-sm text-rose-600">{error}</p>}
        </div>
      )}
    </section>
  );
}

function AccessTokenCard({ required }) {
  const [value, setValue] = useState(getAccessToken());
  const [saved, setSaved] = useState(false);
  return (
    <section className={CARD}>
      <h2 className="text-base font-semibold text-slate-900">App access token</h2>
      <p className="mb-3 text-sm text-slate-500">
        {required
          ? "This server requires an access token for connecting Gmail, sending and checking replies. Enter it once; it's kept in this browser only."
          : "Not required on this server. For any deployment reachable from the internet, set APP_ACCESS_TOKEN so only your team can send from the NGO's mailbox."}
      </p>
      <div className="flex gap-2">
        <input
          type="password"
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setSaved(false);
          }}
          placeholder="Access token"
          className={INPUT}
        />
        <button
          type="button"
          onClick={() => {
            setAccessToken(value.trim());
            setSaved(true);
          }}
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          Save
        </button>
      </div>
      {saved && <p className="mt-1 text-xs text-emerald-700">Saved in this browser.</p>}
    </section>
  );
}

function SenderCard() {
  const [values, setValues] = useState(null);
  const [intervals, setIntervals] = useState("");
  const [state, setState] = useState({ saving: false, saved: false, error: null });

  useEffect(() => {
    getEmailSettings()
      .then((data) => {
        setValues(data);
        setIntervals(data.followup_intervals.join(", "));
      })
      .catch((err) => setState((s) => ({ ...s, error: err.message })));
  }, []);

  const save = async (event) => {
    event.preventDefault();
    const days = intervals.split(",").map((d) => Number(d.trim())).filter((d) => d > 0);
    setState({ saving: true, saved: false, error: null });
    try {
      const updated = await updateEmailSettings({
        sender_name: values.sender_name || null,
        signature: values.signature || null,
        followup_intervals: days,
        default_followup_days: Number(values.default_followup_days),
      });
      setValues(updated);
      setIntervals(updated.followup_intervals.join(", "));
      setState({ saving: false, saved: true, error: null });
    } catch (err) {
      setState({ saving: false, saved: false, error: err.message });
    }
  };

  if (!values) return <section className={CARD}>{state.error ? <p className="text-sm text-rose-600">{state.error}</p> : "Loading…"}</section>;

  return (
    <form onSubmit={save} className={`${CARD} space-y-3`}>
      <h2 className="text-base font-semibold text-slate-900">Sender &amp; follow-ups</h2>
      <div>
        <label className="mb-1 block text-xs font-medium text-slate-600">Sender name</label>
        <input
          value={values.sender_name ?? ""}
          onChange={(e) => setValues({ ...values, sender_name: e.target.value })}
          placeholder="e.g. Asha Rao, A Ray of Hope Foundation"
          className={INPUT}
        />
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium text-slate-600">Signature (added to every generated email)</label>
        <textarea
          rows={4}
          value={values.signature ?? ""}
          onChange={(e) => setValues({ ...values, signature: e.target.value })}
          placeholder={"Warm regards,\nAsha Rao\nPartnerships, A Ray of Hope Foundation\n+91 20 1234 5678"}
          className={INPUT}
        />
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-600">Follow-up intervals (days)</label>
          <input value={intervals} onChange={(e) => setIntervals(e.target.value)} placeholder="3, 7, 14, 30" className={INPUT} />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-600">Default follow-up after sending (days)</label>
          <input
            type="number"
            min={1}
            max={365}
            value={values.default_followup_days}
            onChange={(e) => setValues({ ...values, default_followup_days: e.target.value })}
            className={INPUT}
          />
        </div>
      </div>
      {state.error && <p className="text-sm text-rose-600">{state.error}</p>}
      <div className="flex items-center gap-3">
        <button type="submit" disabled={state.saving} className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-60">
          {state.saving ? "Saving…" : "Save"}
        </button>
        {state.saved && <span className="text-sm text-emerald-700">Saved.</span>}
      </div>
    </form>
  );
}

function TemplatesCard() {
  const meta = useEmailMeta();
  const [templates, setTemplates] = useState([]);
  const [selected, setSelected] = useState(null);
  const [draft, setDraft] = useState(null);
  const [message, setMessage] = useState(null);

  useEffect(() => {
    listEmailTemplates()
      .then((rows) => {
        setTemplates(rows);
        setSelected(rows[0]?.id ?? null);
        setDraft(rows[0] ?? null);
      })
      .catch((err) => setMessage(err.message));
  }, []);

  const choose = (id) => {
    setSelected(id);
    setDraft(templates.find((t) => t.id === id));
    setMessage(null);
  };

  const save = async () => {
    try {
      const updated = await updateEmailTemplate(draft.id, { subject: draft.subject, body: draft.body });
      setTemplates(templates.map((t) => (t.id === updated.id ? updated : t)));
      setMessage("Template saved.");
    } catch (err) {
      setMessage(err.message);
    }
  };

  const reset = async () => {
    if (!window.confirm("Restore all templates to the defaults? Your edits will be lost.")) return;
    const rows = await resetEmailTemplates();
    setTemplates(rows);
    setSelected(rows[0]?.id ?? null);
    setDraft(rows[0] ?? null);
    setMessage("Templates restored.");
  };

  return (
    <section className={`${CARD} space-y-3`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-slate-900">Default templates</h2>
        <button type="button" onClick={reset} className="text-xs font-medium text-slate-500 hover:text-slate-700">
          Restore defaults
        </button>
      </div>
      <p className="text-sm text-slate-500">
        Used when AI writing is off or not configured. Placeholders: {"{contact_first_name}"}, {"{contact_name}"},{" "}
        {"{company_name}"}, {"{csr_focus}"}, {"{ngo_name}"}, {"{ngo_work_area}"}, {"{sender_name}"}, {"{signature}"}.
      </p>
      <div className="flex flex-wrap gap-1.5">
        {templates.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => choose(t.id)}
            className={`rounded-full px-3 py-1 text-xs font-medium ${selected === t.id ? "bg-emerald-600 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}
          >
            {meta?.email_types?.[t.email_type] ?? t.name}
          </button>
        ))}
      </div>
      {draft && (
        <>
          <input value={draft.subject} onChange={(e) => setDraft({ ...draft, subject: e.target.value })} className={INPUT} />
          <textarea rows={10} value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} className={INPUT} />
          <button type="button" onClick={save} className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700">
            Save template
          </button>
        </>
      )}
      {message && <p className="text-sm text-slate-600">{message}</p>}
    </section>
  );
}

export default function SettingsPage() {
  const [params, setParams] = useSearchParams();
  const [status, setStatus] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    getEmailAccount().then(setStatus).catch(() => setStatus(null));
  }, [refreshKey]);

  const result = params.get("email");
  const notice = result ? (
    <div
      className={`mb-3 flex items-start justify-between gap-3 rounded-lg px-3 py-2 text-sm ${result === "connected" ? "bg-emerald-50 text-emerald-800" : "bg-rose-50 text-rose-700"}`}
    >
      <span>{result === "connected" ? `Gmail connected: ${params.get("account")}` : params.get("message") || "Gmail couldn't be connected."}</span>
      <button type="button" onClick={() => setParams({})} className="opacity-60 hover:opacity-100">
        ✕
      </button>
    </div>
  ) : null;

  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-8">
      <header>
        <h1 className="text-2xl font-semibold text-slate-900">Settings</h1>
        <p className="text-sm text-slate-500">Email account, sender details, follow-up timing and templates.</p>
      </header>
      <GmailCard status={status} notice={notice} onChanged={() => setRefreshKey((k) => k + 1)} />
      <AccessTokenCard required={status?.access_token_required} />
      <SenderCard />
      <TemplatesCard />
    </div>
  );
}
