"""SQLAlchemy models for Phase 1: companies, contacts, notes.

Matches the "Contact Database" data model in docs/PROJECT_OVERVIEW.md:
Company -> Contact(s) -> Outreach status / Notes.
"""

import enum

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    LargeBinary,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.orm import deferred, relationship

from .database import Base


class LeadStatus(str, enum.Enum):
    NEW = "New"
    CONTACTED = "Contacted"
    FOLLOW_UP = "Follow-up"
    MEETING = "Meeting"
    PROPOSAL_SENT = "Proposal Sent"
    SUCCESSFUL = "Successful"
    NOT_INTERESTED = "Not Interested"


class ProposalStage(str, enum.Enum):
    REQUESTED = "Requested"
    DRAFTING = "Drafting"
    SENT = "Sent"
    APPROVED = "Approved"
    REJECTED = "Rejected"


company_tags = Table(
    "company_tags",
    Base.metadata,
    Column("company_id", Integer, ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    industry = Column(String(120), index=True)
    city = Column(String(120), index=True)
    state = Column(String(120), index=True)
    website = Column(String(500))
    # Link to the company's published CSR/sustainability report - the main
    # research artifact staff work from, kept separate from the general
    # website (PROJECT_OVERVIEW.md's Company Profile page lists both).
    csr_report_url = Column(String(500))
    csr_focus = Column(String(255), index=True)
    csr_spending = Column(Float)
    revenue = Column(Float)
    employee_count = Column(Integer)

    status = Column(Enum(LeadStatus), nullable=False, default=LeadStatus.NEW, index=True)
    last_contacted_date = Column(Date, nullable=True)
    follow_up_date = Column(Date, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    contacts = relationship(
        "Contact", back_populates="company", cascade="all, delete-orphan", order_by="Contact.id"
    )
    notes = relationship(
        "Note", back_populates="company", cascade="all, delete-orphan", order_by="Note.created_at.desc()"
    )
    activity_logs = relationship(
        "ActivityLog",
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="ActivityLog.created_at.desc(), ActivityLog.id.desc()",
    )
    tags = relationship("Tag", secondary=company_tags, order_by="Tag.name", back_populates="companies")
    documents = relationship(
        "Document",
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="Document.uploaded_at.desc()",
    )
    proposals = relationship(
        "Proposal",
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="Proposal.created_at.desc()",
    )


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)

    name = Column(String(255), nullable=False)
    designation = Column(String(255))
    email = Column(String(255))
    phone = Column(String(50))
    linkedin_url = Column(String(500))
    source_url = Column(String(500))

    # Contact discovery (app/contact_discovery/). All nullable: contacts
    # added by hand leave them empty, and existing databases get these
    # columns added in place by app/schema_upgrade.py.
    office_location = Column(String(255))
    role_category = Column(String(120))
    # 1 = CSR/Sustainability/ESG/Foundation, 2 = HR/Communications/Corporate
    # Affairs, 3 = Regional/Operations leadership.
    priority = Column(Integer, index=True)
    confidence = Column(Integer)
    # {field: {status, source, source_url}} - verified/inferred/unavailable,
    # same vocabulary as company discovery.
    provenance = Column(JSON)
    # "manual" (typed in by staff) or "discovery" (saved from Find contacts).
    origin = Column(String(20))

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    company = relationship("Company", back_populates="contacts")
    sources = relationship(
        "ContactSource", back_populates="contact", cascade="all, delete-orphan", order_by="ContactSource.id"
    )
    # Not cascaded: deleting a contact keeps its notes/activity on the
    # company (the FK is nulled), so outreach history isn't lost.
    notes = relationship("Note", back_populates="contact", order_by="Note.created_at.desc()")
    activity_logs = relationship(
        "ActivityLog", back_populates="contact", order_by="ActivityLog.created_at.desc(), ActivityLog.id.desc()"
    )


class ContactSource(Base):
    """A public page (or third-party lookup) a saved contact was found on.
    A contact can be confirmed by several - e.g. the leadership page and
    the CSR committee table in the annual report.
    """

    __tablename__ = "contact_sources"

    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True)

    url = Column(String(1000))
    # "website", "csr_report", "third_party", ...
    source_type = Column(String(40), nullable=False)
    label = Column(String(255))
    # What the source stated, e.g. "name, designation, email".
    fields = Column(String(255))
    found_at = Column(DateTime(timezone=True), server_default=func.now())

    contact = relationship("Contact", back_populates="sources")


class ContactDiscoveryLog(Base):
    """One "Find contacts" run: what was checked and what came back. Kept
    for transparency (which pages were read, which robots.txt blocked) -
    company_id is null when the company hadn't been saved as a lead yet.
    """

    __tablename__ = "contact_discovery_logs"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True)
    company_name = Column(String(255), nullable=False)
    website = Column(String(500))

    pages_checked = Column(JSON)
    pages_blocked = Column(JSON)
    sources_used = Column(JSON)
    candidates_found = Column(Integer, nullable=False, default=0)
    messages = Column(JSON)
    duration_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class Note(Base):
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)

    # Set when the note is about one contact (written from the contact's
    # profile). Still a company note, so it shows on the company page too.
    contact_id = Column(Integer, ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True, index=True)

    body = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    company = relationship("Company", back_populates="notes")
    contact = relationship("Contact", back_populates="notes")


class ActivityLog(Base):
    """Auto-recorded events for Phase 4's recent-activity feed and
    dashboard KPIs (e.g. company added, contact added, status changed).
    Not user-editable - written only by crud.py as a side effect of the
    action it describes.
    """

    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    # Set for events about one contact - drives the contact's own timeline.
    contact_id = Column(Integer, ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True, index=True)

    event_type = Column(String(50), nullable=False)
    description = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    company = relationship("Company", back_populates="activity_logs")
    contact = relationship("Contact", back_populates="activity_logs")


class Tag(Base):
    """Reusable free-form label (Phase 5), e.g. "Education", "High
    Priority" - created on first use via crud.get_or_create_tag, shared
    across companies via the company_tags association table.
    """

    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(60), unique=True, nullable=False, index=True)

    companies = relationship("Company", secondary=company_tags, back_populates="tags")


class Document(Base):
    """An uploaded file (proposal, CSR report, MoU, receipt, ...) for a
    company (Phase 5). Stored directly in the database (LargeBinary) -
    simplest option at this tool's scale, no separate file-storage
    infra needed. `data` is deferred so listing documents (metadata
    only) doesn't pull file bytes into memory.
    """

    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)

    filename = Column(String(255), nullable=False)
    content_type = Column(String(120))
    size = Column(Integer, nullable=False)
    data = deferred(Column(LargeBinary, nullable=False))
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())

    company = relationship("Company", back_populates="documents")


class Proposal(Base):
    """A CSR proposal tracked through its own stage pipeline (Phase 5),
    distinct from the company's overall lead `status` - a company can
    have multiple proposals over time (different projects/years).
    """

    __tablename__ = "proposals"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)

    title = Column(String(255), nullable=False)
    amount = Column(Float, nullable=True)
    stage = Column(Enum(ProposalStage), nullable=False, default=ProposalStage.REQUESTED, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    company = relationship("Company", back_populates="proposals")


class NGOProfile(Base):
    """Single-row (id=1) editable NGO profile (Phase 5), replacing the
    env-only NGO_* settings as the source of truth for lead scoring's
    location/focus match and AI-generated content. See
    crud.get_ngo_profile / crud.update_ngo_profile: the row is
    seeded from app.config.settings on first access, and every update
    is mirrored back onto the live `settings` object so scoring.py and
    ai.py (which read `settings.ngo_*`) pick up edits immediately
    without needing a db session threaded through them.
    """

    __tablename__ = "ngo_profile"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    work_area = Column(String(255))
    focus_areas = Column(String(500))
    city = Column(String(120))
    state = Column(String(120))
    contact_email = Column(String(255))
    contact_phone = Column(String(50))
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
