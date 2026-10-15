"""Email automation logic: drafts, manual-approval sending, reply sync and
classification, conversation outcomes, follow-ups, meetings, metrics.

The one rule everything here keeps: **nothing is sent without a person
approving it.** `send()` is only reachable from the send endpoint, which
requires `confirm: true` plus the exact recipient, subject and body the
person saw. Background work (reply sync, due follow-ups) only ever
*creates drafts*.

Timeline: every step that matters to staff (email generated, draft saved,
sent, reply received, meeting scheduled, proposal sent, status updated)
is written to the existing ActivityLog with the contact's id, so it shows
on both the company's and the contact's timeline. Lower-level delivery
history goes to email_events.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional

from sqlalchemy.orm import Session, joinedload

from .. import ai, crud, models, schemas
from ..config import settings
from . import classify as classifier
from . import crypto, states, templates
from .providers import EmailProvider, ProviderAuthError, ProviderError, get_provider
from .providers.base import OutgoingMessage

logger = logging.getLogger("mail")

SYNC_LOOKBACK_DAYS = 120


class MailError(Exception):
    """A user-facing failure; routers turn it into an HTTP error."""

    def __init__(self, message: str, status_code: int = 400, code: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite hands back naive datetimes even for timezone=True columns."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# ----------------------------------------------------------------------------
# Settings & templates
# ----------------------------------------------------------------------------
def get_settings(db: Session) -> models.EmailSettings:
    row = db.get(models.EmailSettings, 1)
    if row is None:
        row = models.EmailSettings(id=1, followup_intervals="3,7,14,30", default_followup_days=7)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def followup_intervals(row: models.EmailSettings) -> list[int]:
    days = []
    for part in (row.followup_intervals or "").split(","):
        try:
            value = int(part.strip())
        except ValueError:
            continue
        if 0 < value <= 365 and value not in days:
            days.append(value)
    return sorted(days) or [3, 7, 14, 30]


def update_settings(db: Session, payload: schemas.EmailSettingsUpdate) -> models.EmailSettings:
    row = get_settings(db)
    data = payload.model_dump(exclude_unset=True)
    if "followup_intervals" in data and data["followup_intervals"] is not None:
        data["followup_intervals"] = ",".join(str(d) for d in sorted(set(data["followup_intervals"])))
    for key, value in data.items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


def ensure_templates(db: Session) -> None:
    if db.query(models.EmailTemplate).count() == 0:
        for template in templates.DEFAULT_TEMPLATES:
            db.add(models.EmailTemplate(**template))
        db.commit()


def template_for(db: Session, email_type: str) -> models.EmailTemplate:
    ensure_templates(db)
    row = (
        db.query(models.EmailTemplate)
        .filter(models.EmailTemplate.email_type == email_type)
        .order_by(models.EmailTemplate.id)
        .first()
    )
    if row is None:
        row = db.query(models.EmailTemplate).filter(models.EmailTemplate.email_type == "first_outreach").first()
    return row


# ----------------------------------------------------------------------------
# Timeline helpers
# ----------------------------------------------------------------------------
def _event(db: Session, company_id: int, event_type: str, detail: str = "", *, email=None, thread=None) -> None:
    db.add(
        models.EmailEvent(
            company_id=company_id,
            email_id=email.id if email is not None else None,
            thread_id=thread.id if thread is not None else (email.thread_id if email is not None else None),
            event_type=event_type,
            detail=detail,
        )
    )


def _timeline(db: Session, company_id: int, event_type: str, description: str, contact_id: Optional[int]) -> None:
    crud._log_activity(db, company_id, event_type, description, contact_id=contact_id)


def _who(contact: Optional[models.Contact], fallback: Optional[str] = None) -> str:
    return contact.name if contact is not None else (fallback or "the company")


# ----------------------------------------------------------------------------
# Drafting
# ----------------------------------------------------------------------------
def _conversation_text(thread: Optional[models.EmailThread]) -> Optional[str]:
    if thread is None:
        return None
    parts = []
    for email in thread.emails[-4:]:
        if email.status in ("sent", "received"):
            who = "NGO" if email.direction == "outbound" else (email.from_name or email.from_email or "Company")
            parts.append(f"[{who}] {email.subject}\n{email.body[:1200]}")
    return "\n\n".join(parts) or None


def generate_content(
    db: Session,
    company: models.Company,
    contact: Optional[models.Contact],
    email_type: str,
    *,
    use_ai: bool = True,
    thread: Optional[models.EmailThread] = None,
) -> tuple[str, str, str]:
    """(subject, body, generated_by). AI when configured and wanted,
    otherwise the email type's template. The signature is part of the body
    so the draft shows exactly what will be sent.
    """
    profile = crud.get_ngo_profile(db)
    row = get_settings(db)
    context = templates.build_context(
        contact_name=contact.name if contact else None,
        contact_designation=contact.designation if contact else None,
        company_name=company.name,
        csr_focus=company.csr_focus,
        ngo_name=profile.name,
        ngo_work_area=profile.work_area or settings.ngo_work_area,
        sender_name=row.sender_name,
        signature=row.signature,
    )
    reply_subject = None
    if thread is not None and thread.subject:
        reply_subject = thread.subject if thread.subject.lower().startswith("re:") else f"Re: {thread.subject}"

    if use_ai and ai.is_configured():
        result = ai.generate_email(
            ngo_name=profile.name,
            ngo_work_area=context["ngo_work_area"],
            company_name=company.name,
            contact_name=contact.name if contact else None,
            contact_designation=contact.designation if contact else None,
            csr_focus=company.csr_focus,
            email_type=email_type,
            context=_conversation_text(thread),
            sender_name=context["sender_name"],
        )
        if result:
            body = result["body"].rstrip() + "\n\n" + context["signature"]
            return reply_subject or result["subject"], body, "ai"

    template = template_for(db, email_type)
    subject = templates.render(template.subject, context)
    body = templates.render(template.body, context)
    return reply_subject or subject, body, "template"


def _new_thread(db: Session, company: models.Company, contact: Optional[models.Contact], subject: str) -> models.EmailThread:
    thread = models.EmailThread(
        company_id=company.id, contact_id=contact.id if contact else None, subject=subject, status="draft"
    )
    db.add(thread)
    db.flush()
    return thread


def create_draft(
    db: Session,
    *,
    company: models.Company,
    contact: Optional[models.Contact],
    email_type: str = "first_outreach",
    use_ai: bool = True,
    subject: Optional[str] = None,
    body: Optional[str] = None,
    thread: Optional[models.EmailThread] = None,
    generated_by: Optional[str] = None,
    duplicated_from: Optional[models.Email] = None,
) -> models.Email:
    if contact is not None and contact.company_id != company.id:
        raise MailError("That contact belongs to a different company.")
    if subject is None or body is None:
        subject, body, generated_by = generate_content(db, company, contact, email_type, use_ai=use_ai, thread=thread)
    if thread is None:
        thread = _new_thread(db, company, contact, subject)
    email = models.Email(
        thread_id=thread.id,
        company_id=company.id,
        contact_id=contact.id if contact else None,
        direction="outbound",
        status="draft",
        email_type=email_type,
        generated_by=generated_by or "manual",
        subject=subject,
        body=body,
        to_email=contact.email if contact else None,
        to_name=contact.name if contact else None,
        duplicated_from_id=duplicated_from.id if duplicated_from else None,
    )
    db.add(email)
    db.flush()
    label = states.EMAIL_TYPES.get(email_type, email_type)
    contact_id = contact.id if contact else None
    if email.generated_by in ("ai", "template"):
        how = "AI" if email.generated_by == "ai" else "template"
        _event(db, company.id, "generated", f"{label} generated from {how}", email=email)
        _timeline(db, company.id, "email_generated", f"{label} email generated for {_who(contact)} ({how})", contact_id)
    else:
        verb = "duplicated" if duplicated_from else "saved"
        _event(db, company.id, "draft_saved", f"Draft {verb}", email=email)
        _timeline(db, company.id, "draft_saved", f"Draft {verb} for {_who(contact)}: {subject[:80]}", contact_id)
    db.commit()
    db.refresh(email)
    return email


def update_draft(db: Session, email: models.Email, payload: schemas.EmailDraftUpdate) -> models.Email:
    if email.direction != "outbound" or email.status not in ("draft", "failed"):
        raise MailError("Only drafts can be edited - this email has already been sent.", 409)
    data = payload.model_dump(exclude_unset=True)
    if "contact_id" in data:
        contact = db.get(models.Contact, data["contact_id"]) if data["contact_id"] else None
        if data["contact_id"] and (contact is None or contact.company_id != email.company_id):
            raise MailError("That contact doesn't belong to this company.")
        email.contact_id = contact.id if contact else None
        email.to_email = contact.email if contact else None
        email.to_name = contact.name if contact else None
        if email.thread.status == "draft":
            email.thread.contact_id = email.contact_id
    for field in ("subject", "body", "to_email", "email_type"):
        if field in data and data[field] is not None:
            setattr(email, field, data[field])
    if email.thread.status == "draft" and "subject" in data:
        email.thread.subject = email.subject
    if email.status == "failed":
        email.status, email.error = "draft", None
    _event(db, email.company_id, "draft_saved", "Draft edited and saved", email=email)
    _timeline(db, email.company_id, "draft_saved", f"Draft saved: {email.subject[:80]}", email.contact_id)
    db.commit()
    db.refresh(email)
    return email


def delete_draft(db: Session, email: models.Email) -> None:
    if email.direction != "outbound" or email.status not in ("draft", "failed"):
        raise MailError("Sent emails and replies can't be deleted - they're part of the conversation record.", 409)
    thread = email.thread
    for followup in db.query(models.FollowUp).filter(models.FollowUp.draft_email_id == email.id):
        followup.draft_email_id = None
        if followup.status == "drafted":
            followup.status, followup.cancel_reason = "cancelled", "Draft deleted"
    db.delete(email)
    db.flush()
    if thread is not None and not thread.emails:
        db.delete(thread)
    db.commit()


def duplicate(db: Session, email: models.Email, contact: Optional[models.Contact]) -> models.Email:
    """A new draft with the same content, as a new conversation - to the
    same contact or another contact at the same company.
    """
    if email.direction != "outbound":
        raise MailError("Only emails you wrote can be duplicated.")
    company = db.get(models.Company, email.company_id)
    target = contact if contact is not None else email.contact
    return create_draft(
        db,
        company=company,
        contact=target,
        email_type=email.email_type or "first_outreach",
        subject=email.subject,
        body=email.body,
        generated_by="duplicate",
        duplicated_from=email,
    )


def followup_draft(db: Session, thread: models.EmailThread, *, use_ai: bool = True) -> models.Email:
    """A follow-up in the same conversation (sent as a reply in-thread)."""
    if not any(e.status == "sent" for e in thread.emails):
        raise MailError("Send the first email in this conversation before drafting a follow-up.", 409)
    company = db.get(models.Company, thread.company_id)
    contact = db.get(models.Contact, thread.contact_id) if thread.contact_id else None
    return create_draft(db, company=company, contact=contact, email_type="follow_up", use_ai=use_ai, thread=thread)


# ----------------------------------------------------------------------------
# Mailbox account & OAuth
# ----------------------------------------------------------------------------
def get_account(db: Session, provider_key: Optional[str] = None) -> Optional[models.EmailAccount]:
    query = db.query(models.EmailAccount).filter(models.EmailAccount.status != "disconnected")
    if provider_key:
        query = query.filter(models.EmailAccount.provider == provider_key)
    return query.order_by(models.EmailAccount.connected_at.desc(), models.EmailAccount.id.desc()).first()


def connect_account(db: Session, provider: EmailProvider, code: str) -> models.EmailAccount:
    tokens = provider.exchange_code(code)
    if not tokens.refresh_token:
        raise MailError("Google didn't return a refresh token. Remove the app's access at "
                        "myaccount.google.com/permissions and connect again.")
    # One mailbox per provider: replace any earlier connection.
    for old in db.query(models.EmailAccount).filter(models.EmailAccount.provider == provider.key):
        old.status = "disconnected"
        old.encrypted_access_token = old.encrypted_refresh_token = None
    account = models.EmailAccount(
        provider=provider.key,
        email_address=tokens.email_address,
        encrypted_refresh_token=crypto.encrypt(tokens.refresh_token),
        encrypted_access_token=crypto.encrypt(tokens.access_token),
        access_token_expires_at=tokens.expires_at,
        scopes=tokens.scopes,
        status="connected",
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def disconnect_account(db: Session, account: models.EmailAccount, provider: EmailProvider) -> None:
    token = crypto.decrypt(account.encrypted_refresh_token) or crypto.decrypt(account.encrypted_access_token)
    if token:
        provider.revoke(token)
    account.status = "disconnected"
    account.encrypted_access_token = account.encrypted_refresh_token = None
    account.access_token_expires_at = None
    db.commit()


def _access_token(db: Session, account: models.EmailAccount, provider: EmailProvider, force_refresh: bool = False) -> str:
    expires = _aware(account.access_token_expires_at)
    token = crypto.decrypt(account.encrypted_access_token)
    if token and not force_refresh and expires and expires > utcnow() + timedelta(seconds=60):
        return token
    refresh = crypto.decrypt(account.encrypted_refresh_token)
    if not refresh:
        _mark_account_error(db, account, "Stored Gmail authorisation can't be read (was TOKEN_ENCRYPTION_KEY changed?). Reconnect Gmail.")
    try:
        tokens = provider.refresh_access_token(refresh)
    except ProviderAuthError as exc:
        _mark_account_error(db, account, str(exc))
    account.encrypted_access_token = crypto.encrypt(tokens.access_token)
    account.access_token_expires_at = tokens.expires_at
    if tokens.refresh_token:
        account.encrypted_refresh_token = crypto.encrypt(tokens.refresh_token)
    account.status, account.last_error = "connected", None
    db.commit()
    return tokens.access_token


def _mark_account_error(db: Session, account: models.EmailAccount, message: str):
    account.status, account.last_error = "error", message
    db.commit()
    raise MailError(message, 409, code="reconnect_required")


# ----------------------------------------------------------------------------
# Sending (manual approval only)
# ----------------------------------------------------------------------------
def _sent_in_last_hour(db: Session) -> int:
    since = utcnow() - timedelta(hours=1)
    return (
        db.query(models.Email)
        .filter(models.Email.direction == "outbound", models.Email.status == "sent", models.Email.sent_at >= since)
        .count()
    )


def send(
    db: Session,
    email: models.Email,
    *,
    to_email: str,
    subject: str,
    body: str,
    followup_days: Optional[int] = None,
    provider_lookup: Callable[[str], EmailProvider] = get_provider,
) -> models.Email:
    """Send one approved email. Called only from POST /api/emails/{id}/send."""
    if email.direction != "outbound" or email.status not in ("draft", "failed"):
        raise MailError("This email has already been sent.", 409)
    subject, body, to_email = subject.strip(), body.strip(), to_email.strip().lower()
    if not subject or not body:
        raise MailError("Subject and body can't be empty.")
    account = get_account(db)
    if account is None or account.status == "disconnected":
        raise MailError("Connect a Gmail account in Settings before sending.", 409, code="not_connected")
    if account.status == "error":
        raise MailError(account.last_error or "Reconnect Gmail in Settings.", 409, code="reconnect_required")

    company = db.get(models.Company, email.company_id)
    # Only to people saved as this company's contacts: the app sends
    # outreach, not arbitrary mail, even if the API is called directly.
    recipient = next((c for c in company.contacts if c.email and c.email.strip().lower() == to_email), None)
    if recipient is None:
        raise MailError("Emails can only be sent to a contact saved for this company with that email address.")
    if _sent_in_last_hour(db) >= settings.max_emails_per_hour:
        raise MailError(
            f"Sending paused: {settings.max_emails_per_hour} emails were sent in the last hour (MAX_EMAILS_PER_HOUR).",
            429,
        )

    provider = provider_lookup(account.provider)
    row = get_settings(db)
    thread = email.thread
    previous = [e for e in thread.emails if e.id != email.id and e.rfc822_message_id and e.status in ("sent", "received")]
    email.subject, email.body, email.to_email = subject, body, to_email
    email.contact_id, email.to_name = recipient.id, recipient.name
    email.approved_at = utcnow()
    message = OutgoingMessage(
        from_email=account.email_address,
        from_name=row.sender_name or crud.get_ngo_profile(db).name,
        to_email=to_email,
        to_name=recipient.name,
        subject=subject,
        body=body,
        provider_thread_id=thread.provider_thread_id,
        in_reply_to=previous[-1].rfc822_message_id if previous else None,
    )
    try:
        token = _access_token(db, account, provider)
        try:
            sent = provider.send(token, message)
        except ProviderAuthError:
            sent = provider.send(_access_token(db, account, provider, force_refresh=True), message)
    except (ProviderError, MailError) as exc:
        reason = exc.message if isinstance(exc, MailError) else str(exc)
        email.status, email.error = "failed", reason
        _event(db, email.company_id, "failed", reason, email=email)
        _timeline(db, email.company_id, "email_failed", f"Email to {recipient.name} failed: {reason}", recipient.id)
        db.commit()
        raise MailError(f"Sending failed: {reason}", 502) from exc

    now = utcnow()
    email.status, email.error, email.sent_at = "sent", None, now
    email.provider, email.provider_message_id = provider.key, sent.provider_message_id
    email.rfc822_message_id = sent.rfc822_message_id
    email.from_email, email.from_name = account.email_address, message.from_name
    thread.provider = provider.key
    thread.provider_thread_id = thread.provider_thread_id or sent.provider_thread_id
    thread.contact_id = thread.contact_id or recipient.id
    thread.subject = thread.subject or subject
    thread.last_message_at = now
    for followup in db.query(models.FollowUp).filter(models.FollowUp.draft_email_id == email.id):
        followup.status, followup.completed_at = "sent", now
    _event(db, email.company_id, "sent", f"Sent to {to_email} via {provider.label}", email=email)
    _timeline(db, email.company_id, "email_sent", f"Email sent to {recipient.name} <{to_email}>: {subject[:80]}", recipient.id)
    if thread.status == "draft":
        set_thread_status(db, thread, "awaiting_reply", source="auto", log=False)
    if followup_days:
        schedule_followup(db, company=company, contact=recipient, thread=thread, days=followup_days, commit=False)
    db.commit()
    crud.update_company(db, company, schemas.CompanyUpdate(last_contacted_date=date.today()))
    db.refresh(email)
    return email


# ----------------------------------------------------------------------------
# Conversation outcome
# ----------------------------------------------------------------------------
_OUTCOME_EVENTS = {"meeting_scheduled": "meeting_scheduled", "proposal_sent": "proposal_sent"}


def set_thread_status(
    db: Session, thread: models.EmailThread, status: str, *, source: str = "manual", log: bool = True
) -> models.EmailThread:
    if status not in states.THREAD_STATUSES:
        raise MailError(f"Unknown conversation status '{status}'.")
    old = thread.status
    if old != status:
        thread.status, thread.status_source = status, source
        contact = db.get(models.Contact, thread.contact_id) if thread.contact_id else None
        label = f"{states.THREAD_STATUSES.get(old, old)} → {states.THREAD_STATUSES[status]}"
        _event(db, thread.company_id, "status_changed", label, thread=thread)
        if log:
            event_type = _OUTCOME_EVENTS.get(status, "status_updated")
            _timeline(db, thread.company_id, event_type, f"Conversation with {_who(contact)}: {label}", thread.contact_id)
        if status in ("partnership_confirmed", "closed", "negative"):
            cancel_followups(db, thread, f"Conversation marked {states.THREAD_STATUSES[status]}")
    db.flush()
    company = db.get(models.Company, thread.company_id)
    target = states.lead_status_for(status, company.status)
    if target is not None:
        crud.update_company(db, company, schemas.CompanyUpdate(status=target))  # logs "Status changed", commits
    else:
        db.commit()
    return thread


# ----------------------------------------------------------------------------
# Replies
# ----------------------------------------------------------------------------
def apply_classification(
    db: Session, email: models.Email, result: dict, *, method: Optional[str] = None
) -> models.ReplyClassification:
    method = method or result.get("method", "ai")
    row = models.ReplyClassification(
        email_id=email.id,
        classification=result["classification"],
        confidence=result.get("confidence"),
        reasoning=result.get("reasoning"),
        intent=result.get("intent") or "none",
        method=method,
    )
    db.add(row)
    db.flush()
    label = states.CLASSIFICATIONS.get(row.classification, row.classification)
    confidence = f" ({round(row.confidence * 100)}%)" if row.confidence is not None else ""
    _event(db, email.company_id, "classified", f"{label}{confidence} by {method}", email=email)
    thread = email.thread
    new_status = states.thread_status_for_reply(row.classification, row.intent)
    if thread.status in states.AUTO_REPLACEABLE:
        set_thread_status(db, thread, new_status, source="manual" if method == "manual" else "auto")
    else:
        db.commit()
    return row


def classify_email(db: Session, email: models.Email) -> models.ReplyClassification:
    if email.direction != "inbound":
        raise MailError("Only replies can be classified.")
    company = db.get(models.Company, email.company_id)
    ours = next((e for e in reversed(email.thread.emails) if e.direction == "outbound" and e.status == "sent"), None)
    result = classifier.classify(
        email.body, company_name=company.name, ngo_name=crud.get_ngo_profile(db).name, our_email=ours.body if ours else None
    )
    return apply_classification(db, email, result)


def override_classification(db: Session, email: models.Email, classification: str, intent: Optional[str]) -> models.ReplyClassification:
    if email.direction != "inbound":
        raise MailError("Only replies can be classified.")
    if classification not in states.CLASSIFICATIONS:
        raise MailError(f"Unknown classification '{classification}'.")
    if intent is not None and intent not in states.INTENTS:
        raise MailError(f"Unknown intent '{intent}'.")
    result = {"classification": classification, "confidence": 1.0, "reasoning": "Set by staff.", "intent": intent or "none"}
    row = apply_classification(db, email, result, method="manual")
    contact = db.get(models.Contact, email.contact_id) if email.contact_id else None
    crud._log_activity(
        db, email.company_id, "status_updated",
        f"Reply from {_who(contact, email.from_name)} re-classified as {states.CLASSIFICATIONS[classification]}",
        contact_id=email.contact_id,
    )
    db.commit()
    return row


def _record_reply(db, thread, message, account) -> models.Email:
    contact = db.get(models.Contact, thread.contact_id) if thread.contact_id else None
    email = models.Email(
        thread_id=thread.id,
        company_id=thread.company_id,
        contact_id=thread.contact_id,
        direction="inbound",
        status="received",
        subject=message.subject or "",
        body=message.body or "",
        from_email=message.from_email,
        from_name=message.from_name,
        to_email=account.email_address,
        provider=account.provider,
        provider_message_id=message.provider_message_id,
        rfc822_message_id=message.rfc822_message_id,
        received_at=message.sent_at or utcnow(),
    )
    db.add(email)
    db.flush()
    thread.last_message_at = email.received_at
    _event(db, thread.company_id, "reply_received", f"Reply from {message.from_email}", email=email)
    cancel_followups(db, thread, "Reply received")
    classification = classify_email(db, email)
    label = states.CLASSIFICATIONS.get(classification.classification, classification.classification)
    confidence = f", {round(classification.confidence * 100)}% confidence" if classification.confidence is not None else ""
    _timeline(
        db, thread.company_id, "reply_received",
        f"Reply received from {_who(contact, message.from_name or message.from_email)}: {label}{confidence}",
        thread.contact_id,
    )
    db.commit()
    return email


def _record_bounce(db, thread, message) -> None:
    sent = [e for e in thread.emails if e.direction == "outbound" and e.status == "sent"]
    target = sent[-1] if sent else None
    reason = (message.body or message.subject or "Delivery failed")[:300]
    db.add(
        models.Email(
            thread_id=thread.id, company_id=thread.company_id, contact_id=thread.contact_id, direction="inbound",
            status="bounce", subject=message.subject or "Delivery failure", body=message.body or "",
            from_email=message.from_email, provider_message_id=message.provider_message_id,
            received_at=message.sent_at or utcnow(),
        )
    )
    if target is not None:
        target.status, target.error = "failed", f"Bounced: {reason}"
        _event(db, thread.company_id, "bounced", reason, email=target)
        _timeline(db, thread.company_id, "email_failed", f"Email to {target.to_email} bounced", thread.contact_id)
    db.commit()


def _record_outside_send(db, thread, message, account) -> None:
    """A message staff sent from Gmail itself, in a conversation we track."""
    email = models.Email(
        thread_id=thread.id, company_id=thread.company_id, contact_id=thread.contact_id, direction="outbound",
        status="sent", generated_by="gmail", subject=message.subject or "", body=message.body or "",
        from_email=account.email_address, to_email=message.to_email, provider=account.provider,
        provider_message_id=message.provider_message_id, rfc822_message_id=message.rfc822_message_id,
        sent_at=message.sent_at or utcnow(),
    )
    db.add(email)
    db.flush()
    thread.last_message_at = email.sent_at
    _event(db, thread.company_id, "sent", "Sent from Gmail directly", email=email)
    _timeline(db, thread.company_id, "email_sent", f"Email sent from Gmail: {email.subject[:80]}", thread.contact_id)
    db.commit()


def sync(db: Session, provider_lookup: Callable[[str], EmailProvider] = get_provider) -> dict:
    """Check every tracked conversation for new messages. Reads only;
    never sends.
    """
    summary = {"connected": False, "threads_checked": 0, "new_replies": 0, "bounces": 0, "errors": []}
    account = get_account(db)
    if account is None or account.status != "connected":
        return summary
    summary["connected"] = True
    provider = provider_lookup(account.provider)
    token = _access_token(db, account, provider)
    since = utcnow() - timedelta(days=SYNC_LOOKBACK_DAYS)
    threads = (
        db.query(models.EmailThread)
        .options(joinedload(models.EmailThread.emails))
        .filter(
            models.EmailThread.provider == account.provider,
            models.EmailThread.provider_thread_id.isnot(None),
            models.EmailThread.status != "closed",
        )
        .all()
    )
    ours = account.email_address.lower()
    for thread in threads:
        last = _aware(thread.last_message_at)
        if last is not None and last < since:
            continue
        summary["threads_checked"] += 1
        try:
            try:
                messages = provider.thread_messages(token, thread.provider_thread_id)
            except ProviderAuthError:
                token = _access_token(db, account, provider, force_refresh=True)
                messages = provider.thread_messages(token, thread.provider_thread_id)
        except ProviderAuthError as exc:
            account.status, account.last_error = "error", str(exc)
            summary["errors"].append(f"Gmail authorisation failed: {exc}")
            break
        except ProviderError as exc:
            summary["errors"].append(f"{thread.subject or thread.id}: {exc}")
            continue
        known = {e.provider_message_id for e in thread.emails if e.provider_message_id}
        for message in sorted(messages, key=lambda m: m.sent_at or utcnow()):
            if message.provider_message_id in known:
                continue
            known.add(message.provider_message_id)
            if message.is_bounce:
                _record_bounce(db, thread, message)
                summary["bounces"] += 1
            elif message.from_email == ours:
                _record_outside_send(db, thread, message, account)
            else:
                _record_reply(db, thread, message, account)
                summary["new_replies"] += 1
    account.last_sync_at = utcnow()
    db.commit()
    return summary


# ----------------------------------------------------------------------------
# Follow-ups
# ----------------------------------------------------------------------------
def schedule_followup(
    db: Session,
    *,
    company: models.Company,
    contact: Optional[models.Contact],
    thread: Optional[models.EmailThread],
    days: Optional[int] = None,
    due_date: Optional[date] = None,
    note: Optional[str] = None,
    commit: bool = True,
) -> models.FollowUp:
    if due_date is None:
        if not days or days < 1:
            raise MailError("Choose a follow-up interval or a date.")
        due_date = date.today() + timedelta(days=days)
    followup = models.FollowUp(
        company_id=company.id,
        contact_id=contact.id if contact else (thread.contact_id if thread else None),
        thread_id=thread.id if thread else None,
        due_date=due_date,
        interval_days=days,
        status="scheduled",
        note=note,
    )
    db.add(followup)
    # Keep the existing follow-up reminders (dashboard lists, company page)
    # pointing at the nearest follow-up.
    if company.follow_up_date is None or company.follow_up_date > due_date or company.follow_up_date < date.today():
        company.follow_up_date = due_date
    when = f"in {days} days" if days else ""
    _timeline(
        db, company.id, "followup_scheduled",
        f"Follow-up scheduled for {due_date.isoformat()} {when}".strip(), followup.contact_id,
    )
    if commit:
        db.commit()
        db.refresh(followup)
    return followup


def cancel_followups(db: Session, thread: models.EmailThread, reason: str) -> int:
    pending = db.query(models.FollowUp).filter(
        models.FollowUp.thread_id == thread.id, models.FollowUp.status.in_(("scheduled", "drafted"))
    )
    count = 0
    for followup in pending:
        followup.status, followup.cancel_reason, followup.completed_at = "cancelled", reason, utcnow()
        count += 1
    return count


def generate_due_followups(db: Session, today: Optional[date] = None, *, use_ai: bool = True) -> list[models.FollowUp]:
    """Turn due follow-ups into drafts for staff to review. Never sends."""
    today = today or date.today()
    due = (
        db.query(models.FollowUp)
        .filter(models.FollowUp.status == "scheduled", models.FollowUp.due_date <= today)
        .order_by(models.FollowUp.due_date)
        .all()
    )
    drafted = []
    for followup in due:
        thread = db.get(models.EmailThread, followup.thread_id) if followup.thread_id else None
        if thread is not None and thread.status in ("closed", "partnership_confirmed", "negative"):
            followup.status, followup.cancel_reason = "cancelled", "Conversation closed"
            continue
        company = db.get(models.Company, followup.company_id)
        contact = db.get(models.Contact, followup.contact_id) if followup.contact_id else None
        try:
            if thread is not None and any(e.status == "sent" for e in thread.emails):
                draft = followup_draft(db, thread, use_ai=use_ai)
            else:
                draft = create_draft(db, company=company, contact=contact, email_type="follow_up", use_ai=use_ai)
        except MailError as exc:
            logger.info("Follow-up %s not drafted: %s", followup.id, exc.message)
            continue
        followup.status, followup.draft_email_id = "drafted", draft.id
        _timeline(
            db, company.id, "followup_drafted",
            f"Follow-up draft ready for review (was due {followup.due_date.isoformat()})", followup.contact_id,
        )
        drafted.append(followup)
    db.commit()
    return drafted


# ----------------------------------------------------------------------------
# Meetings
# ----------------------------------------------------------------------------
def create_meeting(db: Session, payload: schemas.MeetingCreate) -> models.Meeting:
    company = db.get(models.Company, payload.company_id)
    if company is None:
        raise MailError("Company not found", 404)
    thread = db.get(models.EmailThread, payload.thread_id) if payload.thread_id else None
    if thread is not None and thread.company_id != company.id:
        raise MailError("That conversation belongs to a different company.")
    contact_id = payload.contact_id or (thread.contact_id if thread else None)
    meeting = models.Meeting(**{**payload.model_dump(), "contact_id": contact_id})
    db.add(meeting)
    db.flush()
    _after_meeting_change(db, meeting, company, thread)
    db.refresh(meeting)
    return meeting


def update_meeting(db: Session, meeting: models.Meeting, payload: schemas.MeetingUpdate) -> models.Meeting:
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(meeting, key, value)
    db.flush()
    company = db.get(models.Company, meeting.company_id)
    thread = db.get(models.EmailThread, meeting.thread_id) if meeting.thread_id else None
    _after_meeting_change(db, meeting, company, thread)
    db.refresh(meeting)
    return meeting


def _after_meeting_change(db, meeting, company, thread) -> None:
    when = _aware(meeting.scheduled_at).strftime("%d %b %Y, %H:%M UTC") if meeting.scheduled_at else "date to be fixed"
    if meeting.status in ("scheduled", "completed"):
        _timeline(db, company.id, "meeting_scheduled", f"Meeting {meeting.status}: {meeting.title} ({when})", meeting.contact_id)
        if thread is not None and thread.status not in ("proposal_sent", "partnership_confirmed", "closed"):
            set_thread_status(db, thread, "meeting_scheduled", source="manual", log=False)
            return
        target = states.lead_status_for("meeting_scheduled", company.status)
        if target is not None:
            crud.update_company(db, company, schemas.CompanyUpdate(status=target))
            return
    elif meeting.status == "requested":
        _timeline(db, company.id, "status_updated", f"Meeting requested: {meeting.title}", meeting.contact_id)
    else:
        _timeline(db, company.id, "status_updated", f"Meeting cancelled: {meeting.title}", meeting.contact_id)
    db.commit()


# ----------------------------------------------------------------------------
# Dashboard metrics
# ----------------------------------------------------------------------------
def _rate(numerator: int, denominator: int) -> Optional[float]:
    return round(100 * numerator / denominator, 1) if denominator else None


def outreach_metrics(db: Session) -> dict:
    LS = models.LeadStatus
    companies = db.query(models.Company.id, models.Company.status).all()
    threads = db.query(models.EmailThread).options(joinedload(models.EmailThread.emails)).all()

    sent_threads, replied_threads, positive_threads = set(), set(), set()
    replied_companies, thread_stage = set(), {}
    positive = negative = replies = sent = generated = 0
    for thread in threads:
        for email in thread.emails:
            if email.direction == "outbound":
                if email.generated_by in ("ai", "template"):
                    generated += 1
                if email.status == "sent":
                    sent += 1
                    sent_threads.add(thread.id)
            elif email.status == "received":
                replies += 1
                replied_threads.add(thread.id)
                replied_companies.add(thread.company_id)
                latest = email.classifications[-1].classification if email.classifications else None
                if latest == "positive":
                    positive += 1
                    positive_threads.add(thread.id)
                elif latest == "negative":
                    negative += 1
        thread_stage.setdefault(thread.company_id, set()).add(thread.status)

    meeting_companies = {
        m.company_id for m in db.query(models.Meeting).filter(models.Meeting.status.in_(("scheduled", "completed")))
    }
    emailed_companies = {t.company_id for t in threads if t.id in sent_threads}
    meeting_stage = {LS.MEETING, LS.PROPOSAL_SENT, LS.SUCCESSFUL}
    proposal_stage = {LS.PROPOSAL_SENT, LS.SUCCESSFUL}
    meetings = proposals = partnerships = contacted = 0
    pipeline = {stage: 0 for stage in states.PIPELINE_STAGES}
    for company_id, status in companies:
        stages = thread_stage.get(company_id, set())
        if status in meeting_stage or company_id in meeting_companies or stages & {"meeting_scheduled"}:
            meetings += 1
        if status in proposal_stage or stages & {"proposal_sent", "partnership_confirmed"}:
            proposals += 1
        won = status == LS.SUCCESSFUL or "partnership_confirmed" in stages
        partnerships += int(won)
        contacted += int(status != LS.NEW or company_id in emailed_companies)
        if won:
            pipeline["Won"] += 1
        elif status == LS.NOT_INTERESTED:
            pipeline["Lost"] += 1
        elif status == LS.PROPOSAL_SENT:
            pipeline["Proposal"] += 1
        elif status == LS.MEETING:
            pipeline["Meeting"] += 1
        elif status in (LS.CONTACTED, LS.FOLLOW_UP):
            pipeline["Replied" if company_id in replied_companies else "Contacted"] += 1
        else:
            pipeline["New"] += 1

    today = date.today()
    open_followups = db.query(models.FollowUp).filter(models.FollowUp.status.in_(("scheduled", "drafted")))
    return {
        "metrics": {
            "total_companies": len(companies),
            "saved_leads": sum(1 for _, s in companies if s not in (LS.SUCCESSFUL, LS.NOT_INTERESTED)),
            "contacts": db.query(models.Contact).count(),
            "emails_generated": generated,
            "emails_sent": sent,
            "replies_received": replies,
            "positive_replies": positive,
            "negative_replies": negative,
            "meetings_scheduled": meetings,
            "proposals_sent": proposals,
            "partnerships": partnerships,
            "pending_followups": open_followups.filter(models.FollowUp.due_date >= today).count(),
            "overdue_followups": open_followups.filter(models.FollowUp.due_date < today).count(),
            "reply_rate": _rate(len(replied_threads & sent_threads), len(sent_threads)),
            "positive_reply_rate": _rate(len(positive_threads), len(replied_threads)),
            "conversion_rate": _rate(partnerships, contacted),
        },
        "pipeline": [{"stage": stage, "count": pipeline[stage]} for stage in states.PIPELINE_STAGES],
    }
