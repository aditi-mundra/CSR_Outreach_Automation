import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getDashboard } from "../api/client";
import StatusBadge from "../components/StatusBadge";
import { timeAgo } from "../utils/time";

// Outreach metrics (GET /api/dashboard -> outreach), grouped so each row
// answers one question. Headline numbers are stat tiles, not charts.
const METRIC_GROUPS = [
  {
    title: "Leads",
    tiles: [
      { key: "total_companies", label: "Total Companies" },
      { key: "saved_leads", label: "Saved Leads", hint: "Open leads - not yet won or lost" },
      { key: "contacts", label: "Contacts" },
    ],
  },
  {
    title: "Emails",
    tiles: [
      { key: "emails_generated", label: "Emails Generated" },
      { key: "emails_sent", label: "Emails Sent" },
      { key: "replies_received", label: "Replies Received" },
      { key: "positive_replies", label: "Positive Replies" },
      { key: "negative_replies", label: "Negative Replies" },
    ],
  },
  {
    title: "Outcomes",
    tiles: [
      { key: "meetings_scheduled", label: "Meetings Scheduled" },
      { key: "proposals_sent", label: "Proposals Sent" },
      { key: "partnerships", label: "Partnerships" },
      { key: "pending_followups", label: "Pending Follow-ups" },
      { key: "overdue_followups", label: "Overdue Follow-ups", alert: true },
    ],
  },
  {
    title: "Rates",
    tiles: [
      { key: "reply_rate", label: "Reply Rate", percent: true, hint: "Conversations with a reply / conversations emailed" },
      { key: "positive_reply_rate", label: "Positive Reply Rate", percent: true, hint: "Replied conversations with a positive reply" },
      { key: "conversion_rate", label: "Conversion Rate", percent: true, hint: "Partnerships / companies contacted" },
    ],
  },
];

function MetricTile({ tile, value }) {
  const shown = value == null ? "—" : tile.percent ? `${value}%` : value.toLocaleString("en-IN");
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" title={tile.hint}>
      <div className={`text-2xl font-semibold ${tile.alert && value > 0 ? "text-rose-700" : "text-slate-900"}`}>{shown}</div>
      <div className="mt-1 text-xs font-medium text-slate-500">{tile.label}</div>
    </div>
  );
}

// One ordered series (companies per stage): a single hue, thin rounded
// bars, values in text ink beside them - no legend needed.
function Pipeline({ stages }) {
  const max = Math.max(1, ...stages.map((s) => s.count));
  const total = stages.reduce((sum, s) => sum + s.count, 0);
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="mb-3 text-sm font-semibold text-slate-900">Pipeline</h2>
      <ul className="space-y-2">
        {stages.map((stage) => (
          <li key={stage.stage} className="grid grid-cols-[5.5rem_1fr_2.5rem] items-center gap-3 text-sm">
            <span className="text-slate-600">{stage.stage}</span>
            <span className="h-3 rounded-full bg-slate-100" title={`${stage.stage}: ${stage.count} compan${stage.count === 1 ? "y" : "ies"}`}>
              <span
                className="block h-3 rounded-full bg-emerald-600"
                style={{ width: stage.count ? `max(${(stage.count / max) * 100}%, 0.75rem)` : 0 }}
              />
            </span>
            <span className="text-right font-medium tabular-nums text-slate-800">{stage.count}</span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-slate-400">
        {total} compan{total === 1 ? "y" : "ies"} · &quot;Replied&quot; = contacted companies with at least one reply
      </p>
    </div>
  );
}

function EmailFollowUps({ items }) {
  const today = new Date().toISOString().slice(0, 10);
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
        <h2 className="text-sm font-semibold text-slate-900">Email follow-ups</h2>
        <Link to="/emails?tab=followups" className="text-xs font-medium text-emerald-700 hover:underline">
          All →
        </Link>
      </div>
      {items.length === 0 ? (
        <p className="px-4 py-3 text-sm text-slate-400">No follow-ups scheduled.</p>
      ) : (
        <ul className="divide-y divide-slate-100">
          {items.map((f) => (
            <li key={f.id} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
              <div className="min-w-0">
                <Link to={`/companies/${f.company_id}`} className="font-medium text-emerald-700 hover:underline">
                  {f.company_name}
                </Link>
                <span className="text-slate-500">
                  {f.contact_name ? ` · ${f.contact_name}` : ""}
                  {f.status === "drafted" ? " · draft ready to review" : ""}
                </span>
              </div>
              <span className={`whitespace-nowrap text-xs font-medium ${f.due_date < today ? "text-rose-600" : "text-slate-500"}`}>
                {f.due_date < today ? "Overdue · " : ""}
                {f.due_date}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function FollowUpList({ items, emptyLabel, dateClass }) {
  if (items.length === 0) {
    return <p className="px-4 py-3 text-sm text-slate-400">{emptyLabel}</p>;
  }
  return (
    <ul className="divide-y divide-slate-100">
      {items.map((item) => (
        <li key={item.id} className="flex items-center justify-between px-4 py-2.5">
          <div>
            <Link
              to={`/companies/${item.id}`}
              className="text-sm font-medium text-emerald-700 hover:underline"
            >
              {item.name}
            </Link>
            <div className="mt-0.5">
              <StatusBadge status={item.status} />
            </div>
          </div>
          <span className={`text-xs font-medium ${dateClass}`}>{item.follow_up_date}</span>
        </li>
      ))}
    </ul>
  );
}

export default function DashboardPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getDashboard()
      .then(setData)
      .catch((err) => setError(err.message));
  }, []);

  if (error) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-8">
        <p className="rounded-lg bg-rose-50 px-4 py-2 text-sm text-rose-700">{error}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-8 text-slate-400">Loading dashboard…</div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-900">Dashboard</h1>
        <p className="text-sm text-slate-500">Outreach from first email to partnership, at a glance.</p>
      </header>

      {data.outreach && (
        <div className="mb-8 space-y-4">
          {METRIC_GROUPS.map((group) => (
            <section key={group.title}>
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">{group.title}</h2>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
                {group.tiles.map((tile) => (
                  <MetricTile key={tile.key} tile={tile} value={data.outreach[tile.key]} />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}

      <div className="mb-8 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Pipeline stages={data.pipeline} />
        <EmailFollowUps items={data.email_followups} />
      </div>

      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Company follow-up dates</h2>

      <div className="mb-8 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <h2 className="border-b border-slate-100 px-4 py-3 text-sm font-semibold text-rose-700">
            Overdue ({data.follow_ups.overdue.length})
          </h2>
          <FollowUpList
            items={data.follow_ups.overdue}
            emptyLabel="No overdue follow-ups."
            dateClass="text-rose-600"
          />
        </div>
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <h2 className="border-b border-slate-100 px-4 py-3 text-sm font-semibold text-amber-700">
            Due Today ({data.follow_ups.due_today.length})
          </h2>
          <FollowUpList
            items={data.follow_ups.due_today}
            emptyLabel="Nothing due today."
            dateClass="text-amber-600"
          />
        </div>
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <h2 className="border-b border-slate-100 px-4 py-3 text-sm font-semibold text-slate-700">
            Upcoming ({data.follow_ups.upcoming.length})
          </h2>
          <FollowUpList
            items={data.follow_ups.upcoming}
            emptyLabel="Nothing upcoming."
            dateClass="text-slate-500"
          />
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <h2 className="border-b border-slate-100 px-4 py-3 text-sm font-semibold text-slate-700">
          Recent Activity
        </h2>
        {data.recent_activity.length === 0 ? (
          <p className="px-4 py-3 text-sm text-slate-400">No activity yet.</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {data.recent_activity.map((entry) => (
              <li key={entry.id} className="flex items-center justify-between px-4 py-2.5">
                <div className="text-sm text-slate-700">
                  <Link
                    to={`/companies/${entry.company_id}`}
                    className="font-medium text-emerald-700 hover:underline"
                  >
                    {entry.company_name}
                  </Link>
                  <span className="text-slate-500"> — {entry.description}</span>
                </div>
                <span className="whitespace-nowrap text-xs text-slate-400">
                  {timeAgo(entry.created_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
