"""Phase 6: a small, realistic-looking demo dataset for showing the app to
NGO staff or running the UAT_CHECKLIST.md sessions against - not a
performance test (see load_test.py for that).

Connects to whatever DATABASE_URL is configured (backend/.env), so it can
be pointed at a local Postgres or the deployed one. Safe to re-run: company
creation goes through the same duplicate-detection path the API uses, so
re-running this just skips companies that already exist rather than
duplicating them.

These are fictional companies with *.example.com websites - demo data only.
Real companies come from the Companies page's "Discover companies" tab
(app/company_discovery/). To clear the demo companies out of a database
you're now using for real outreach, run with --remove: it deletes only
rows matching both a demo name and its demo website, never anything else.

Usage:
    cd backend && python scripts/seed_demo_data.py            # add demo data
    cd backend && python scripts/seed_demo_data.py --remove   # remove it again
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import crud, models, schemas  # noqa: F401 - models registers tables on Base.metadata
from app.database import Base, SessionLocal, engine

COMPANIES = [
    dict(
        name="Sahyadri Steel Works",
        industry="Manufacturing",
        city="Pune",
        state="Maharashtra",
        website="https://sahyadristeel.example.com",
        csr_focus="Education",
        csr_spending=8_500_000,
        revenue=1_200_000_000,
        employee_count=2400,
    ),
    dict(
        name="Konkan Coastal Foods",
        industry="Food Processing",
        city="Mumbai",
        state="Maharashtra",
        website="https://konkancoastal.example.com",
        csr_focus="Rural Development",
        csr_spending=3_200_000,
        revenue=450_000_000,
        employee_count=900,
    ),
    dict(
        name="Deccan Software Solutions",
        industry="Technology",
        city="Pune",
        state="Maharashtra",
        website="https://deccansoft.example.com",
        csr_focus="Education",
        csr_spending=12_000_000,
        revenue=2_800_000_000,
        employee_count=5200,
    ),
    dict(
        name="Bharat Textiles Ltd",
        industry="Textiles",
        city="Ahmedabad",
        state="Gujarat",
        website="https://bharattextiles.example.com",
        csr_focus="Women Empowerment",
        csr_spending=5_600_000,
        revenue=680_000_000,
        employee_count=3100,
    ),
    dict(
        name="Nilgiri Healthcare Devices",
        industry="Healthcare",
        city="Chennai",
        state="Tamil Nadu",
        website="https://nilgirihealthcare.example.com",
        csr_focus="Healthcare",
        csr_spending=9_800_000,
        revenue=1_500_000_000,
        employee_count=1800,
    ),
    dict(
        name="Aravalli Cement Corp",
        industry="Construction Materials",
        city="Jaipur",
        state="Rajasthan",
        website="https://aravallicement.example.com",
        csr_focus="Environment",
        csr_spending=4_100_000,
        revenue=920_000_000,
        employee_count=2000,
    ),
    dict(
        name="Ganga Power Utilities",
        industry="Energy",
        city="Lucknow",
        state="Uttar Pradesh",
        website="https://gangapower.example.com",
        csr_focus="Rural Development",
        csr_spending=15_000_000,
        revenue=3_400_000_000,
        employee_count=6100,
    ),
    dict(
        name="Malabar Spices Exports",
        industry="Agriculture",
        city="Kochi",
        state="Kerala",
        website="https://malabarspices.example.com",
        csr_focus="Education",
        csr_spending=2_400_000,
        revenue=310_000_000,
        employee_count=650,
    ),
    dict(
        name="Vindhya Auto Components",
        industry="Automotive",
        city="Indore",
        state="Madhya Pradesh",
        website="https://vindhyaauto.example.com",
        csr_focus="Healthcare",
        csr_spending=6_700_000,
        revenue=1_050_000_000,
        employee_count=2700,
    ),
    dict(
        name="Yamuna Digital Payments",
        industry="Fintech",
        city="Delhi",
        state="Delhi",
        website="https://yamunapay.example.com",
        csr_focus="Education",
        csr_spending=11_200_000,
        revenue=1_900_000_000,
        employee_count=1400,
    ),
]

CONTACTS_BY_COMPANY = {
    "Sahyadri Steel Works": ("Anjali Deshpande", "Head of CSR"),
    "Deccan Software Solutions": ("Rohit Kulkarni", "Sustainability Lead"),
    "Nilgiri Healthcare Devices": ("Priya Menon", "Foundation Director"),
}

TAGS_BY_COMPANY = {
    "Sahyadri Steel Works": ["High Priority", "Pune"],
    "Deccan Software Solutions": ["High Priority", "Pune", "Education"],
    "Ganga Power Utilities": ["Follow-up Q1"],
}


def remove_demo_companies() -> None:
    db = SessionLocal()
    removed = 0
    try:
        for data in COMPANIES:
            company = (
                db.query(models.Company)
                .filter(models.Company.name == data["name"], models.Company.website == data["website"])
                .first()
            )
            if company is None:
                continue
            crud.delete_company(db, company)  # cascades to its contacts/notes/tags links
            removed += 1
            print(f"removed: {data['name']}")
        print(f"\nDone: {removed} demo compan{'y' if removed == 1 else 'ies'} removed.")
    finally:
        db.close()


def main():
    # The app normally creates tables on startup (see app/main.py's lifespan).
    # This script talks to the DB directly, so on a database the app has never
    # booted against - a freshly provisioned Neon/Postgres instance, which is
    # exactly when you want demo data - seeding would otherwise die with
    # "no such table: companies".
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    created = 0
    skipped = 0
    try:
        for data in COMPANIES:
            payload = schemas.CompanyCreate(**data)
            if crud.find_duplicate_company(db, payload.name, payload.website):
                print(f"skip (already exists): {payload.name}")
                skipped += 1
                continue

            company = crud.create_company(db, payload)
            created += 1
            print(f"created: {company.name}")

            if company.name in CONTACTS_BY_COMPANY:
                name, designation = CONTACTS_BY_COMPANY[company.name]
                crud.create_contact(
                    db,
                    company.id,
                    schemas.ContactCreate(name=name, designation=designation),
                )

            for tag_name in TAGS_BY_COMPANY.get(company.name, []):
                tag = crud.get_or_create_tag(db, tag_name)
                crud.add_tag_to_company(db, company, tag)

        print(f"\nDone: {created} created, {skipped} skipped (already existed).")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--remove", action="store_true", help="delete the demo companies instead of adding them")
    if parser.parse_args().remove:
        Base.metadata.create_all(bind=engine)
        remove_demo_companies()
    else:
        main()
