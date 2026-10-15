"""AI-assisted content: lead-score explanations, email/summary/brief
generation (Phase 3). The lead score itself is computed deterministically
in app/scoring.py and returned inline on every company response
(see routers/companies.py) - the endpoints here are the parts that need
an LLM call, and all report `configured: false` when GEMINI_API_KEY
isn't set rather than erroring.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import ai, crud, schemas
from ..config import settings
from ..database import get_db
from ..scoring import compute_lead_score

router = APIRouter(prefix="/api/companies", tags=["ai"])


def _get_company_or_404(db: Session, company_id: int):
    company = crud.get_company(db, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


@router.post("/{company_id}/score/explain", response_model=schemas.ScoreExplanation)
def explain_score(company_id: int, db: Session = Depends(get_db)):
    company = _get_company_or_404(db, company_id)
    if not ai.is_configured():
        return schemas.ScoreExplanation(configured=False, explanation=None)

    result = compute_lead_score(company)
    explanation = ai.explain_lead_score(company.name, result["factors"], result["score"], result["priority"])
    return schemas.ScoreExplanation(configured=True, explanation=explanation)


@router.post("/{company_id}/generate-email", response_model=schemas.GeneratedEmail)
def generate_email(
    company_id: int, payload: schemas.GenerateEmailRequest, db: Session = Depends(get_db)
):
    company = _get_company_or_404(db, company_id)
    if not ai.is_configured():
        return schemas.GeneratedEmail(configured=False)

    contact = None
    if payload.contact_id is not None:
        contact = crud.get_contact(db, payload.contact_id)
        if contact is None or contact.company_id != company.id:
            raise HTTPException(status_code=404, detail="Contact not found")

    result = ai.generate_email(
        ngo_name=settings.ngo_name,
        ngo_work_area=settings.ngo_work_area,
        company_name=company.name,
        contact_name=contact.name if contact else None,
        contact_designation=contact.designation if contact else None,
        csr_focus=company.csr_focus,
        email_type=payload.email_type.value,
    )
    if result is None:
        return schemas.GeneratedEmail(configured=True)

    crud.log_email_generated(db, company.id, payload.email_type.value.replace("_", " ").title(), contact)
    return schemas.GeneratedEmail(configured=True, subject=result["subject"], body=result["body"])


@router.post("/{company_id}/summary", response_model=schemas.AITextResult)
def company_summary(company_id: int, db: Session = Depends(get_db)):
    company = _get_company_or_404(db, company_id)
    if not ai.is_configured():
        return schemas.AITextResult(configured=False)

    text = ai.generate_company_summary(
        company_name=company.name,
        industry=company.industry,
        city=company.city,
        state=company.state,
        csr_focus=company.csr_focus,
        csr_spending=company.csr_spending,
        ngo_name=settings.ngo_name,
        ngo_work_area=settings.ngo_work_area,
    )
    return schemas.AITextResult(configured=True, text=text)


@router.post("/{company_id}/meeting-brief", response_model=schemas.AITextResult)
def meeting_brief(company_id: int, db: Session = Depends(get_db)):
    company = _get_company_or_404(db, company_id)
    if not ai.is_configured():
        return schemas.AITextResult(configured=False)

    text = ai.generate_meeting_brief(
        company_name=company.name,
        industry=company.industry,
        city=company.city,
        state=company.state,
        csr_focus=company.csr_focus,
        notes=[note.body for note in company.notes],
    )
    return schemas.AITextResult(configured=True, text=text)
