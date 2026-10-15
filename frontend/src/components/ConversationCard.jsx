import { useState } from "react";
import {
  cancelFollowup,
  createMeeting,
  draftFollowupNow,
  scheduleFollowup,
  updateThreadStatus,
} from "../api/client";
import { EMAIL_STATUS_STYLES, THREAD_STATUS_STYLES } from "../constants";
import { formatDateTime } from "../utils/emailMeta";
import ReplyClassification from "./ReplyClassification";

const SMALL_BUTTON =
  "rounded-lg border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50";

// One conversation with one contact: its emails and replies, outcome
// status, follow-ups and meetings.
export default function ConversationCard({ thread, meta, settings, onOpenEmail, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [meetingForm, setMeetingForm] = useState(null);
  const hasSent = thread.emails.some((e) => e.status === "sent");
  const openFollowups = thread.followups.filter((f) => ["scheduled", "drafted"].includes(f.status));
  const statuses = meta?.thread_statuses ?? {};

  const act = async (action) => {
    setBusy(true);
    setError(null);
    try {
      const result = await action();
      onChanged();
      return result;
    } catch (err) {
      setError(err.message);
      return null;
    } finally {
      setBusy(false);
    }
  };

  const saveMeeting = (event) => {
    event.preventDefault();
    act(async () => {
      await createMeeting({
        company_id: thread.company_id,
        thread_id: thread.id,
        title: meetingForm.title,
        scheduled_at: meetingForm.when ? new Date(meetingForm.when).toISOString() : null,
        location: meetingForm.location || null,
      });
      setMeetingForm(null);
    });
  };

  return (
    <li className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-slate-900">{thread.subject || "(no subject)"}</p>
          <p className="text-xs text-slate-500">
            {thread.contact_name ? `${thread.contact_name}${thread.contact_email ? ` · ${thread.contact_email}` : ""}` : "No contact"}
            {thread.last_message_at && ` · last message ${formatDateTime(thread.last_message_at)}`}
          </p>
        </div>
        <select
          value={thread.status}
          disabled={busy || thread.status === "draft"}
          onChange={(e) => act(() => updateThreadStatus(thread.id, e.target.value))}
          className={`rounded-full border-0 px-2.5 py-1 text-xs font-medium ${THREAD_STATUS_STYLES[thread.status] ?? ""}`}
          title="Conversation outcome - updates the company's lead status"
        >
          {Object.entries(statuses).map(([key, label]) => (
            <option key={key} value={key} disabled={key === "draft"}>
              {label}
            </option>
          ))}
        </select>
      </div>

      <ul className="mt-2 space-y-1.5">
        {thread.emails
          .filter((email) => email.status !== "bounce")
          .map((email) => (
            <li key={email.id} className={email.direction === "inbound" ? "ml-4" : ""}>
              <button
                type="button"
                onClick={() => onOpenEmail(email)}
                className="flex w-full items-center gap-2 rounded-lg bg-slate-50 px-2.5 py-1.5 text-left text-sm hover:bg-slate-100"
              >
                <span className="text-slate-400">{email.direction === "inbound" ? "←" : "→"}</span>
                <span className={`rounded-full px-1.5 py-px text-[10px] font-medium ${EMAIL_STATUS_STYLES[email.status] ?? ""}`}>
                  {email.direction === "inbound" ? "reply" : email.status}
                </span>
                <span className="min-w-0 flex-1 truncate text-slate-700">{email.subject}</span>
                <span className="shrink-0 text-xs text-slate-400">
                  {formatDateTime(email.received_at || email.sent_at || email.updated_at)}
                </span>
              </button>
              {email.status === "failed" && <p className="ml-2 mt-0.5 text-xs text-rose-600">{email.error}</p>}
              {email.direction === "inbound" && <ReplyClassification email={email} meta={meta} onChanged={onChanged} />}
            </li>
          ))}
      </ul>

      {(openFollowups.length > 0 || thread.meetings.length > 0) && (
        <ul className="mt-2 space-y-1 text-xs text-slate-600">
          {openFollowups.map((f) => (
            <li key={f.id} className="flex flex-wrap items-center gap-2">
              <span>
                ⏰ Follow-up {f.status === "drafted" ? "draft ready" : "due"} {f.due_date}
              </span>
              {f.status === "drafted" && f.draft_email_id && (
                <button
                  type="button"
                  onClick={() => onOpenEmail(thread.emails.find((e) => e.id === f.draft_email_id))}
                  className="font-medium text-emerald-700 hover:underline"
                >
                  Review draft
                </button>
              )}
              <button type="button" onClick={() => act(() => cancelFollowup(f.id))} className="text-slate-400 hover:text-rose-600">
                Cancel
              </button>
            </li>
          ))}
          {thread.meetings.map((m) => (
            <li key={m.id}>
              📅 {m.title} · {m.scheduled_at ? formatDateTime(m.scheduled_at) : "date TBC"}
              {m.location ? ` · ${m.location}` : ""} ({m.status})
            </li>
          ))}
        </ul>
      )}

      {hasSent && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-slate-100 pt-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => act(async () => onOpenEmail(await draftFollowupNow(thread.id)))}
            className={SMALL_BUTTON}
          >
            Write follow-up
          </button>
          <span className="ml-1 text-xs text-slate-400">Remind in</span>
          {(settings?.followup_intervals ?? [3, 7, 14, 30]).map((days) => (
            <button
              key={days}
              type="button"
              disabled={busy}
              onClick={() => act(() => scheduleFollowup({ thread_id: thread.id, days }))}
              className={SMALL_BUTTON}
              title={`A follow-up draft will be prepared in ${days} days for you to review`}
            >
              {days}d
            </button>
          ))}
          <button
            type="button"
            disabled={busy}
            onClick={() => setMeetingForm(meetingForm ? null : { title: `Meeting with ${thread.contact_name || thread.company_name}`, when: "", location: "" })}
            className={`${SMALL_BUTTON} ml-auto`}
          >
            Schedule meeting
          </button>
        </div>
      )}

      {meetingForm && (
        <form onSubmit={saveMeeting} className="mt-2 grid grid-cols-1 gap-2 rounded-lg bg-slate-50 p-2 sm:grid-cols-3">
          <input
            value={meetingForm.title}
            onChange={(e) => setMeetingForm({ ...meetingForm, title: e.target.value })}
            placeholder="Title"
            required
            className="rounded-lg border border-slate-300 px-2 py-1 text-sm"
          />
          <input
            type="datetime-local"
            value={meetingForm.when}
            onChange={(e) => setMeetingForm({ ...meetingForm, when: e.target.value })}
            className="rounded-lg border border-slate-300 px-2 py-1 text-sm"
          />
          <div className="flex gap-2">
            <input
              value={meetingForm.location}
              onChange={(e) => setMeetingForm({ ...meetingForm, location: e.target.value })}
              placeholder="Place or link"
              className="min-w-0 flex-1 rounded-lg border border-slate-300 px-2 py-1 text-sm"
            />
            <button type="submit" disabled={busy} className="rounded-lg bg-emerald-600 px-3 py-1 text-xs font-medium text-white">
              Save
            </button>
          </div>
        </form>
      )}
      {error && <p className="mt-2 text-xs text-rose-600">{error}</p>}
    </li>
  );
}
