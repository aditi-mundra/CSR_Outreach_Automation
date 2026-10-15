import { Link } from "react-router-dom";
import { CONTACT_PRIORITIES, confidenceStyle } from "../constants";
import { displayHost } from "../utils/format";
import ProvenanceBadge from "./ProvenanceBadge";

function Field({ label, provenance, children }) {
  return (
    <div className="min-w-0">
      <div className="mb-0.5 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-400">
        {label}
        <ProvenanceBadge provenance={provenance} />
      </div>
      <div className="truncate text-sm text-slate-700">{children}</div>
    </div>
  );
}

const DASH = <span className="text-slate-400">—</span>;

// One person (or shared CSR/HR mailbox) found by contact discovery. Every
// field carries its verified / inferred / unavailable badge.
export default function DiscoveredContactCard({ contact, selected, onToggle, onSave, onForceSave, rowState }) {
  const p = contact.provenance || {};
  const tier = CONTACT_PRIORITIES[contact.priority];
  const savedId = rowState?.savedId ?? contact.saved_contact_id;
  const duplicate = rowState?.duplicate;

  return (
    <li className={`rounded-xl border bg-white p-4 shadow-sm ${selected ? "border-emerald-400" : "border-slate-200"}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <label className="flex min-w-0 flex-1 cursor-pointer items-start gap-3">
          <input
            type="checkbox"
            checked={selected}
            disabled={Boolean(savedId)}
            onChange={onToggle}
            className="mt-1 h-4 w-4 accent-emerald-600"
            aria-label={`Select ${contact.name}`}
          />
          <span className="min-w-0">
            <span className="flex flex-wrap items-center gap-2">
              <span className="text-base font-semibold text-slate-900">{contact.name}</span>
              <ProvenanceBadge provenance={p.name} />
              {tier && (
                <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${tier.className}`}>
                  {tier.label} · {contact.role_category}
                </span>
              )}
            </span>
            <span className="mt-0.5 flex items-center gap-1.5 text-sm text-slate-600">
              {contact.designation || "—"}
              <ProvenanceBadge provenance={p.designation} />
            </span>
          </span>
        </label>

        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <span
            title={contact.confidence_reasons.join("\n")}
            className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${confidenceStyle(contact.confidence)}`}
          >
            Confidence {contact.confidence}%
          </span>
          {savedId ? (
            <Link
              to={`/contacts/${savedId}`}
              className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-100"
            >
              ✓ Saved · Open profile →
            </Link>
          ) : (
            <button
              type="button"
              onClick={onSave}
              disabled={rowState?.saving}
              className="rounded-lg bg-emerald-600 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-60"
            >
              {rowState?.saving ? "Saving…" : "Save contact"}
            </button>
          )}
        </div>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Company" provenance={p.company}>
          {contact.company}
        </Field>
        <Field label="Office location" provenance={p.office_location}>
          {contact.office_location || DASH}
        </Field>
        <Field label="Work email" provenance={p.email}>
          {contact.email ? (
            <a href={`mailto:${contact.email}`} className="text-emerald-700 hover:underline">
              {contact.email}
            </a>
          ) : (
            DASH
          )}
        </Field>
        <Field label="Company phone" provenance={p.phone}>
          {contact.phone || DASH}
        </Field>
        <Field label="LinkedIn" provenance={p.linkedin_url}>
          {contact.linkedin_url ? (
            <a href={contact.linkedin_url} target="_blank" rel="noreferrer" className="text-emerald-700 hover:underline">
              Profile ↗
            </a>
          ) : contact.linkedin_search_url ? (
            <a
              href={contact.linkedin_search_url}
              target="_blank"
              rel="noreferrer"
              title="Opens a LinkedIn people search in a new tab - the app itself never reads LinkedIn"
              className="text-slate-500 underline decoration-slate-300 hover:text-slate-700"
            >
              Search LinkedIn ↗
            </a>
          ) : (
            DASH
          )}
        </Field>
        <Field label="Source" provenance={p.source_url}>
          {contact.source_url ? (
            <a href={contact.source_url} target="_blank" rel="noreferrer" className="text-emerald-700 hover:underline">
              {displayHost(contact.source_url)} ↗
            </a>
          ) : (
            DASH
          )}
        </Field>
      </div>

      {contact.sources.length > 1 && (
        <p className="mt-2 text-xs text-slate-500">
          Also seen on:{" "}
          {contact.sources.slice(1).map((source, i) => (
            <span key={source.url}>
              {i > 0 && " · "}
              <a href={source.url} target="_blank" rel="noreferrer" className="underline decoration-slate-300 hover:text-slate-700">
                {source.label || displayHost(source.url)}
              </a>
            </span>
          ))}
        </p>
      )}

      {duplicate && (
        <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
          <span>
            Already saved as <strong>{duplicate.existing_contact_name}</strong>
            {duplicate.existing_contact_email ? ` (${duplicate.existing_contact_email})` : ""}.
          </span>
          <Link to={`/contacts/${duplicate.existing_contact_id}`} className="font-medium text-amber-900 underline">
            View existing
          </Link>
          <button type="button" onClick={onForceSave} className="font-medium text-amber-900 underline">
            Save anyway
          </button>
        </div>
      )}
      {rowState?.error && <p className="mt-2 text-sm text-rose-600">{rowState.error}</p>}
    </li>
  );
}
