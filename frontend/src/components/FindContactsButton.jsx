import { useState } from "react";
import ContactDiscoveryPanel from "./ContactDiscoveryPanel";
import Modal from "./Modal";

const VARIANTS = {
  primary:
    "rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-emerald-700",
  secondary:
    "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50",
  small: "rounded-lg border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50",
};

// "Find contacts" - used on the company detail page, each saved-lead row and
// each Discover result. `company` is a saved lead ({ id, ... }) or a
// discovery result; `savePayload` (discovery results only) is what gets
// saved as the lead if a contact is saved before the company is.
export default function FindContactsButton({ company, savePayload, onSaved, variant = "secondary", label = "Find contacts" }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className={VARIANTS[variant]}>
        {label}
      </button>
      {open && (
        <Modal title={`Find contacts · ${company.name}`} onClose={() => setOpen(false)} size="wide">
          <ContactDiscoveryPanel company={company} savePayload={savePayload} onSaved={onSaved} />
        </Modal>
      )}
    </>
  );
}
