import { useSearchParams } from "react-router-dom";
import DiscoverCompaniesView from "../components/DiscoverCompaniesView";
import SavedLeadsView from "../components/SavedLeadsView";

const TABS = [
  { key: "discover", label: "Discover companies" },
  { key: "saved", label: "Saved leads" },
];

export default function CompaniesPage() {
  const [params, setParams] = useSearchParams();
  const view = params.get("view") === "saved" ? "saved" : "discover";

  const selectTab = (key) => {
    // Each tab owns its own URL state; switching starts the other tab fresh.
    setParams(key === "saved" ? { view: "saved" } : {});
  };

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <header className="mb-4">
        <h1 className="text-2xl font-semibold text-slate-900">Companies</h1>
        <p className="text-sm text-slate-500">
          Find real companies for CSR outreach and keep track of the ones you&apos;ve saved.
        </p>
      </header>

      <div className="mb-6 flex gap-1 border-b border-slate-200">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => selectTab(tab.key)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${
              view === tab.key
                ? "border-emerald-600 text-emerald-700"
                : "border-transparent text-slate-500 hover:text-slate-700"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {view === "saved" ? <SavedLeadsView /> : <DiscoverCompaniesView />}
    </div>
  );
}
