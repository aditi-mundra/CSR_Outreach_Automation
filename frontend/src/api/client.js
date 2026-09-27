// In local dev this is left unset, so requests go to relative "/api" and
// hit the Vite proxy (see vite.config.js). In production the frontend and
// backend are deployed separately (Vercel + Render) with no shared proxy,
// so VITE_API_BASE_URL must be set to the deployed backend's origin - see
// docs/DEPLOYMENT.md.
const API_ROOT = import.meta.env.VITE_API_BASE_URL || "";
const BASE_URL = `${API_ROOT}/api`;

async function request(path, options = {}) {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // response had no JSON body
    }
    const message = typeof detail === "string" ? detail : (detail?.message ?? response.statusText);
    const error = new Error(message);
    error.status = response.status;
    error.detail = detail;
    throw error;
  }

  if (response.status === 204) return null;
  return response.json();
}

async function requestFormData(path, formData, { method = "POST" } = {}) {
  const response = await fetch(`${BASE_URL}${path}`, { method, body: formData });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      // no JSON body
    }
    const message = typeof detail === "string" ? detail : (detail?.message ?? response.statusText);
    const error = new Error(message);
    error.status = response.status;
    error.detail = detail;
    throw error;
  }
  if (response.status === 204) return null;
  return response.json();
}

export function listCompanies(filters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, value);
    }
  });
  const query = params.toString();
  return request(`/companies${query ? `?${query}` : ""}`);
}

export function getCompany(id) {
  return request(`/companies/${id}`);
}

export function createCompany(payload, { force = false } = {}) {
  const query = force ? "?force=true" : "";
  return request(`/companies${query}`, { method: "POST", body: JSON.stringify(payload) });
}

export function updateCompany(id, payload) {
  return request(`/companies/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export function deleteCompany(id) {
  return request(`/companies/${id}`, { method: "DELETE" });
}

export function addContact(companyId, payload, { force = false } = {}) {
  const query = force ? "?force=true" : "";
  return request(`/companies/${companyId}/contacts${query}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateContact(contactId, payload) {
  return request(`/contacts/${contactId}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export function deleteContact(contactId) {
  return request(`/contacts/${contactId}`, { method: "DELETE" });
}

export function addNote(companyId, body) {
  return request(`/companies/${companyId}/notes`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });
}

export function deleteNote(noteId) {
  return request(`/notes/${noteId}`, { method: "DELETE" });
}

export function scrapeCompany(companyId) {
  return request(`/companies/${companyId}/scrape`, { method: "POST" });
}

export function enrichCompany(companyId) {
  return request(`/companies/${companyId}/enrich`, { method: "POST" });
}

export function explainScore(companyId) {
  return request(`/companies/${companyId}/score/explain`, { method: "POST" });
}

export function generateEmail(companyId, { emailType, contactId }) {
  return request(`/companies/${companyId}/generate-email`, {
    method: "POST",
    body: JSON.stringify({ email_type: emailType, contact_id: contactId ?? null }),
  });
}

export function generateCompanySummary(companyId) {
  return request(`/companies/${companyId}/summary`, { method: "POST" });
}

export function generateMeetingBrief(companyId) {
  return request(`/companies/${companyId}/meeting-brief`, { method: "POST" });
}

export function getDashboard() {
  return request("/dashboard");
}

export function exportCompaniesUrl(filters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, value);
    }
  });
  const query = params.toString();
  return `${BASE_URL}/companies/export${query ? `?${query}` : ""}`;
}

export function importCompaniesCsv(file) {
  const formData = new FormData();
  formData.append("file", file);
  return requestFormData("/companies/import", formData);
}

// ----------------------------------------------------------------------------
// Tags (Phase 5)
// ----------------------------------------------------------------------------
export function listTags() {
  return request("/tags");
}

export function addTagToCompany(companyId, name) {
  return request(`/companies/${companyId}/tags`, {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function removeTagFromCompany(companyId, tagId) {
  return request(`/companies/${companyId}/tags/${tagId}`, { method: "DELETE" });
}

// ----------------------------------------------------------------------------
// Documents (Phase 5)
// ----------------------------------------------------------------------------
export function uploadDocument(companyId, file) {
  const formData = new FormData();
  formData.append("file", file);
  return requestFormData(`/companies/${companyId}/documents`, formData);
}

export function documentDownloadUrl(documentId) {
  return `${BASE_URL}/documents/${documentId}`;
}

export function deleteDocument(documentId) {
  return request(`/documents/${documentId}`, { method: "DELETE" });
}

// ----------------------------------------------------------------------------
// Proposals (Phase 5)
// ----------------------------------------------------------------------------
export function addProposal(companyId, payload) {
  return request(`/companies/${companyId}/proposals`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateProposal(proposalId, payload) {
  return request(`/proposals/${proposalId}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export function deleteProposal(proposalId) {
  return request(`/proposals/${proposalId}`, { method: "DELETE" });
}

// ----------------------------------------------------------------------------
// NGO Profile (Phase 5)
// ----------------------------------------------------------------------------
export function getNgoProfile() {
  return request("/ngo-profile");
}

export function updateNgoProfile(payload) {
  return request("/ngo-profile", { method: "PATCH", body: JSON.stringify(payload) });
}
