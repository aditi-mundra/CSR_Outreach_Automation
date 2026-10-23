import { NavLink, Routes, Route } from "react-router-dom";
import DashboardPage from "./pages/DashboardPage";
import CompaniesPage from "./pages/CompaniesPage";
import CompanyDetailPage from "./pages/CompanyDetailPage";
import NGOProfilePage from "./pages/NGOProfilePage";
import ContactsPage from "./pages/ContactsPage";
import ContactProfilePage from "./pages/ContactProfilePage";
import EmailsPage from "./pages/EmailsPage";
import SettingsPage from "./pages/SettingsPage";

const NAV_LINK_CLASS = ({ isActive }) =>
  `text-sm font-medium ${isActive ? "text-emerald-700" : "text-slate-500 hover:text-slate-700"}`;

export default function App() {
  return (
    <div className="min-h-screen bg-slate-50">
      <nav className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="text-lg">🤝</span>
            <span className="font-semibold text-slate-900">CSR Outreach Portal</span>
          </div>
          <NavLink to="/" end className={NAV_LINK_CLASS}>
            Dashboard
          </NavLink>
          <NavLink to="/companies" className={NAV_LINK_CLASS}>
            Companies
          </NavLink>
          <NavLink to="/contacts" className={NAV_LINK_CLASS}>
            Contacts
          </NavLink>
          <NavLink to="/emails" className={NAV_LINK_CLASS}>
            Emails
          </NavLink>
          <NavLink to="/ngo-profile" className={NAV_LINK_CLASS}>
            NGO Profile
          </NavLink>
          <NavLink to="/settings" className={NAV_LINK_CLASS}>
            Settings
          </NavLink>
        </div>
      </nav>

      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/companies" element={<CompaniesPage />} />
        <Route path="/companies/:id" element={<CompanyDetailPage />} />
        <Route path="/contacts" element={<ContactsPage />} />
        <Route path="/contacts/:id" element={<ContactProfilePage />} />
        <Route path="/ngo-profile" element={<NGOProfilePage />} />
        <Route path="/emails" element={<EmailsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Routes>
    </div>
  );
}
