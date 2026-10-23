import { useState } from "react";
import { overrideClassification } from "../api/client";
import { CLASSIFICATION_STYLES } from "../constants";

const METHOD_LABELS = { ai: "AI", keywords: "Keyword rules", manual: "Set by staff" };

// AI reading of a reply - classification, confidence, reasoning - with a
// manual override that keeps the original reading in the history.
export default function ReplyClassification({ email, meta, onChanged }) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const current = email.classification;
  const labels = meta?.classifications ?? {};

  const override = async (classification) => {
    setSaving(true);
    setError(null);
    try {
      await overrideClassification(email.id, classification);
      setEditing(false);
      onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  if (!current) return <p className="text-xs text-slate-400">Not classified yet.</p>;

  return (
    <div className="mt-2 rounded-lg border border-slate-200 bg-white p-2.5">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span
          className={`rounded-full px-2 py-0.5 font-medium ring-1 ring-inset ${CLASSIFICATION_STYLES[current.classification] ?? ""}`}
        >
          {labels[current.classification] ?? current.classification}
        </span>
        {current.intent && current.intent !== "none" && (
          <span className="rounded-full bg-purple-50 px-2 py-0.5 font-medium text-purple-700">
            {current.intent === "meeting_requested" ? "Asks for a meeting" : "Asks for a proposal"}
          </span>
        )}
        {current.confidence != null && (
          <span className="text-slate-500">{Math.round(current.confidence * 100)}% confidence</span>
        )}
        <span className="text-slate-400">· {METHOD_LABELS[current.method] ?? current.method}</span>
        <button
          type="button"
          onClick={() => setEditing((v) => !v)}
          className="ml-auto font-medium text-emerald-700 hover:underline"
        >
          {editing ? "Cancel" : "Change"}
        </button>
      </div>
      {current.reasoning && <p className="mt-1 text-xs text-slate-600">{current.reasoning}</p>}
      {editing && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {Object.entries(labels).map(([key, label]) => (
            <button
              key={key}
              type="button"
              disabled={saving || key === current.classification}
              onClick={() => override(key)}
              className={`rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset disabled:opacity-40 ${CLASSIFICATION_STYLES[key]}`}
            >
              {label}
            </button>
          ))}
        </div>
      )}
      {email.classification_history.length > 1 && (
        <p className="mt-1 text-[11px] text-slate-400">
          Earlier:{" "}
          {email.classification_history
            .slice(0, -1)
            .map((c) => `${labels[c.classification] ?? c.classification} (${METHOD_LABELS[c.method] ?? c.method})`)
            .join(", ")}
        </p>
      )}
      {error && <p className="mt-1 text-xs text-rose-600">{error}</p>}
    </div>
  );
}
