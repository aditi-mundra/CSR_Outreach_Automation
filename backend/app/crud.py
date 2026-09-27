"""Data-access functions (CRUD) for companies, contacts, and notes."""

import re
from datetime import date
from typing import Optional

from pydantic import ValidationError
from sqlalchemy.orm import Session, joinedload

from . import models, schemas
from .config import settings

# Statuses later in the pipeline than a given stage imply that stage was
# already reached (e.g. a company at "Proposal Sent" obviously already had
# its meeting) - used for cumulative-feeling dashboard KPIs without needing
# full historical event tracking. "Not Interested" is a terminal side-branch,
# not part of this ordered pipeline, so it only counts toward "Contacted".
_REPLIED_OR_LATER = {
    models.LeadStatus.FOLLOW_UP,
    models.LeadStatus.MEETING,
    models.LeadStatus.PROPOSAL_SENT,
    models.LeadStatus.SUCCESSFUL,
}
_MEETING_OR_LATER = {
    models.LeadStatus.MEETING,
    models.LeadStatus.PROPOSAL_SENT,
    models.LeadStatus.SUCCESSFUL,
}
_PROPOSAL_OR_LATER = {models.LeadStatus.PROPOSAL_SENT, models.LeadStatus.SUCCESSFUL}


def _log_activity(db: Session, company_id: int, event_type: str, description: str) -> None:
    """Queue an activity-log row; persisted by the caller's own commit()."""
    db.add(models.ActivityLog(company_id=company_id, event_type=event_type, description=description))


def _normalize_domain(website: str) -> str:
    if not website:
        return ""
    normalized = website.strip().lower()
    normalized = re.sub(r"^https?://", "", normalized)
    normalized = re.sub(r"^www\.", "", normalized)
    return normalized.rstrip("/")


# ----------------------------------------------------------------------------
# Companies
# ----------------------------------------------------------------------------
def find_duplicate_company(
    db: Session, name: str, website: Optional[str]
) -> Optional[models.Company]:
    """Best-effort duplicate check by case-insensitive name or website match.

    Fine at this tool's scale (a single NGO's outreach list, not a
    bulk data warehouse) - see docs/PROJECT_OVERVIEW.md's "keep
    infrastructure simple" principle.
    """
    name_match = (
        db.query(models.Company).filter(models.Company.name.ilike(name.strip())).first()
    )
    if name_match:
        return name_match

    target_domain = _normalize_domain(website) if website else ""
    if target_domain:
        for company in db.query(models.Company).filter(models.Company.website.isnot(None)).all():
            if _normalize_domain(company.website) == target_domain:
                return company
    return None


def create_company(db: Session, payload: schemas.CompanyCreate) -> models.Company:
    company = models.Company(**payload.model_dump())
    db.add(company)
    db.commit()
    db.refresh(company)
    _log_activity(db, company.id, "company_added", f"Company '{company.name}' added")
    db.commit()
    return company


def get_company(db: Session, company_id: int) -> Optional[models.Company]:
    return (
        db.query(models.Company)
        .options(
            joinedload(models.Company.contacts),
            joinedload(models.Company.notes),
            joinedload(models.Company.tags),
            joinedload(models.Company.documents),
            joinedload(models.Company.proposals),
            joinedload(models.Company.activity_logs),
        )
        .filter(models.Company.id == company_id)
        .first()
    )


def search_companies(
    db: Session,
    *,
    name: Optional[str] = None,
    industry: Optional[str] = None,
    state: Optional[str] = None,
    city: Optional[str] = None,
    csr_focus: Optional[str] = None,
    status: Optional[models.LeadStatus] = None,
    min_csr_spending: Optional[float] = None,
    max_csr_spending: Optional[float] = None,
    min_revenue: Optional[float] = None,
    max_revenue: Optional[float] = None,
    min_employees: Optional[int] = None,
    max_employees: Optional[int] = None,
    tag: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
) -> list[models.Company]:
    query = db.query(models.Company)

    if name:
        query = query.filter(models.Company.name.ilike(f"%{name}%"))
    if industry:
        query = query.filter(models.Company.industry.ilike(f"%{industry}%"))
    if state:
        query = query.filter(models.Company.state.ilike(f"%{state}%"))
    if city:
        query = query.filter(models.Company.city.ilike(f"%{city}%"))
    if csr_focus:
        query = query.filter(models.Company.csr_focus.ilike(f"%{csr_focus}%"))
    if status:
        query = query.filter(models.Company.status == status)
    if min_csr_spending is not None:
        query = query.filter(models.Company.csr_spending >= min_csr_spending)
    if max_csr_spending is not None:
        query = query.filter(models.Company.csr_spending <= max_csr_spending)
    if min_revenue is not None:
        query = query.filter(models.Company.revenue >= min_revenue)
    if max_revenue is not None:
        query = query.filter(models.Company.revenue <= max_revenue)
    if min_employees is not None:
        query = query.filter(models.Company.employee_count >= min_employees)
    if max_employees is not None:
        query = query.filter(models.Company.employee_count <= max_employees)
    if tag:
        query = query.join(models.Company.tags).filter(models.Tag.name.ilike(tag))

    return (
        query.options(joinedload(models.Company.contacts), joinedload(models.Company.tags))
        .order_by(models.Company.name)
        .offset(skip)
        .limit(limit)
        .all()
    )


def update_company(
    db: Session, company: models.Company, payload: schemas.CompanyUpdate
) -> models.Company:
    updates = payload.model_dump(exclude_unset=True)
    old_status = company.status
    for field, value in updates.items():
        setattr(company, field, value)
    if "status" in updates and company.status != old_status:
        _log_activity(
            db,
            company.id,
            "status_changed",
            f"Status changed from {old_status.value} to {company.status.value}",
        )
    db.commit()
    db.refresh(company)
    return company


def delete_company(db: Session, company: models.Company) -> None:
    db.delete(company)
    db.commit()


# ----------------------------------------------------------------------------
# Contacts
# ----------------------------------------------------------------------------
def find_duplicate_contact(
    db: Session, company_id: int, name: str, email: Optional[str]
) -> Optional[models.Contact]:
    """Best-effort duplicate check for a contact being added to a company,
    by case-insensitive email or name match - the contact-level counterpart
    of find_duplicate_company.

    Scoped to the one company on purpose: the same professional email
    legitimately appearing under two different companies is a real (if
    odd) situation, whereas the same email twice under one company is
    almost always a re-scan of that company's site or a double-submit.
    Email is checked before name because two genuinely different people
    can share a common name, but an email is the identity.
    """
    email = (email or "").strip()
    if email:
        email_match = (
            db.query(models.Contact)
            .filter(models.Contact.company_id == company_id, models.Contact.email.ilike(email))
            .first()
        )
        if email_match:
            return email_match

    name = (name or "").strip()
    if name:
        return (
            db.query(models.Contact)
            .filter(models.Contact.company_id == company_id, models.Contact.name.ilike(name))
            .first()
        )
    return None


def create_contact(
    db: Session, company_id: int, payload: schemas.ContactCreate
) -> models.Contact:
    contact = models.Contact(company_id=company_id, **payload.model_dump())
    db.add(contact)
    _log_activity(db, company_id, "contact_added", f"Contact '{contact.name}' added")
    db.commit()
    db.refresh(contact)
    return contact


def get_contact(db: Session, contact_id: int) -> Optional[models.Contact]:
    return db.query(models.Contact).filter(models.Contact.id == contact_id).first()


def update_contact(
    db: Session, contact: models.Contact, payload: schemas.ContactUpdate
) -> models.Contact:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(contact, field, value)
    _log_activity(db, contact.company_id, "contact_updated", f"Contact '{contact.name}' updated")
    db.commit()
    db.refresh(contact)
    return contact


def delete_contact(db: Session, contact: models.Contact) -> None:
    db.delete(contact)
    db.commit()


# ----------------------------------------------------------------------------
# Notes
# ----------------------------------------------------------------------------
def create_note(db: Session, company_id: int, payload: schemas.NoteCreate) -> models.Note:
    note = models.Note(company_id=company_id, body=payload.body)
    db.add(note)
    preview = payload.body if len(payload.body) <= 80 else payload.body[:77] + "..."
    _log_activity(db, company_id, "note_added", f"Note added: {preview}")
    db.commit()
    db.refresh(note)
    return note


def get_note(db: Session, note_id: int) -> Optional[models.Note]:
    return db.query(models.Note).filter(models.Note.id == note_id).first()


def delete_note(db: Session, note: models.Note) -> None:
    db.delete(note)
    db.commit()


def log_email_generated(db: Session, company_id: int, email_type_label: str) -> None:
    """Called by routers/ai.py after a successful draft - not part of any
    other transaction, so it commits immediately.
    """
    _log_activity(db, company_id, "email_generated", f"{email_type_label} email drafted")
    db.commit()


# ----------------------------------------------------------------------------
# Dashboard (Phase 4: KPIs, follow-ups, recent activity)
# ----------------------------------------------------------------------------
def get_dashboard_kpis(db: Session) -> dict:
    total = db.query(models.Company).count()
    contacted = (
        db.query(models.Company).filter(models.Company.status != models.LeadStatus.NEW).count()
    )
    replies_received = (
        db.query(models.Company).filter(models.Company.status.in_(_REPLIED_OR_LATER)).count()
    )
    meetings_scheduled = (
        db.query(models.Company).filter(models.Company.status.in_(_MEETING_OR_LATER)).count()
    )
    proposals_sent = (
        db.query(models.Company).filter(models.Company.status.in_(_PROPOSAL_OR_LATER)).count()
    )
    successful = (
        db.query(models.Company)
        .filter(models.Company.status == models.LeadStatus.SUCCESSFUL)
        .count()
    )
    return {
        "total_companies": total,
        "contacted": contacted,
        "replies_received": replies_received,
        "meetings_scheduled": meetings_scheduled,
        "proposals_sent": proposals_sent,
        "successful_partnerships": successful,
    }


def get_follow_ups(db: Session) -> dict:
    """Companies with a follow-up date, bucketed relative to today.

    Excludes closed-out leads (Successful / Not Interested) - a follow-up
    reminder on a closed deal isn't actionable.
    """
    today = date.today()
    companies = (
        db.query(models.Company)
        .filter(
            models.Company.follow_up_date.isnot(None),
            models.Company.status.notin_(
                [models.LeadStatus.SUCCESSFUL, models.LeadStatus.NOT_INTERESTED]
            ),
        )
        .order_by(models.Company.follow_up_date)
        .all()
    )
    overdue, due_today, upcoming = [], [], []
    for company in companies:
        if company.follow_up_date < today:
            overdue.append(company)
        elif company.follow_up_date == today:
            due_today.append(company)
        else:
            upcoming.append(company)
    return {"overdue": overdue, "due_today": due_today, "upcoming": upcoming}


def get_recent_activity(db: Session, limit: int = 20) -> list[models.ActivityLog]:
    return (
        db.query(models.ActivityLog)
        .options(joinedload(models.ActivityLog.company))
        .order_by(models.ActivityLog.created_at.desc(), models.ActivityLog.id.desc())
        .limit(limit)
        .all()
    )


# ----------------------------------------------------------------------------
# CSV import (Phase 4)
# ----------------------------------------------------------------------------
_NUMERIC_FIELDS = {"csr_spending", "revenue", "employee_count"}


def import_companies_from_rows(db: Session, rows: list[dict]) -> dict:
    """Create companies from parsed CSV rows (column headers = CompanyCreate
    field names). Unknown columns are ignored; rows missing a name, with an
    unparseable number, or matching an existing company (name/website) are
    reported rather than silently dropped.
    """
    allowed_fields = set(schemas.CompanyCreate.model_fields.keys())
    created = 0
    skipped_duplicates = 0
    errors: list[str] = []

    for i, row in enumerate(rows, start=2):  # row 1 is the header
        name = (row.get("name") or "").strip()
        if not name:
            errors.append(f"Row {i}: missing company name, skipped")
            continue

        data: dict = {"name": name}
        row_error = None
        for field in allowed_fields - {"name"}:
            raw = (row.get(field) or "").strip()
            if not raw:
                continue
            if field in _NUMERIC_FIELDS:
                try:
                    data[field] = int(float(raw)) if field == "employee_count" else float(raw)
                except ValueError:
                    row_error = f"Row {i}: invalid number for '{field}' ('{raw}'), row skipped"
                    break
            else:
                data[field] = raw
        if row_error:
            errors.append(row_error)
            continue

        try:
            payload = schemas.CompanyCreate(**data)
        except ValidationError as exc:
            errors.append(f"Row {i}: {exc.errors()[0]['msg']}, row skipped")
            continue
        if find_duplicate_company(db, payload.name, payload.website):
            skipped_duplicates += 1
            continue
        create_company(db, payload)
        created += 1

    return {"created": created, "skipped_duplicates": skipped_duplicates, "errors": errors}


# ----------------------------------------------------------------------------
# Tags (Phase 5)
# ----------------------------------------------------------------------------
def list_tags(db: Session) -> list[models.Tag]:
    return db.query(models.Tag).order_by(models.Tag.name).all()


def get_tag(db: Session, tag_id: int) -> Optional[models.Tag]:
    return db.query(models.Tag).filter(models.Tag.id == tag_id).first()


def get_or_create_tag(db: Session, name: str) -> models.Tag:
    clean = name.strip()
    tag = db.query(models.Tag).filter(models.Tag.name.ilike(clean)).first()
    if tag is not None:
        return tag
    tag = models.Tag(name=clean)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


def delete_tag(db: Session, tag: models.Tag) -> None:
    db.delete(tag)
    db.commit()


def add_tag_to_company(db: Session, company: models.Company, tag: models.Tag) -> models.Company:
    if tag not in company.tags:
        company.tags.append(tag)
        _log_activity(db, company.id, "tag_added", f"Tag '{tag.name}' added")
        db.commit()
        db.refresh(company)
    return company


def remove_tag_from_company(db: Session, company: models.Company, tag: models.Tag) -> models.Company:
    if tag in company.tags:
        company.tags.remove(tag)
        _log_activity(db, company.id, "tag_removed", f"Tag '{tag.name}' removed")
        db.commit()
        db.refresh(company)
    return company


# ----------------------------------------------------------------------------
# Documents (Phase 5)
# ----------------------------------------------------------------------------
def add_document(
    db: Session, company_id: int, filename: str, content_type: Optional[str], data: bytes
) -> models.Document:
    document = models.Document(
        company_id=company_id,
        filename=filename,
        content_type=content_type,
        size=len(data),
        data=data,
    )
    db.add(document)
    _log_activity(db, company_id, "document_added", f"Document '{filename}' uploaded")
    db.commit()
    db.refresh(document)
    return document


def get_document(db: Session, document_id: int) -> Optional[models.Document]:
    return db.query(models.Document).filter(models.Document.id == document_id).first()


def delete_document(db: Session, document: models.Document) -> None:
    db.delete(document)
    db.commit()


# ----------------------------------------------------------------------------
# Proposals (Phase 5)
# ----------------------------------------------------------------------------
def create_proposal(
    db: Session, company_id: int, payload: schemas.ProposalCreate
) -> models.Proposal:
    proposal = models.Proposal(company_id=company_id, **payload.model_dump())
    db.add(proposal)
    _log_activity(
        db, company_id, "proposal_added", f"Proposal '{proposal.title}' added ({proposal.stage.value})"
    )
    db.commit()
    db.refresh(proposal)
    return proposal


def get_proposal(db: Session, proposal_id: int) -> Optional[models.Proposal]:
    return db.query(models.Proposal).filter(models.Proposal.id == proposal_id).first()


def update_proposal(
    db: Session, proposal: models.Proposal, payload: schemas.ProposalUpdate
) -> models.Proposal:
    updates = payload.model_dump(exclude_unset=True)
    old_stage = proposal.stage
    for field, value in updates.items():
        setattr(proposal, field, value)
    if "stage" in updates and proposal.stage != old_stage:
        _log_activity(
            db,
            proposal.company_id,
            "proposal_stage_changed",
            f"Proposal '{proposal.title}' moved from {old_stage.value} to {proposal.stage.value}",
        )
    db.commit()
    db.refresh(proposal)
    return proposal


def delete_proposal(db: Session, proposal: models.Proposal) -> None:
    db.delete(proposal)
    db.commit()


# ----------------------------------------------------------------------------
# NGO Profile (Phase 5)
# ----------------------------------------------------------------------------
# Maps NGOProfile columns to the app.config.settings fields that scoring.py
# and ai.py actually read - kept in sync on every load/update so editing the
# profile takes effect immediately without threading a db session through
# every scoring/AI call site.
_NGO_SETTINGS_FIELDS = {
    "name": "ngo_name",
    "work_area": "ngo_work_area",
    "focus_areas": "ngo_focus_areas",
    "city": "ngo_city",
    "state": "ngo_state",
}


def _sync_settings_from_ngo_profile(profile: models.NGOProfile) -> None:
    for profile_field, settings_field in _NGO_SETTINGS_FIELDS.items():
        value = getattr(profile, profile_field)
        if value is not None:
            setattr(settings, settings_field, value)


def get_ngo_profile(db: Session) -> models.NGOProfile:
    profile = db.query(models.NGOProfile).filter(models.NGOProfile.id == 1).first()
    if profile is None:
        profile = models.NGOProfile(
            id=1,
            name=settings.ngo_name,
            work_area=settings.ngo_work_area,
            focus_areas=settings.ngo_focus_areas,
            city=settings.ngo_city,
            state=settings.ngo_state,
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
    _sync_settings_from_ngo_profile(profile)
    return profile


def update_ngo_profile(
    db: Session, profile: models.NGOProfile, payload: schemas.NGOProfileUpdate
) -> models.NGOProfile:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    db.commit()
    db.refresh(profile)
    _sync_settings_from_ngo_profile(profile)
    return profile
