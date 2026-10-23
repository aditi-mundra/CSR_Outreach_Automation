import { PROVENANCE_STYLES } from "../constants";

// How much to trust a discovered value: stated by a public source
// (verified), worked out by the app (inferred), or not published anywhere
// we can reach (unavailable). Hover shows the source.
function provenanceTitle(provenance) {
  if (!provenance) return "";
  if (provenance.status === "unavailable") return "No public source we can reach publishes this.";
  const prefix = provenance.status === "inferred" ? "Worked out by the app from" : "From";
  return `${prefix} ${provenance.source || "a public source"} - please double-check before relying on it.`;
}

export default function ProvenanceBadge({ provenance }) {
  const style = PROVENANCE_STYLES[provenance?.status] ?? PROVENANCE_STYLES.unavailable;
  const content = (
    <span
      title={provenanceTitle(provenance)}
      className={`inline-flex items-center rounded-full px-1.5 py-px text-[10px] font-medium ring-1 ring-inset ${style.className}`}
    >
      {style.label}
    </span>
  );
  if (provenance?.source_url) {
    return (
      <a href={provenance.source_url} target="_blank" rel="noreferrer" className="hover:opacity-80">
        {content}
      </a>
    );
  }
  return content;
}
