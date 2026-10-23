"""Contact search, profile, notes, and update/delete (addressed by their own id)."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..database import get_db

router = APIRouter(prefix="/api/contacts", tags=["contacts"])


@router.get("", response_model=list[schemas.ContactListItem])
def search_contacts(
    company: Optional[str] = None,
    name: Optional[str] = None,
    designation: Optional[str] = None,
    industry: Optional[str] = None,
    state: Optional[str] = None,
    city: Optional[str] = None,
    priority: Optional[int] = Query(default=None, ge=1, le=3),
    company_id: Optional[int] = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    rows = crud.search_contacts(
        db,
        company=company,
        name=name,
        designation=designation,
        industry=industry,
        state=state,
        city=city,
        priority=priority,
        company_id=company_id,
        skip=skip,
        limit=limit,
    )
    return [
        schemas.ContactListItem(
            **schemas.ContactOut.model_validate(contact).model_dump(),
            company_name=company_row.name,
            company_industry=company_row.industry,
            company_city=company_row.city,
            company_state=company_row.state,
        )
        for contact, company_row in rows
    ]


@router.get("/{contact_id}", response_model=schemas.ContactProfile)
def get_contact_profile(contact_id: int, db: Session = Depends(get_db)):
    contact = crud.get_contact_profile(db, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact


@router.post("/{contact_id}/notes", response_model=schemas.NoteOut, status_code=201)
def add_contact_note(contact_id: int, payload: schemas.NoteCreate, db: Session = Depends(get_db)):
    contact = crud.get_contact(db, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    return crud.create_note(db, contact.company_id, payload, contact=contact)


@router.patch("/{contact_id}", response_model=schemas.ContactOut)
def update_contact(contact_id: int, payload: schemas.ContactUpdate, db: Session = Depends(get_db)):
    contact = crud.get_contact(db, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    return crud.update_contact(db, contact, payload)


@router.delete("/{contact_id}", status_code=204)
def delete_contact(contact_id: int, db: Session = Depends(get_db)):
    contact = crud.get_contact(db, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    crud.delete_contact(db, contact)
