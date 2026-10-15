"""Outreach emails: drafts, manual-approval sending, conversations (threads),
reply classification, follow-ups and meetings. See docs/EMAIL_AUTOMATION.md.
"""

from datetime import date
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..mail import service, states
from ..mail.access import require_mailbox_access
from ..mail.providers import EmailProvider, get_provider

router = APIRouter(prefix="/api", tags=["emails"])


def get_provider_lookup() -> Callable[[str], EmailProvider]:
    return get_provider


# ----------------------------------------------------------------------------
# Serialization
# ----------------------------------------------------------------------------
def email_out(email: models.Email) -> schemas.EmailOut:
    out = schemas.EmailOut.model_validate(email)
    history = [schemas.ReplyClassificationOut.model_validate(c) for c in email.classifications]
    out.classification_history = history
    out.classification = history[-1] if history else None
    out.company_name = email.company.name if email.company else None
    out.contact_name = email.contact.name if email.contact else None
    out.thread_status = email.thread.status if email.thread else None
    return out


def followup_out(followup: models.FollowUp) -> schemas.FollowUpOut:
    out = schemas.FollowUpOut.model_validate(followup)
    out.company_name = followup.company.name if followup.company else None
    out.contact_name = followup.contact.name if followup.contact else None
    return out


def meeting_out(meeting: models.Meeting) -> schemas.MeetingOut:
    out = schemas.MeetingOut.model_validate(meeting)
    out.company_name = meeting.company.name if meeting.company else None
    out.contact_name = meeting.contact.name if meeting.contact else None
    return out


def thread_out(db: Session, thread: models.EmailThread, detail: bool = True) -> schemas.EmailThreadOut:
    out = schemas.EmailThreadOut(
        id=thread.id,
        company_id=thread.company_id,
        contact_id=thread.contact_id,
        subject=thread.subject,
        status=thread.status,
        status_label=states.THREAD_STATUSES.get(thread.status, thread.status),
        status_source=thread.status_source,
        provider=thread.provider,
        last_message_at=thread.last_message_at,
        created_at=thread.created_at,
        company_name=thread.company.name if thread.company else None,
        contact_name=thread.contact.name if thread.contact else None,
        contact_email=thread.contact.email if thread.contact else None,
        emails=[email_out(e) for e in thread.emails],
    )
    if detail:
        out.followups = [
            followup_out(f)
            for f in db.query(models.FollowUp).filter(models.FollowUp.thread_id == thread.id).order_by(models.FollowUp.due_date)
        ]
        out.meetings = [
            meeting_out(m) for m in db.query(models.Meeting).filter(models.Meeting.thread_id == thread.id).order_by(models.Meeting.id)
        ]
        out.events = [
            schemas.EmailEventOut.model_validate(e)
            for e in db.query(models.EmailEvent)
            .filter(models.EmailEvent.thread_id == thread.id)
            .order_by(models.EmailEvent.created_at, models.EmailEvent.id)
        ]
    return out


# ----------------------------------------------------------------------------
# Lookups
# ----------------------------------------------------------------------------
def _get(db: Session, model, object_id: int, label: str):
    row = db.get(model, object_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return row


def _contact_for(db: Session, company: models.Company, contact_id: Optional[int]) -> Optional[models.Contact]:
    if contact_id is None:
        return None
    contact = _get(db, models.Contact, contact_id, "Contact")
    if contact.company_id != company.id:
        raise HTTPException(status_code=400, detail="That contact belongs to a different company.")
    return contact


# ----------------------------------------------------------------------------
# Emails
# ----------------------------------------------------------------------------
@router.get("/emails", response_model=list[schemas.EmailOut])
def list_emails(
    company_id: Optional[int] = None,
    contact_id: Optional[int] = None,
    thread_id: Optional[int] = None,
    status: Optional[str] = None,
    direction: Optional[str] = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(models.Email)
    for column, value in (
        (models.Email.company_id, company_id),
        (models.Email.contact_id, contact_id),
        (models.Email.thread_id, thread_id),
        (models.Email.status, status),
        (models.Email.direction, direction),
    ):
        if value is not None:
            query = query.filter(column == value)
    rows = query.order_by(models.Email.updated_at.desc(), models.Email.id.desc()).offset(skip).limit(limit).all()
    return [email_out(e) for e in rows]


@router.post("/emails/generate", response_model=schemas.EmailOut, status_code=201)
def generate_email_draft(payload: schemas.EmailGenerateRequest, db: Session = Depends(get_db)):
    """Generate (AI or template) and save as a draft. Never sends."""
    if payload.email_type not in states.EMAIL_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown email type '{payload.email_type}'.")
    company = _get(db, models.Company, payload.company_id, "Company")
    thread = None
    if payload.thread_id is not None:
        thread = _get(db, models.EmailThread, payload.thread_id, "Conversation")
        if thread.company_id != company.id:
            raise HTTPException(status_code=400, detail="That conversation belongs to a different company.")
        return email_out(service.followup_draft(db, thread, use_ai=payload.use_ai))
    contact = _contact_for(db, company, payload.contact_id)
    return email_out(
        service.create_draft(db, company=company, contact=contact, email_type=payload.email_type, use_ai=payload.use_ai)
    )


@router.post("/emails", response_model=schemas.EmailOut, status_code=201)
def create_email_draft(payload: schemas.EmailDraftCreate, db: Session = Depends(get_db)):
    company = _get(db, models.Company, payload.company_id, "Company")
    contact = _contact_for(db, company, payload.contact_id)
    return email_out(
        service.create_draft(
            db, company=company, contact=contact, email_type=payload.email_type,
            subject=payload.subject, body=payload.body, generated_by="manual",
        )
    )


@router.get("/emails/{email_id}", response_model=schemas.EmailOut)
def get_email(email_id: int, db: Session = Depends(get_db)):
    return email_out(_get(db, models.Email, email_id, "Email"))


@router.patch("/emails/{email_id}", response_model=schemas.EmailOut)
def save_draft(email_id: int, payload: schemas.EmailDraftUpdate, db: Session = Depends(get_db)):
    return email_out(service.update_draft(db, _get(db, models.Email, email_id, "Email"), payload))


@router.delete("/emails/{email_id}", status_code=204)
def delete_draft(email_id: int, db: Session = Depends(get_db)):
    service.delete_draft(db, _get(db, models.Email, email_id, "Email"))


@router.post("/emails/{email_id}/duplicate", response_model=schemas.EmailOut, status_code=201)
def duplicate_email(email_id: int, payload: schemas.EmailDuplicateRequest, db: Session = Depends(get_db)):
    email = _get(db, models.Email, email_id, "Email")
    company = _get(db, models.Company, email.company_id, "Company")
    contact = _contact_for(db, company, payload.contact_id)
    return email_out(service.duplicate(db, email, contact))


@router.post(
    "/emails/{email_id}/send",
    response_model=schemas.EmailOut,
    dependencies=[Depends(require_mailbox_access)],
)
def send_email(
    email_id: int,
    payload: schemas.EmailSendRequest,
    db: Session = Depends(get_db),
    provider_lookup: Callable[[str], EmailProvider] = Depends(get_provider_lookup),
):
    """The only way an email is ever sent: an explicit, per-email approval."""
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Sending needs explicit confirmation (confirm: true).")
    email = _get(db, models.Email, email_id, "Email")
    sent = service.send(
        db, email, to_email=payload.to_email, subject=payload.subject, body=payload.body,
        followup_days=payload.followup_days, provider_lookup=provider_lookup,
    )
    return email_out(sent)


@router.post("/emails/{email_id}/classification", response_model=schemas.ReplyClassificationOut)
def override_classification(email_id: int, payload: schemas.ClassificationOverride, db: Session = Depends(get_db)):
    email = _get(db, models.Email, email_id, "Email")
    return service.override_classification(db, email, payload.classification, payload.intent)


@router.post("/emails/{email_id}/reclassify", response_model=schemas.ReplyClassificationOut)
def reclassify(email_id: int, db: Session = Depends(get_db)):
    return service.classify_email(db, _get(db, models.Email, email_id, "Email"))


# ----------------------------------------------------------------------------
# Conversations
# ----------------------------------------------------------------------------
@router.get("/email-threads", response_model=list[schemas.EmailThreadOut])
def list_threads(
    company_id: Optional[int] = None,
    contact_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(models.EmailThread)
    if company_id is not None:
        query = query.filter(models.EmailThread.company_id == company_id)
    if contact_id is not None:
        query = query.filter(models.EmailThread.contact_id == contact_id)
    if status:
        query = query.filter(models.EmailThread.status == status)
    rows = query.order_by(models.EmailThread.last_message_at.desc().nullsfirst(), models.EmailThread.id.desc()).limit(limit)
    return [thread_out(db, t, detail=company_id is not None or contact_id is not None) for t in rows]


@router.get("/email-threads/{thread_id}", response_model=schemas.EmailThreadOut)
def get_thread(thread_id: int, db: Session = Depends(get_db)):
    return thread_out(db, _get(db, models.EmailThread, thread_id, "Conversation"))


@router.patch("/email-threads/{thread_id}", response_model=schemas.EmailThreadOut)
def update_thread_status(thread_id: int, payload: schemas.ThreadStatusUpdate, db: Session = Depends(get_db)):
    thread = _get(db, models.EmailThread, thread_id, "Conversation")
    service.set_thread_status(db, thread, payload.status, source="manual")
    db.refresh(thread)
    return thread_out(db, thread)


@router.post("/email-threads/{thread_id}/followup-draft", response_model=schemas.EmailOut, status_code=201)
def draft_followup_now(thread_id: int, use_ai: bool = True, db: Session = Depends(get_db)):
    thread = _get(db, models.EmailThread, thread_id, "Conversation")
    return email_out(service.followup_draft(db, thread, use_ai=use_ai))


# ----------------------------------------------------------------------------
# Follow-ups
# ----------------------------------------------------------------------------
@router.get("/followups", response_model=list[schemas.FollowUpOut])
def list_followups(
    status: Optional[str] = None,
    company_id: Optional[int] = None,
    contact_id: Optional[int] = None,
    due_before: Optional[date] = None,
    db: Session = Depends(get_db),
):
    query = db.query(models.FollowUp)
    if status == "open":
        query = query.filter(models.FollowUp.status.in_(("scheduled", "drafted")))
    elif status:
        query = query.filter(models.FollowUp.status == status)
    if company_id is not None:
        query = query.filter(models.FollowUp.company_id == company_id)
    if contact_id is not None:
        query = query.filter(models.FollowUp.contact_id == contact_id)
    if due_before is not None:
        query = query.filter(models.FollowUp.due_date <= due_before)
    return [followup_out(f) for f in query.order_by(models.FollowUp.due_date, models.FollowUp.id).limit(500)]


@router.post("/followups", response_model=schemas.FollowUpOut, status_code=201)
def schedule_followup(payload: schemas.FollowUpCreate, db: Session = Depends(get_db)):
    thread = _get(db, models.EmailThread, payload.thread_id, "Conversation") if payload.thread_id else None
    company_id = thread.company_id if thread else payload.company_id
    if company_id is None:
        raise HTTPException(status_code=400, detail="Give a conversation (thread_id) or a company_id.")
    company = _get(db, models.Company, company_id, "Company")
    contact = _contact_for(db, company, payload.contact_id or (thread.contact_id if thread else None))
    if payload.due_date is not None and payload.due_date < date.today():
        raise HTTPException(status_code=400, detail="The follow-up date is in the past.")
    followup = service.schedule_followup(
        db, company=company, contact=contact, thread=thread, days=payload.days, due_date=payload.due_date,
        note=payload.note,
    )
    return followup_out(followup)


@router.patch("/followups/{followup_id}", response_model=schemas.FollowUpOut)
def update_followup(followup_id: int, payload: schemas.FollowUpUpdate, db: Session = Depends(get_db)):
    followup = _get(db, models.FollowUp, followup_id, "Follow-up")
    data = payload.model_dump(exclude_unset=True)
    if "status" in data and data["status"] != "cancelled":
        raise HTTPException(status_code=400, detail="A follow-up can only be cancelled by hand.")
    if followup.status in ("sent", "cancelled") and data:
        raise HTTPException(status_code=409, detail="This follow-up is already finished.")
    if data.get("status") == "cancelled":
        followup.status, followup.cancel_reason, followup.completed_at = "cancelled", "Cancelled by staff", service.utcnow()
    if data.get("due_date"):
        followup.due_date = data["due_date"]
    if "note" in data:
        followup.note = data["note"]
    db.commit()
    db.refresh(followup)
    return followup_out(followup)


@router.post("/followups/generate-due", response_model=list[schemas.FollowUpOut])
def generate_due_followups(use_ai: bool = True, db: Session = Depends(get_db)):
    """Create drafts for follow-ups that are due. Never sends."""
    return [followup_out(f) for f in service.generate_due_followups(db, use_ai=use_ai)]


# ----------------------------------------------------------------------------
# Meetings
# ----------------------------------------------------------------------------
@router.get("/meetings", response_model=list[schemas.MeetingOut])
def list_meetings(company_id: Optional[int] = None, contact_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(models.Meeting)
    if company_id is not None:
        query = query.filter(models.Meeting.company_id == company_id)
    if contact_id is not None:
        query = query.filter(models.Meeting.contact_id == contact_id)
    return [meeting_out(m) for m in query.order_by(models.Meeting.scheduled_at.desc().nullslast(), models.Meeting.id.desc())]


@router.post("/meetings", response_model=schemas.MeetingOut, status_code=201)
def create_meeting(payload: schemas.MeetingCreate, db: Session = Depends(get_db)):
    if payload.status not in states.MEETING_STATUSES:
        raise HTTPException(status_code=400, detail=f"Unknown meeting status '{payload.status}'.")
    company = _get(db, models.Company, payload.company_id, "Company")
    _contact_for(db, company, payload.contact_id)
    return meeting_out(service.create_meeting(db, payload))


@router.patch("/meetings/{meeting_id}", response_model=schemas.MeetingOut)
def update_meeting(meeting_id: int, payload: schemas.MeetingUpdate, db: Session = Depends(get_db)):
    if payload.status is not None and payload.status not in states.MEETING_STATUSES:
        raise HTTPException(status_code=400, detail=f"Unknown meeting status '{payload.status}'.")
    return meeting_out(service.update_meeting(db, _get(db, models.Meeting, meeting_id, "Meeting"), payload))


@router.delete("/meetings/{meeting_id}", status_code=204)
def delete_meeting(meeting_id: int, db: Session = Depends(get_db)):
    db.delete(_get(db, models.Meeting, meeting_id, "Meeting"))
    db.commit()
