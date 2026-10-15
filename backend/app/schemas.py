"""Pydantic request/response schemas."""

from datetime import date, datetime
from enum import Enum
from typing import Annotated, Optional

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
# Email automation (app/mail/)
# ----------------------------------------------------------------------------
class EmailSettingsOut(BaseModel):
    sender_name: Optional[str] = None
    signature: Optional[str] = None
    followup_intervals: list[int]
    default_followup_days: int
    updated_at: Optional[datetime] = None


class EmailSettingsUpdate(BaseModel):
    sender_name: Optional[str] = Field(default=None, max_length=255)
    signature: Optional[str] = Field(default=None, max_length=2000)
    followup_intervals: Optional[list[Annotated[int, Field(ge=1, le=365)]]] = Field(default=None, min_length=1, max_length=8)
    default_followup_days: Optional[int] = Field(default=None, ge=1, le=365)


class EmailTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email_type: str
    name: str
    subject: str
    body: str
    updated_at: Optional[datetime] = None


class EmailTemplateUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    subject: Optional[str] = Field(default=None, min_length=1, max_length=500)
    body: Optional[str] = Field(default=None, min_length=1, max_length=20000)


class ProviderCapabilities(BaseModel):
    delivery: bool
    opens: bool
    clicks: bool
    replies: bool
    bounces: bool
    notes: list[str] = []


class EmailProviderInfo(BaseModel):
    key: str
    label: str
    configured: bool
    setup_hint: str
    capabilities: ProviderCapabilities


class EmailAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider: str
    email_address: str
    status: str
    last_error: Optional[str] = None
    last_sync_at: Optional[datetime] = None
    connected_at: Optional[datetime] = None


class EmailAccountStatus(BaseModel):
    providers: list[EmailProviderInfo]
    account: Optional[EmailAccountOut] = None
    encryption_configured: bool
    access_token_required: bool
    sync_minutes: int
    max_emails_per_hour: int


class OAuthStart(BaseModel):
    authorization_url: str


class ReplyClassificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    classification: str
    confidence: Optional[float] = None
    reasoning: Optional[str] = None
    intent: Optional[str] = None
    method: str
    created_at: datetime


class EmailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    thread_id: int
    company_id: int
    contact_id: Optional[int] = None
    direction: str
    status: str
    email_type: Optional[str] = None
    generated_by: Optional[str] = None
    subject: str
    body: str
    to_email: Optional[str] = None
    to_name: Optional[str] = None
    from_email: Optional[str] = None
    from_name: Optional[str] = None
    error: Optional[str] = None
    duplicated_from_id: Optional[int] = None
    approved_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    received_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    opened_at: Optional[datetime] = None
    clicked_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    # Filled in by the router: latest classification (replies), names.
    classification: Optional[ReplyClassificationOut] = None
    classification_history: list[ReplyClassificationOut] = []
    company_name: Optional[str] = None
    contact_name: Optional[str] = None
    thread_status: Optional[str] = None


class EmailEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email_id: Optional[int] = None
    thread_id: Optional[int] = None
    event_type: str
    detail: Optional[str] = None
    created_at: datetime


class FollowUpOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    contact_id: Optional[int] = None
    thread_id: Optional[int] = None
    due_date: date
    interval_days: Optional[int] = None
    status: str
    draft_email_id: Optional[int] = None
    note: Optional[str] = None
    cancel_reason: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    company_name: Optional[str] = None
    contact_name: Optional[str] = None


class MeetingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    contact_id: Optional[int] = None
    thread_id: Optional[int] = None
    title: str
    scheduled_at: Optional[datetime] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    status: str
    created_at: datetime
    company_name: Optional[str] = None
    contact_name: Optional[str] = None


class EmailThreadOut(BaseModel):
    id: int
    company_id: int
    contact_id: Optional[int] = None
    subject: Optional[str] = None
    status: str
    status_label: str
    status_source: Optional[str] = None
    provider: Optional[str] = None
    last_message_at: Optional[datetime] = None
    created_at: datetime
    company_name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    emails: list[EmailOut] = []
    followups: list[FollowUpOut] = []
    meetings: list[MeetingOut] = []
    events: list[EmailEventOut] = []


class EmailGenerateRequest(BaseModel):
    company_id: int
    contact_id: Optional[int] = None
    email_type: str = "first_outreach"
    use_ai: bool = True
    # Follow-up inside an existing conversation.
    thread_id: Optional[int] = None


class EmailDraftCreate(BaseModel):
    company_id: int
    contact_id: Optional[int] = None
    email_type: str = "first_outreach"
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=50000)


class EmailDraftUpdate(BaseModel):
    subject: Optional[str] = Field(default=None, max_length=500)
    body: Optional[str] = Field(default=None, max_length=50000)
    to_email: Optional[str] = Field(default=None, max_length=255)
    contact_id: Optional[int] = None
    email_type: Optional[str] = None


class EmailDuplicateRequest(BaseModel):
    contact_id: Optional[int] = None


class EmailSendRequest(BaseModel):
    """The person's explicit approval: `confirm` plus the exact content they
    reviewed. What's sent is this, not whatever the draft held before.
    """

    confirm: bool
    to_email: str = Field(min_length=3, max_length=255)
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=50000)
    followup_days: Optional[int] = Field(default=None, ge=1, le=365)


class ClassificationOverride(BaseModel):
    classification: str
    intent: Optional[str] = None


class ThreadStatusUpdate(BaseModel):
    status: str


class FollowUpCreate(BaseModel):
    company_id: Optional[int] = None
    contact_id: Optional[int] = None
    thread_id: Optional[int] = None
    days: Optional[int] = Field(default=None, ge=1, le=365)
    due_date: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=2000)


class FollowUpUpdate(BaseModel):
    due_date: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=2000)
    # Only "cancelled" can be set by hand; sending a draft marks it "sent".
    status: Optional[str] = None


class MeetingCreate(BaseModel):
    company_id: int
    contact_id: Optional[int] = None
    thread_id: Optional[int] = None
    title: str = Field(min_length=1, max_length=255)
    scheduled_at: Optional[datetime] = None
    location: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = Field(default=None, max_length=5000)
    status: str = "scheduled"


class MeetingUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    scheduled_at: Optional[datetime] = None
    location: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = Field(default=None, max_length=5000)
    status: Optional[str] = None


class SyncResult(BaseModel):
    connected: bool
    threads_checked: int
    new_replies: int
    bounces: int
    errors: list[str] = []
    followups_drafted: int = 0


class OutreachMetrics(BaseModel):
    total_companies: int
    saved_leads: int
    contacts: int
    emails_generated: int
    emails_sent: int
    replies_received: int
    positive_replies: int
    negative_replies: int
    meetings_scheduled: int
    proposals_sent: int
    partnerships: int
    pending_followups: int
    overdue_followups: int
    reply_rate: Optional[float] = None
    positive_reply_rate: Optional[float] = None
    conversion_rate: Optional[float] = None


class PipelineStage(BaseModel):
    stage: str
    count: int


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
    # Email automation additions (the fields above are unchanged).
    outreach: Optional[OutreachMetrics] = None
    pipeline: list[PipelineStage] = []
    email_followups: list[FollowUpOut] = []


# ----------------------------------------------------------------------------
# CSV import (Phase 4)
# ----------------------------------------------------------------------------
class ImportResult(BaseModel):
    created: int
    skipped_duplicates: int
    errors: list[str]
