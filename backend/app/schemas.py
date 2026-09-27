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


class ContactOut(ContactBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    created_at: datetime


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
