import { useState } from "react";
import { Link } from "react-router-dom";
import { addContact, deleteContact } from "../api/client";
import { CONTACT_PRIORITIES } from "../constants";
import FindContactsButton from "./FindContactsButton";

const EMPTY = { name: "", designation: "", email: "", phone: "", linkedin_url: "" };

export default function ContactsSection({ company, contacts, onChanged }) {
  const companyId = company.id;
  const [showForm, setShowForm] = useState(false);
  const [values, setValues] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [duplicate, setDuplicate] = useState(null);
  const [error, setError] = useState(null);

  const handleChange = (key) => (e) => {
    setValues({ ...values, [key]: e.target.value });
    setDuplicate(null);
  };

  const save = async (force) => {
    setSaving(true);
    setError(null);
    try {
      await addContact(companyId, values, { force });
      setValues(EMPTY);
      setDuplicate(null);
      setShowForm(false);
      onChanged();
    } catch (err) {
      if (err.status === 409 && err.detail?.existing_contact_id) {
        setDuplicate(err.detail);
      } else {
        setError(err.message);
      }
    } finally {
      setSaving(false);
    }
  };

  const handleAdd = (e) => {
    e.preventDefault();
    if (!values.name.trim()) return;
    save(false);
  };

  const handleDelete = async (contactId) => {
    await deleteContact(contactId);
    onChanged();
  };

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-900">
          CSR contacts ({contacts.length})
        </h2>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setShowForm((v) => !v)}
            className="text-sm font-medium text-emerald-700 hover:underline"
          >
            {showForm ? "Cancel" : "+ Add contact"}
          </button>
          <FindContactsButton company={company} onSaved={onChanged} variant="primary" />
        </div>
      </div>

      {showForm && (
        <form onSubmit={handleAdd} className="mb-4 grid grid-cols-2 gap-2 rounded-lg bg-slate-50 p-3">
          <input
            autoFocus
            placeholder="Name *"
            value={values.name}
            onChange={handleChange("name")}
            className="col-span-2 rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
          <input
            placeholder="Designation"
            value={values.designation}
            onChange={handleChange("designation")}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
          <input
            placeholder="Email"
            value={values.email}
            onChange={handleChange("email")}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
          <input
            placeholder="Phone"
            value={values.phone}
            onChange={handleChange("phone")}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
          <input
            placeholder="LinkedIn URL"
            value={values.linkedin_url}
            onChange={handleChange("linkedin_url")}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
          {duplicate && (
            <div className="col-span-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
              <p>
                This company already has a contact called{" "}
                <strong>{duplicate.existing_contact_name}</strong>
                {duplicate.existing_contact_email ? ` (${duplicate.existing_contact_email})` : ""}.
              </p>
              <button
                type="button"
                onClick={() => save(true)}
                disabled={saving}
                className="mt-2 font-medium text-amber-900 hover:underline disabled:opacity-60"
              >
                Add anyway
              </button>
            </div>
          )}

          {error && <p className="col-span-2 text-sm text-rose-600">{error}</p>}

          <div className="col-span-2 flex justify-end">
            <button
              type="submit"
              disabled={saving}
              className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-60"
            >
              {saving ? "Saving…" : "Save contact"}
            </button>
          </div>
        </form>
      )}

      {contacts.length === 0 && !showForm && (
        <p className="text-sm text-slate-400">
          No contacts saved yet. Click <strong>Find contacts</strong> to discover this company&apos;s publicly
          listed CSR, HR and regional decision makers.
        </p>
      )}

      <ul className="divide-y divide-slate-100">
        {contacts.map((contact) => (
          <li key={contact.id} className="flex items-start justify-between py-2">
            <div>
              <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-slate-900">
                <Link to={`/contacts/${contact.id}`} className="text-emerald-700 hover:underline">
                  {contact.name}
                </Link>
                {CONTACT_PRIORITIES[contact.priority] && (
                  <span
                    className={`rounded-full px-1.5 py-px text-[10px] font-medium ${CONTACT_PRIORITIES[contact.priority].className}`}
                  >
                    {CONTACT_PRIORITIES[contact.priority].label}
                  </span>
                )}
              </p>
              <p className="text-xs text-slate-500">{contact.designation || "—"}</p>
              <p className="text-xs text-slate-500">
                {[contact.email, contact.phone].filter(Boolean).join(" · ") || "—"}
              </p>
              {contact.linkedin_url && (
                <a
                  href={contact.linkedin_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs text-emerald-700 hover:underline"
                >
                  LinkedIn
                </a>
              )}
            </div>
            <button
              type="button"
              onClick={() => handleDelete(contact.id)}
              className="text-xs text-rose-500 hover:underline"
            >
              Remove
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
