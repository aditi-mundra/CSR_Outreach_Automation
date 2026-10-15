export const LEAD_STATUSES = [
  "New",
  "Contacted",
  "Follow-up",
  "Meeting",
  "Proposal Sent",
  "Successful",
  "Not Interested",
];

export const STATUS_STYLES = {
  New: "bg-slate-100 text-slate-700",
  Contacted: "bg-blue-100 text-blue-700",
  "Follow-up": "bg-amber-100 text-amber-700",
  Meeting: "bg-purple-100 text-purple-700",
  "Proposal Sent": "bg-indigo-100 text-indigo-700",
  Successful: "bg-emerald-100 text-emerald-700",
  "Not Interested": "bg-rose-100 text-rose-700",
};

export const PRIORITY_STYLES = {
  High: "bg-emerald-100 text-emerald-700",
  Medium: "bg-amber-100 text-amber-700",
  Low: "bg-slate-100 text-slate-600",
};

export const EMAIL_TYPES = [
  { value: "first_outreach", label: "First Outreach" },
  { value: "follow_up", label: "Follow-up" },
  { value: "meeting_request", label: "Meeting Request" },
  { value: "thank_you", label: "Thank You" },
];

export const PROPOSAL_STAGES = ["Requested", "Drafting", "Sent", "Approved", "Rejected"];

export const PROPOSAL_STAGE_STYLES = {
  Requested: "bg-slate-100 text-slate-700",
  Drafting: "bg-amber-100 text-amber-700",
  Sent: "bg-indigo-100 text-indigo-700",
  Approved: "bg-emerald-100 text-emerald-700",
  Rejected: "bg-rose-100 text-rose-700",
};

// Discovery provenance: how much to trust a discovered value.
export const PROVENANCE_STYLES = {
  verified: { label: "Verified", className: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  inferred: { label: "Inferred", className: "bg-amber-50 text-amber-700 ring-amber-200" },
  unavailable: { label: "Unavailable", className: "bg-slate-50 text-slate-500 ring-slate-200" },
};

// Email automation: conversation outcomes (labels come from /api/email/meta;
// these are just colours) and reply classifications.
export const THREAD_STATUS_STYLES = {
  draft: "bg-slate-100 text-slate-600",
  awaiting_reply: "bg-blue-50 text-blue-700",
  replied: "bg-sky-100 text-sky-700",
  positive: "bg-emerald-100 text-emerald-700",
  neutral: "bg-slate-100 text-slate-700",
  negative: "bg-rose-100 text-rose-700",
  needs_follow_up: "bg-amber-100 text-amber-700",
  meeting_requested: "bg-purple-100 text-purple-700",
  meeting_scheduled: "bg-purple-100 text-purple-800",
  proposal_requested: "bg-indigo-100 text-indigo-700",
  proposal_sent: "bg-indigo-100 text-indigo-800",
  partnership_confirmed: "bg-emerald-200 text-emerald-900",
  closed: "bg-slate-200 text-slate-700",
};

export const CLASSIFICATION_STYLES = {
  positive: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  negative: "bg-rose-50 text-rose-700 ring-rose-200",
  neutral: "bg-slate-50 text-slate-600 ring-slate-200",
  needs_follow_up: "bg-amber-50 text-amber-700 ring-amber-200",
};

export const EMAIL_STATUS_STYLES = {
  draft: "bg-slate-100 text-slate-600",
  sent: "bg-blue-50 text-blue-700",
  failed: "bg-rose-100 text-rose-700",
  received: "bg-emerald-50 text-emerald-700",
  bounce: "bg-rose-50 text-rose-600",
};

// Contact discovery priority tiers (backend: app/contact_discovery/roles.py).
export const CONTACT_PRIORITIES = {
  1: { label: "Priority 1", group: "CSR & Sustainability", className: "bg-emerald-100 text-emerald-800" },
  2: { label: "Priority 2", group: "HR & Communications", className: "bg-sky-100 text-sky-800" },
  3: { label: "Priority 3", group: "Regional & Operations", className: "bg-slate-100 text-slate-700" },
};

export function confidenceStyle(score) {
  if (score >= 70) return "bg-emerald-50 text-emerald-700 ring-emerald-200";
  if (score >= 45) return "bg-amber-50 text-amber-700 ring-amber-200";
  return "bg-slate-50 text-slate-600 ring-slate-200";
}
