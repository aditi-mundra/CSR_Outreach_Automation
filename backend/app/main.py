"""FastAPI entrypoint for the CSR Outreach backend."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import crud, models  # noqa: F401 - models import registers tables on Base.metadata
from .config import settings
from .database import Base, SessionLocal, engine
from .schema_upgrade import add_missing_columns
from .routers import (
    ai,
    companies,
    company_discovery,
    contact_discovery,
    contacts,
    dashboard,
    discovery,
    documents,
    ngo_profile,
    notes,
    proposals,
    tags,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Deferred to app startup (not import time) so importing this module
    # for testing doesn't require a live database connection - tests
    # supply their own engine via dependency override (see tests/conftest.py).
    Base.metadata.create_all(bind=engine)
    # Existing databases: add columns introduced since they were created
    # (create_all only creates missing tables) - see schema_upgrade.py.
    add_missing_columns(engine)

    # Load the persisted NGO profile (seeding it from env defaults on first
    # run) and mirror it onto `settings` - see crud.get_ngo_profile - so
    # scoring.py/ai.py reflect any profile edits made in a previous run.
    db = SessionLocal()
    try:
        crud.get_ngo_profile(db)
    finally:
        db.close()

    # Start preparing (or refreshing) the Wikidata company index in the
    # background so the first company search doesn't wait for it - see
    # company_discovery/wikidata.py. Never blocks startup.
    if settings.wikidata_enabled:
        from .company_discovery.service import get_default_service

        for provider in get_default_service().providers:
            if provider.key == "wikidata":
                provider.index.ensure_fresh(background=True)

    yield


app = FastAPI(title="CSR Outreach Portal API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(companies.router)
app.include_router(company_discovery.router)
app.include_router(contact_discovery.router)
app.include_router(contacts.router)
app.include_router(notes.router)
app.include_router(discovery.router)
app.include_router(ai.router)
app.include_router(dashboard.router)
app.include_router(tags.router)
app.include_router(documents.router)
app.include_router(proposals.router)
app.include_router(ngo_profile.router)


@app.get("/api/health")
def health_check():
    return {"status": "ok"}
