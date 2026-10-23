import { generateCompanySummary, generateMeetingBrief } from "../api/client";
import AITextCard from "./AITextCard";
import EmailGeneratorPanel from "./EmailGeneratorPanel";

export default function AIPanel({ company, onChanged }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="mb-3 text-sm font-semibold text-slate-900">AI Assistant</h2>
      <div className="space-y-3">
        <AITextCard
          title="Company Summary"
          buttonLabel="Generate summary"
          fetcher={generateCompanySummary}
          companyId={company.id}
        />
        <AITextCard
          title="Meeting Brief"
          buttonLabel="Generate brief"
          fetcher={generateMeetingBrief}
          companyId={company.id}
        />
        <EmailGeneratorPanel companyId={company.id} contacts={company.contacts} onDraftSaved={onChanged} />
      </div>
    </div>
  );
}
