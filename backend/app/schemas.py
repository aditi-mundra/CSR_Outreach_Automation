"""Pydantic request/response schemas."""

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .models import LeadStatus, ProposalStage


# ----------------------------------------------------------------------------
# AI features (Phase 3: lead scoring + Gemini-generated content)
# ----------------------------------------------------------------------------
class LeadScore(BaseModel):
    score: int
    priority: str
    factors: dict[str, int]


class ScoreExplanation(BaseModel):
    configured: bool
    explanation: Optional[str] = None


class EmailType(str, Enum):
    FIRST_OUTREACH = "first_outreach"
    FOLLOW_UP = "follow_up"
    MEETING_REQUEST = "meeting_request"
    THANK_YOU = "thank_you"


class GenerateEmailRequest(BaseModel):
    email_type: EmailType
    contact_id: Optional[int] = None


class GeneratedEmail(BaseModel):
    configured: bool
    subject: Optional[str] = None
    body: Optional[str] = None


class AITextResult(BaseModel):
    configured: bool
    text: Optional[str] = None


# ----------------------------------------------------------------------------
# Discovery (Phase 2: scraping / enrichment candidates)
# ----------------------------------------------------------------------------
class ScrapedContact(BaseModel):
    name: Optional[str] = None
    designation: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    source_url: Optional[str] = None


class ScrapeResult(BaseModel):
    contacts: list[ScrapedContact]


class EnrichResult(BaseModel):
    configured: bool
    contacts: list[ScrapedContact]


# ----------------------------------------------------------------------------
# Company discovery (real companies from public sources - not yet saved)
# ----------------------------------------------------------------------------
class FieldProvenanceOut(BaseModel):
    # "verified" (stated by a named public source), "inferred" (derived by
    # this app), or "unavailable" (no configured source has it).
    status: str
    source: Optional[str] = None
    source_url: Optional[str] = None


class SourceLink(BaseModel):
    name: str
    url: Optional[str] = None


class DiscoveredCompanyOut(BaseModel):
    result_id: str
    name: str
    aliases: list[str] = []
    description: Optional[str] = None
    industry: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    website: Optional[str] = None
    csr_focus: Optional[str] = None
    csr_spending: Optional[float] = None
    employee_count: Optional[int] = None
    csr_report_url: Optional[str] = None
    provenance: dict[str, FieldProvenanceOut] = {}
    identifiers: dict[str, str] = {}
    listed_on: list[str] = []
    details: dict[str, str] = {}
    sources: list[SourceLink] = []
    # Set when this company is already one of the NGO's saved leads.
    saved_company_id: Optional[int] = None


class DiscoverySourceReport(BaseModel):
    key: str
    label: str
    configured: bool
    used: bool
    result_count: int
    error: Optional[str] = None


class DiscoverySearchResult(BaseModel):
    results: list[DiscoveredCompanyOut]
    total: int
    page: int
    page_size: int
    notes: list[str] = []
    sources: list[DiscoverySourceReport] = []


class DiscoverySourceInfo(BaseModel):
    key: str
    label: str
    description: str
    requires_api_key: bool
    configured: bool
    setup_hint: str
    status: Optional[str] = None


class CsrFocusRequest(BaseModel):
    website: str


class CsrFocusArea(BaseModel):
    area: str
    mentions: int


class CsrFocusResult(BaseModel):
    csr_focus: Optional[str] = None
    areas: list[CsrFocusArea] = []
    source_urls: list[str] = []
    csr_report_url: Optional[str] = None
    pages_checked: list[str] = []
    message: Optional[str] = None


class DiscoverySaveRequest(BaseModel):
    """A discovery result being saved as a lead. Field values plus the
    provenance the UI showed, so the saved lead records where each value
    came from (written as a note - see routers/company_discovery.py).
    """

    name: str = Field(min_length=1)
    industry: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    website: Optional[str] = None
    csr_report_url: Optional[str] = None
    csr_focus: Optional[str] = None
    csr_spending: Optional[float] = Field(default=None, ge=0)
    employee_count: Optional[int] = Field(default=None, ge=0)
    provenance: dict[str, FieldProvenanceOut] = {}
    identifiers: dict[str, str] = {}
    listed_on: list[str] = []
    details: dict[str, str] = {}
    sources: list[SourceLink] = []


# ----------------------------------------------------------------------------
# Contact
# ----------------------------------------------------------------------------
class ContactBase(BaseModel):
    name: str
    designation: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    source_url: Optional[str] = None


class ContactCreate(ContactBase):
    pass


class ContactUpdate(BaseModel):
    name: Optional[str] = None
    designation: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    source_url: Optional[str] = None
    office_location: Optional[str] = None


class ContactOut(ContactBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    created_at: datetime
    # Set for contacts saved from contact discovery; empty for manual ones.
    office_location: Optional[str] = None
    role_category: Optional[str] = None
    priority: Optional[int] = None
    confidence: Optional[int] = None
    provenance: Optional[dict[str, FieldProvenanceOut]] = None
    origin: Optional[str] = None


# ----------------------------------------------------------------------------
# Contact discovery (find publicly listed CSR decision makers)
# ----------------------------------------------------------------------------
class ContactDiscoveryRequest(BaseModel):
    """Either a saved lead (company_id) or a just-discovered company
    (name + whatever discovery knows about it).
    """

    company_id: Optional[int] = None
    name: Optional[str] = None
    website: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    industry: Optional[str] = None
    csr_report_url: Optional[str] = None
    include_reports: bool = False
    refresh: bool = False


class ContactSourceIn(BaseModel):
    url: str
    source_type: str = "website"
    label: Optional[str] = None
    fields: list[str] = []


class DiscoveredContactOut(BaseModel):
    candidate_id: str
    name: str
    designation: Optional[str] = None
    company: str
    role_category: Optional[str] = None
    priority: Optional[int] = None
    priority_label: Optional[str] = None
    office_location: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    linkedin_search_url: Optional[str] = None
    source_url: Optional[str] = None
    sources: list[ContactSourceIn] = []
    provenance: dict[str, FieldProvenanceOut] = {}
    confidence: int
    confidence_reasons: list[str] = []
    is_shared_mailbox: bool = False
    saved_contact_id: Optional[int] = None


class ContactPoint(BaseModel):
    kind: str  # "email" | "phone"
    value: str
    label: str
    source_url: Optional[str] = None


class ContactDiscoverySourceReport(BaseModel):
    key: str
    label: str
    configured: bool
    used: bool
    result_count: int
    message: Optional[str] = None


class ReportScanInfo(BaseModel):
    url: Optional[str] = None
    scanned: bool = False
    pages_read: int = 0
    relevant_pages: list[int] = []
    message: Optional[str] = None
    urls_tried: list[str] = []


class ContactDiscoveryCompany(BaseModel):
    company_id: Optional[int] = None
    name: str
    website: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    industry: Optional[str] = None
    csr_report_url: Optional[str] = None


class ContactDiscoveryResult(BaseModel):
    company: ContactDiscoveryCompany
    # Saved lead this company matches (by id, name or website), if any.
    saved_company_id: Optional[int] = None
    contacts: list[DiscoveredContactOut]
    contact_points: list[ContactPoint] = []
    suggested_searches: list[SourceLink] = []
    pages_checked: list[str] = []
    pages_blocked: list[str] = []
    report: ReportScanInfo = ReportScanInfo()
    report_links: list[str] = []
    sources: list[ContactDiscoverySourceReport] = []
    messages: list[str] = []
    duration_ms: Optional[int] = None
    cached: bool = False
    log_id: Optional[int] = None


class DiscoveredContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    designation: Optional[str] = None
    role_category: Optional[str] = None
    priority: Optional[int] = Field(default=None, ge=1, le=3)
    office_location: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    source_url: Optional[str] = None
    confidence: Optional[int] = Field(default=None, ge=0, le=100)
    provenance: dict[str, FieldProvenanceOut] = {}
    sources: list[ContactSourceIn] = []


class ContactSaveRequest(BaseModel):
    """Save one or more discovered contacts. Give `company_id` for a saved
    lead, or `company` for a just-discovered one - it is saved as a lead
    first (or matched to the existing lead).
    """

    company_id: Optional[int] = None
    company: Optional[DiscoverySaveRequest] = None
    contacts: list[DiscoveredContactIn] = Field(min_length=1)
    # Save even when a contact looks like one already saved.
    force: bool = False


class ContactDuplicate(BaseModel):
    index: int
    name: str
    existing_contact_id: int
    existing_contact_name: str
    existing_contact_email: Optional[str] = None


class ContactSaveResult(BaseModel):
    company_id: int
    company_created: bool
    saved: list[ContactOut]
    duplicates: list[ContactDuplicate] = []
    # Discovered values dropped by the work-info-only rules (personal email
    # provider, mobile number) - reported so staff know why.
    dropped: list[str] = []


class ContactDiscoveryLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: Optional[int] = None
    company_name: str
    website: Optional[str] = None
    pages_checked: Optional[list[str]] = None
    pages_blocked: Optional[list[str]] = None
    sources_used: Optional[list[str]] = None
    candidates_found: int
    messages: Optional[list[str]] = None
    duration_ms: Optional[int] = None
    created_at: datetime


class ContactSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    url: Optional[str] = None
    source_type: str
    label: Optional[str] = None
    fields: Optional[str] = None
    found_at: datetime


class ContactCompanySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    industry: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    website: Optional[str] = None
    status: LeadStatus


class ContactListItem(ContactOut):
    company_name: str
    company_industry: Optional[str] = None
    company_city: Optional[str] = None
    company_state: Optional[str] = None


# ----------------------------------------------------------------------------
# Tags (Phase 5)
# ----------------------------------------------------------------------------
class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class TagCreate(BaseModel):
    name: str


# ----------------------------------------------------------------------------
# Documents (Phase 5)
# ----------------------------------------------------------------------------
class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    filename: str
    content_type: Optional[str] = None
    size: int
    uploaded_at: datetime


# ----------------------------------------------------------------------------
# Proposals (Phase 5)
# ----------------------------------------------------------------------------
class ProposalCreate(BaseModel):
    title: str
    amount: Optional[float] = Field(default=None, ge=0)
    stage: ProposalStage = ProposalStage.REQUESTED


class ProposalUpdate(BaseModel):
    title: Optional[str] = None
    amount: Optional[float] = Field(default=None, ge=0)
    stage: Optional[ProposalStage] = None


class ProposalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    title: str
    amount: Optional[float] = None
    stage: ProposalStage
    created_at: datetime
    updated_at: datetime


# ----------------------------------------------------------------------------
# NGO Profile (Phase 5)
# ----------------------------------------------------------------------------
class NGOProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    work_area: Optional[str] = None
    focus_areas: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    updated_at: datetime


class NGOProfileUpdate(BaseModel):
    name: Optional[str] = None
    work_area: Optional[str] = None
    focus_areas: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None


# ----------------------------------------------------------------------------
# Note
# ----------------------------------------------------------------------------
class NoteCreate(BaseModel):
    body: str


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    contact_id: Optional[int] = None
    body: str
    created_at: datetime


# ----------------------------------------------------------------------------
# Company
# ----------------------------------------------------------------------------
class CompanyBase(BaseModel):
    name: str
    industry: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    website: Optional[str] = None
    csr_report_url: Optional[str] = None
    csr_focus: Optional[str] = None
    csr_spending: Optional[float] = Field(default=None, ge=0)
    revenue: Optional[float] = Field(default=None, ge=0)
    employee_count: Optional[int] = Field(default=None, ge=0)


class CompanyCreate(CompanyBase):
    # Outreach-tracking fields are settable at create time so a CSV export
    # round-trips: _CSV_COLUMNS writes status/last_contacted_date/
    # follow_up_date, and import builds rows through this schema - without
    # them here, re-importing an edited export silently reset every company
    # to "New" with no dates. Also means an invalid status is rejected (422)
    # on create rather than being quietly dropped.
    status: LeadStatus = LeadStatus.NEW
    last_contacted_date: Optional[date] = None
    follow_up_date: Optional[date] = None


class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    industry: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    website: Optional[str] = None
    csr_report_url: Optional[str] = None
    csr_focus: Optional[str] = None
    csr_spending: Optional[float] = Field(default=None, ge=0)
    revenue: Optional[float] = Field(default=None, ge=0)
    employee_count: Optional[int] = Field(default=None, ge=0)
    status: Optional[LeadStatus] = None
    last_contacted_date: Optional[date] = None
    follow_up_date: Optional[date] = None


class CompanyListItem(CompanyBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: LeadStatus
    follow_up_date: Optional[date] = None
    contact_count: int = 0
    lead_score: Optional[LeadScore] = None
    tags: list[TagOut] = []


class CompanyActivityItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contact_id: Optional[int] = None
    event_type: str
    description: str
    created_at: datetime


class CompanyDetail(CompanyBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: LeadStatus
    last_contacted_date: Optional[date] = None
    follow_up_date: Optional[date] = None
    created_at: datetime
    updated_at: datetime
    contacts: list[ContactOut] = []
    notes: list[NoteOut] = []
    lead_score: Optional[LeadScore] = None
    tags: list[TagOut] = []
    documents: list[DocumentOut] = []
    proposals: list[ProposalOut] = []
    activity_logs: list[CompanyActivityItem] = []


class ContactProfile(ContactOut):
    company: ContactCompanySummary
    sources: list[ContactSourceOut] = []
    notes: list[NoteOut] = []
    activity_logs: list[CompanyActivityItem] = []


# ----------------------------------------------------------------------------
# Dashboard (Phase 4: KPIs, follow-ups, recent activity)
# ----------------------------------------------------------------------------
class ActivityLogOut(BaseModel):
    id: int
    company_id: int
    company_name: str
    event_type: str
    description: str
    created_at: datetime


class DashboardKPIs(BaseModel):
    total_companies: int
    contacted: int
    replies_received: int
    meetings_scheduled: int
    proposals_sent: int
    successful_partnerships: int


class FollowUpItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    status: LeadStatus
    follow_up_date: date


class FollowUps(BaseModel):
    overdue: list[FollowUpItem]
    due_today: list[FollowUpItem]
    upcoming: list[FollowUpItem]


class DashboardResponse(BaseModel):
    kpis: DashboardKPIs
    follow_ups: FollowUps
    recent_activity: list[ActivityLogOut]


# ----------------------------------------------------------------------------
# CSV import (Phase 4)
# ----------------------------------------------------------------------------
class ImportResult(BaseModel):
    created: int
    skipped_duplicates: int
    errors: list[str]
