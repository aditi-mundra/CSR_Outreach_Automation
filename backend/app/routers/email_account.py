"""Mailbox connection (OAuth), email settings, templates and reply sync."""

from typing import Callable
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import models, schemas
from ..config import settings
from ..database import get_db
from ..mail import crypto, service, states
from ..mail.access import require_mailbox_access
from ..mail.providers import PROVIDERS, EmailProvider, ProviderError
from ..mail.templates import DEFAULT_TEMPLATES
from .emails import get_provider_lookup

router = APIRouter(prefix="/api/email", tags=["email settings"])


def _provider(key: str, lookup: Callable[[str], EmailProvider]) -> EmailProvider:
    try:
        return lookup(key)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown email provider '{key}'.")


def _settings_out(row: models.EmailSettings) -> schemas.EmailSettingsOut:
    return schemas.EmailSettingsOut(
        sender_name=row.sender_name,
        signature=row.signature,
        followup_intervals=service.followup_intervals(row),
        default_followup_days=row.default_followup_days,
        updated_at=row.updated_at,
    )


@router.get("/account", response_model=schemas.EmailAccountStatus)
def account_status(db: Session = Depends(get_db)):
    account = service.get_account(db)
    return schemas.EmailAccountStatus(
        providers=[
            schemas.EmailProviderInfo(
                key=p.key, label=p.label, configured=p.is_configured(), setup_hint=p.setup_hint(),
                capabilities=schemas.ProviderCapabilities(**vars(p.capabilities)),
            )
            for p in PROVIDERS.values()
        ],
        account=schemas.EmailAccountOut.model_validate(account) if account else None,
        encryption_configured=crypto.is_configured(),
        access_token_required=bool(settings.app_access_token),
        sync_minutes=settings.email_sync_minutes,
        max_emails_per_hour=settings.max_emails_per_hour,
    )


@router.get("/meta")
def email_meta():
    """Labels for statuses/types, so the UI and API share one vocabulary."""
    return {
        "thread_statuses": states.THREAD_STATUSES,
        "classifications": states.CLASSIFICATIONS,
        "email_types": states.EMAIL_TYPES,
        "intents": list(states.INTENTS),
        "followup_statuses": list(states.FOLLOWUP_STATUSES),
        "meeting_statuses": list(states.MEETING_STATUSES),
    }


@router.post(
    "/oauth/{provider_key}/start",
    response_model=schemas.OAuthStart,
    dependencies=[Depends(require_mailbox_access)],
)
def start_oauth(provider_key: str, lookup: Callable[[str], EmailProvider] = Depends(get_provider_lookup)):
    provider = _provider(provider_key, lookup)
    if not provider.is_configured():
        raise HTTPException(status_code=409, detail=f"{provider.label} isn't set up on the server. {provider.setup_hint()}")
    if not crypto.is_configured():
        raise HTTPException(
            status_code=409,
            detail="TOKEN_ENCRYPTION_KEY isn't set, so mailbox tokens can't be stored securely. See docs/EMAIL_AUTOMATION.md.",
        )
    return schemas.OAuthStart(authorization_url=provider.authorization_url(crypto.make_state(provider.key)))


def _back_to_app(**params) -> RedirectResponse:
    return RedirectResponse(f"{settings.frontend_url.rstrip('/')}/settings?{urlencode(params)}", status_code=303)


@router.get("/oauth/{provider_key}/callback")
def oauth_callback(
    provider_key: str,
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_db),
    lookup: Callable[[str], EmailProvider] = Depends(get_provider_lookup),
):
    """Google redirects here. Protected by the signed `state`, which only
    the (access-token-guarded) start endpoint issues.
    """
    if error:
        return _back_to_app(email="error", message=f"Google sign-in was cancelled or refused ({error}).")
    if not crypto.is_configured() or not crypto.verify_state(state, provider_key):
        return _back_to_app(email="error", message="The sign-in link expired or wasn't started from this app. Try again.")
    provider = _provider(provider_key, lookup)
    try:
        account = service.connect_account(db, provider, code)
    except (ProviderError, service.MailError) as exc:
        return _back_to_app(email="error", message=getattr(exc, "message", None) or str(exc))
    return _back_to_app(email="connected", account=account.email_address)


@router.delete("/account", status_code=204, dependencies=[Depends(require_mailbox_access)])
def disconnect(db: Session = Depends(get_db), lookup: Callable[[str], EmailProvider] = Depends(get_provider_lookup)):
    account = service.get_account(db)
    if account is None:
        raise HTTPException(status_code=404, detail="No mailbox is connected.")
    service.disconnect_account(db, account, _provider(account.provider, lookup))


@router.post("/sync", response_model=schemas.SyncResult, dependencies=[Depends(require_mailbox_access)])
def sync_now(db: Session = Depends(get_db), lookup: Callable[[str], EmailProvider] = Depends(get_provider_lookup)):
    """Check for replies and draft due follow-ups. Reads only; never sends."""
    drafted = service.generate_due_followups(db)
    summary = service.sync(db, provider_lookup=lookup)
    return schemas.SyncResult(**summary, followups_drafted=len(drafted))


@router.get("/settings", response_model=schemas.EmailSettingsOut)
def get_email_settings(db: Session = Depends(get_db)):
    return _settings_out(service.get_settings(db))


@router.patch("/settings", response_model=schemas.EmailSettingsOut)
def update_email_settings(payload: schemas.EmailSettingsUpdate, db: Session = Depends(get_db)):
    return _settings_out(service.update_settings(db, payload))


@router.get("/templates", response_model=list[schemas.EmailTemplateOut])
def list_templates(db: Session = Depends(get_db)):
    service.ensure_templates(db)
    return db.query(models.EmailTemplate).order_by(models.EmailTemplate.id).all()


@router.patch("/templates/{template_id}", response_model=schemas.EmailTemplateOut)
def update_template(template_id: int, payload: schemas.EmailTemplateUpdate, db: Session = Depends(get_db)):
    template = db.get(models.EmailTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(template, key, value)
    db.commit()
    db.refresh(template)
    return template


@router.post("/templates/reset", response_model=list[schemas.EmailTemplateOut])
def reset_templates(db: Session = Depends(get_db)):
    db.query(models.EmailTemplate).delete()
    for template in DEFAULT_TEMPLATES:
        db.add(models.EmailTemplate(**template))
    db.commit()
    return db.query(models.EmailTemplate).order_by(models.EmailTemplate.id).all()
