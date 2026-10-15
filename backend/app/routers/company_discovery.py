"""Real-company discovery: search public sources, save results as leads.

Discovery results live only in the response (and a short in-memory
cache) - a company is written to the database only when staff click
"Save as lead" (POST /api/discover/save). Lead scoring, AI summaries,
notes, contacts, documents and outreach tracking all hang off a saved
Company row, so they become available exactly at that point.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import crud, models, schemas
from ..company_discovery.base import (
    INFERRED,
    TRACKED_FIELDS,
    UNAVAILABLE,
    VERIFIED,
    DiscoveryQuery,
    normalize_company_name,
    normalize_domain,
)
from ..company_discovery.csr_focus import infer_csr_focus, is_public_website
from ..company_discovery.service import DiscoveryService, get_default_service
from ..database import get_db
from .companies import _to_detail

router = APIRouter(prefix="/api/discover", tags=["company discovery"])

_FIELD_LABELS = {
    "industry": "industry",
    "city": "city",
    "state": "state",
    "website": "website",
    "csr_focus": "CSR focus",
    "csr_spending": "CSR spending",
    "employee_count": "employee count",
    "csr_report_url": "CSR report link",
}
_IDENTIFIER_LABELS = {
    "wikidata": "Wikidata",
    "cin": "CIN",
    "isin": "ISIN",
    "nse_symbol": "NSE symbol",
    "bse_code": "BSE code",
}


def get_discovery_service() -> DiscoveryService:
    return get_default_service()


@router.get("/sources", response_model=list[schemas.DiscoverySourceInfo])
def list_sources(service: DiscoveryService = Depends(get_discovery_service)):
    return service.source_statuses()


@router.get("/companies", response_model=schemas.DiscoverySearchResult)
def discover_companies(
    name: Optional[str] = None,
    industry: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    csr_focus: Optional[str] = None,
    page: int = Query(default=0, ge=0),
    page_size: int = Query(default=25, ge=1, le=100),
    service: DiscoveryService = Depends(get_discovery_service),
    db: Session = Depends(get_db),
):
    query = DiscoveryQuery(name=name, industry=industry, city=city, state=state, csr_focus=csr_focus)
    try:
        payload = service.search(query, page=page, page_size=page_size)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    by_name, by_domain = crud.saved_company_lookup(db)
    for result in payload["results"]:
        names = [result["name"], *result.get("aliases", [])]
        saved_id = next((by_name[n] for n in map(normalize_company_name, names) if n in by_name), None)
        if saved_id is None:
            saved_id = by_domain.get(normalize_domain(result.get("website")))
        result["saved_company_id"] = saved_id
    return payload


@router.post("/csr-focus", response_model=schemas.CsrFocusResult)
def check_csr_focus(payload: schemas.CsrFocusRequest):
    """Infer CSR focus areas from the company's own CSR web pages. The
    result is never stored - the UI attaches it to the result row, and it
    is saved (labelled inferred) only if staff then save the company.
    """
    website = payload.website.strip()
    if not website:
        raise HTTPException(status_code=400, detail="A website is needed to check CSR focus.")
    if not is_public_website(website):
        raise HTTPException(status_code=400, detail="That website address can't be checked.")
    return infer_csr_focus(website)


def provenance_note(payload: schemas.DiscoverySaveRequest) -> str:
    """Plain-language record of where each saved value came from."""
    verified, inferred, unavailable = [], [], []
    for field_name in TRACKED_FIELDS:
        label = _FIELD_LABELS[field_name]
        p = payload.provenance.get(field_name)
        has_value = getattr(payload, field_name) not in (None, "")
        if not has_value or p is None or p.status == UNAVAILABLE:
            unavailable.append(label)
        elif p.status == INFERRED:
            inferred.append(f"{label} ({p.source})" if p.source else label)
        elif p.status == VERIFIED:
            verified.append(f"{label} ({p.source})" if p.source else label)
        else:
            unavailable.append(label)

    lines = [f"Saved from company discovery on {date.today().isoformat()}."]
    if payload.sources:
        lines.append(
            "Sources: " + "; ".join(f"{s.name} - {s.url}" if s.url else s.name for s in payload.sources)
        )
    idents = [f"{_IDENTIFIER_LABELS.get(k, k)} {v}" for k, v in payload.identifiers.items()]
    if idents:
        lines.append("Identifiers: " + " · ".join(idents))
    if payload.listed_on:
        lines.append("Listed on: " + ", ".join(payload.listed_on))
    lines.append("")
    if verified:
        lines.append("Verified (stated by a public source): " + "; ".join(verified))
    if inferred:
        lines.append("Inferred by the app - please double-check: " + "; ".join(inferred))
    if unavailable:
        lines.append("Not available from public sources: " + ", ".join(unavailable))
    if payload.details:
        lines.append("")
        lines.append("Other public details: " + " · ".join(f"{k}: {v}" for k, v in payload.details.items()))
    return "\n".join(lines)


def find_saved_lead(db: Session, name: str, website: Optional[str]) -> Optional[models.Company]:
    """The saved lead a discovered company corresponds to, matching on name,
    website, or discovery's normalized name ("Infosys Ltd" == "INFOSYS LIMITED").
    """
    duplicate = crud.find_duplicate_company(db, name, website)
    if duplicate is None:
        by_name, _ = crud.saved_company_lookup(db)
        existing_id = by_name.get(normalize_company_name(name))
        duplicate = crud.get_company(db, existing_id) if existing_id else None
    return duplicate


@router.post("/save", response_model=schemas.CompanyDetail, status_code=201)
def save_as_lead(payload: schemas.DiscoverySaveRequest, force: bool = False, db: Session = Depends(get_db)):
    if not force:
        duplicate = find_saved_lead(db, payload.name, payload.website)
        if duplicate is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "This company is already saved as a lead.",
                    "existing_company_id": duplicate.id,
                    "existing_company_name": duplicate.name,
                },
            )
    return _to_detail(crud.get_company(db, create_lead(db, payload).id))


def create_lead(db: Session, payload: schemas.DiscoverySaveRequest) -> models.Company:
    """Create the Company row for a discovery result, plus its provenance
    note. Shared by "Save as lead" and saving contacts for a company that
    hadn't been saved yet (routers/contact_discovery.py).
    """
    company_fields = schemas.CompanyCreate(
        name=payload.name.strip(),
        industry=payload.industry,
        city=payload.city,
        state=payload.state,
        website=payload.website,
        csr_report_url=payload.csr_report_url,
        csr_focus=payload.csr_focus,
        csr_spending=payload.csr_spending,
        employee_count=payload.employee_count,
    )
    source_names = ", ".join(s.name for s in payload.sources) or "public sources"
    company = crud.create_company(
        db, company_fields, activity_description=f"Company '{company_fields.name}' saved from discovery ({source_names})"
    )
    crud.create_note(db, company.id, schemas.NoteCreate(body=provenance_note(payload)))
    return company
