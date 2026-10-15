"""Find publicly listed CSR decision makers for a company, and save them.

Works for a saved lead (company_id) and for a company that has only just
been discovered (name + website from company discovery). Results are
never stored automatically: staff pick contacts and save them, and saving
contacts for an unsaved company saves that company as a lead first.
Every run is recorded in contact_discovery_logs.
"""

import copy
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..company_discovery.base import UNAVAILABLE
from ..contact_discovery import policy
from ..contact_discovery.service import CompanyContext, ContactDiscoveryService, get_default_service
from ..database import get_db
from .company_discovery import create_lead, find_saved_lead

router = APIRouter(prefix="/api/contact-discovery", tags=["contact discovery"])


def get_contact_discovery_service() -> ContactDiscoveryService:
    return get_default_service()


@router.post("/search", response_model=schemas.ContactDiscoveryResult)
def find_contacts(
    payload: schemas.ContactDiscoveryRequest,
    service: ContactDiscoveryService = Depends(get_contact_discovery_service),
    db: Session = Depends(get_db),
):
    if payload.company_id is not None:
        saved = crud.get_company(db, payload.company_id)
        if saved is None:
            raise HTTPException(status_code=404, detail="Company not found")
        name = saved.name
    else:
        name = (payload.name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="A company name or company_id is required.")
        saved = find_saved_lead(db, name, payload.website)

    # Saved values win; discovery's values fill the gaps.
    pick = lambda field: (getattr(saved, field) if saved else None) or getattr(payload, field)  # noqa: E731
    ctx = CompanyContext(
        name=name,
        website=pick("website"),
        city=pick("city"),
        state=pick("state"),
        industry=pick("industry"),
        csr_report_url=pick("csr_report_url"),
        company_id=saved.id if saved else None,
    )
    result = copy.deepcopy(service.find(ctx, include_reports=payload.include_reports, refresh=payload.refresh))
    result["company"]["company_id"] = ctx.company_id
    result["saved_company_id"] = ctx.company_id

    if saved is not None:
        for contact in result["contacts"]:
            duplicate = crud.find_duplicate_contact(
                db, saved.id, contact["name"], contact["email"], contact["linkedin_url"]
            )
            contact["saved_contact_id"] = duplicate.id if duplicate else None

    if not result.get("cached"):
        result["log_id"] = crud.create_contact_discovery_log(db, ctx.company_id, result).id
    return result


def _apply_work_info_rules(item: schemas.DiscoveredContactIn, domain: str, dropped: list[str]) -> None:
    """Re-check the official-work-details-only rules on what the client sent."""
    if item.email and not policy.is_acceptable_email(item.email, domain):
        dropped.append(f"{item.name}: email {item.email} isn't an official work address, so it wasn't saved")
        item.email = None
        item.provenance["email"] = schemas.FieldProvenanceOut(status=UNAVAILABLE)
    if item.phone and not policy.is_office_phone(item.phone, "tel"):
        dropped.append(f"{item.name}: {item.phone} looks like a mobile number, so it wasn't saved")
        item.phone = None
        item.provenance["phone"] = schemas.FieldProvenanceOut(status=UNAVAILABLE)
    if item.linkedin_url and not policy.is_linkedin_profile(item.linkedin_url):
        item.linkedin_url = None
        item.provenance["linkedin_url"] = schemas.FieldProvenanceOut(status=UNAVAILABLE)


@router.post("/save", response_model=schemas.ContactSaveResult)
def save_contacts(payload: schemas.ContactSaveRequest, db: Session = Depends(get_db)):
    company_created = False
    if payload.company_id is not None:
        company = crud.get_company(db, payload.company_id)
        if company is None:
            raise HTTPException(status_code=404, detail="Company not found")
    elif payload.company is not None:
        # Contacts always attach to the saved lead - existing or new.
        company = find_saved_lead(db, payload.company.name, payload.company.website)
        if company is None:
            company = create_lead(db, payload.company)
            company_created = True
            crud.link_discovery_logs_to_company(db, company)
    else:
        raise HTTPException(status_code=400, detail="company_id or company is required.")

    domain = policy.domain_of(company.website)
    saved, duplicates, dropped = [], [], []
    for index, original in enumerate(payload.contacts):
        item = original.model_copy(deep=True)
        _apply_work_info_rules(item, domain, dropped)
        if not payload.force:
            duplicate = crud.find_duplicate_contact(db, company.id, item.name, item.email, item.linkedin_url)
            if duplicate is not None:
                duplicates.append(
                    schemas.ContactDuplicate(
                        index=index,
                        name=item.name,
                        existing_contact_id=duplicate.id,
                        existing_contact_name=duplicate.name,
                        existing_contact_email=duplicate.email,
                    )
                )
                continue
        labels = [s.label or s.url for s in item.sources] or ([item.source_url] if item.source_url else [])
        summary = "found on " + "; ".join(labels[:3]) if labels else "public sources"
        saved.append(crud.create_discovered_contact(db, company.id, item, summary))

    return schemas.ContactSaveResult(
        company_id=company.id,
        company_created=company_created,
        saved=saved,
        duplicates=duplicates,
        dropped=dropped,
    )


@router.get("/logs", response_model=list[schemas.ContactDiscoveryLogOut])
def list_logs(
    company_id: Optional[int] = None,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return crud.list_contact_discovery_logs(db, company_id=company_id, limit=limit)
