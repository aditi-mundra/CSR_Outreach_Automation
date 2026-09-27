import { useState } from "react";
import { Link } from "react-router-dom";
import Modal from "./Modal";

const EMPTY = {
  name: "",
  industry: "",
  city: "",
  state: "",
  website: "",
  csr_report_url: "",
  csr_focus: "",
  csr_spending: "",
  revenue: "",
  employee_count: "",
};

const NUMERIC_FIELDS = new Set(["csr_spending", "revenue", "employee_count"]);

export default function CompanyForm({ onClose, onSubmit }) {
  const [values, setValues] = useState(EMPTY);
  const [error, setError] = useState(null);
  const [duplicate, setDuplicate] = useState(null);
  const [saving, setSaving] = useState(false);

  const handleChange = (key) => (event) => {
    setValues({ ...values, [key]: event.target.value });
    setDuplicate(null);
  };

  const buildPayload = () => {
    const payload = { ...values };
    for (const field of NUMERIC_FIELDS) {
      payload[field] = payload[field] === "" ? null : Number(payload[field]);
    }
    for (const key of Object.keys(payload)) {
      if (payload[key] === "") payload[key] = null;
    }
    return payload;
  };

  const submit = async (force) => {
    setSaving(true);
    setError(null);
    try {
      await onSubmit(buildPayload(), { force });
      setDuplicate(null);
    } catch (err) {
      if (err.status === 409 && err.detail?.existing_company_id) {
        setDuplicate(err.detail);
      } else {
        setError(err.message);
      }
    } finally {
      setSaving(false);
    }
  };

  const handleSubmit = (event) => {
    event.preventDefault();
    if (!values.name.trim()) {
      setError("Company name is required.");
      return;
    }
    submit(false);
  };

  return (
    <Modal title="Add company" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-3">
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-600">
            Company name *
          </label>
          <input
            autoFocus
            value={values.name}
            onChange={handleChange("name")}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">Industry</label>
            <input
              value={values.industry}
              onChange={handleChange("industry")}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">CSR focus</label>
            <input
              value={values.csr_focus}
              onChange={handleChange("csr_focus")}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">City</label>
            <input
              value={values.city}
              onChange={handleChange("city")}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">State</label>
            <input
              value={values.state}
              onChange={handleChange("state")}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </div>
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-slate-600">Website</label>
          <input
            value={values.website}
            onChange={handleChange("website")}
            placeholder="https://"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-slate-600">
            CSR report link
          </label>
          <input
            value={values.csr_report_url}
            onChange={handleChange("csr_report_url")}
            placeholder="https://… (CSR or sustainability report)"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">
              CSR spending (₹)
            </label>
            <input
              type="number"
              value={values.csr_spending}
              onChange={handleChange("csr_spending")}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">Revenue (₹)</label>
            <input
              type="number"
              value={values.revenue}
              onChange={handleChange("revenue")}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">Employees</label>
            <input
              type="number"
              value={values.employee_count}
              onChange={handleChange("employee_count")}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </div>
        </div>

        {error && <p className="text-sm text-rose-600">{error}</p>}

        {duplicate && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            <p>
              A company called <strong>{duplicate.existing_company_name}</strong> already
              exists (same name or website).
            </p>
            <div className="mt-2 flex gap-3">
              <Link
                to={`/companies/${duplicate.existing_company_id}`}
                onClick={onClose}
                className="font-medium text-amber-900 hover:underline"
              >
                View existing company
              </Link>
              <button
                type="button"
                onClick={() => submit(true)}
                disabled={saving}
                className="font-medium text-amber-900 hover:underline disabled:opacity-60"
              >
                Create anyway
              </button>
            </div>
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={saving}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-60"
          >
            {saving ? "Saving…" : "Save company"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
