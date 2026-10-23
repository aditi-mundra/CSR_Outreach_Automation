"""Real-company discovery: providers, merging, provenance, and save-as-lead.

No test here touches the network - providers are exercised through their
pure parsing functions and injected fetchers, and the HTTP endpoints run
against a DiscoveryService built from in-memory fake providers.
"""

import pytest

from app.company_discovery import csr_focus, datasets, mca, wikidata
from app.company_discovery.base import (
    INFERRED,
    VERIFIED,
    CompanyDiscoveryProvider,
    DiscoveredCompany,
    DiscoveryQuery,
    ProviderResult,
    SourceRef,
    normalize_company_name,
    smart_title,
)
from app.company_discovery.matching import (
    matches_city,
    matches_csr_focus,
    matches_industry,
    matches_state,
)
from app.company_discovery.service import DiscoveryService, apply_filters, merge_companies
from app.config import settings
from app.main import app
from app.routers.company_discovery import get_discovery_service


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def make_company(name, provider="fake", source="Fake source", **fields):
    status = fields.pop("_status", VERIFIED)
    identifiers = fields.pop("_identifiers", {})
    company = DiscoveredCompany(name=name, provider=provider, identifiers=dict(identifiers))
    for key, value in fields.items():
        company.set(key, value, status, source, f"https://example.org/{provider}")
    company.sources.append(SourceRef(source, f"https://example.org/{provider}"))
    return company


class FakeProvider(CompanyDiscoveryProvider):
    def __init__(self, key, companies=None, notes=None, error=None, configured=True):
        self.key = key
        self.label = key.title()
        self.description = f"{key} test provider"
        self.setup_hint = "none"
        self._companies = companies or []
        self._notes = notes or []
        self._error = error
        self._configured = configured
        self.calls = 0

    def is_configured(self):
        return self._configured

    def search(self, query):
        self.calls += 1
        if self._error:
            raise self._error
        # Fresh objects per call, like real providers (merging mutates them).
        wanted = normalize_company_name(query.name)
        results = []
        for factory in self._companies:
            company = factory()
            if not wanted or wanted in normalize_company_name(company.name):
                results.append(company)
        return ProviderResult(companies=results, notes=list(self._notes))


@pytest.fixture()
def use_service():
    """Install a DiscoveryService of fake providers for the endpoint tests."""

    def install(*providers):
        service = DiscoveryService(list(providers))
        app.dependency_overrides[get_discovery_service] = lambda: service
        return service

    yield install
    app.dependency_overrides.pop(get_discovery_service, None)


def infosys_wikidata():
    c = make_company(
        "Infosys",
        provider="wikidata",
        source="Wikidata",
        industry="IT service management",
        city="Bengaluru",
        website="https://www.infosys.com/",
        employee_count=300000,
        _identifiers={"wikidata": "Q26989", "isin": "INE009A01021"},
    )
    c.set("state", "Karnataka", INFERRED, "Wikidata (from headquarters location)")
    c.listed_on = ["NSE", "BSE"]
    return c


def infosys_mca():
    c = make_company(
        "Infosys Limited",
        provider="mca",
        source="MCA company master data (data.gov.in)",
        industry="Business Services",
        state="Karnataka",
        _identifiers={"cin": "L85110KA1981PLC013115"},
    )
    c.details["Registry status"] = "Active"
    return c


# ----------------------------------------------------------------------------
# Matching / normalization
# ----------------------------------------------------------------------------
def test_normalize_company_name_strips_legal_suffixes():
    assert normalize_company_name("TATA STEEL LIMITED") == "tata steel"
    assert normalize_company_name("Tata Steel Ltd.") == "tata steel"
    assert normalize_company_name("The Tata Power Company Limited") == "tata power"
    assert normalize_company_name("Larsen & Toubro (India) Pvt Ltd") == "larsen and toubro"


def test_smart_title_only_touches_all_caps():
    assert smart_title("INFOSYS LIMITED") == "Infosys Limited"
    assert smart_title("HDFC BANK LIMITED") == "HDFC Bank Limited"
    assert smart_title("HDFC Bank") == "HDFC Bank"


def test_city_and_state_aliases():
    assert matches_city("Bangalore", "Bengaluru")
    assert matches_city("bombay", "Mumbai City district")
    assert not matches_city("Pune", "Mumbai")
    assert matches_state("Delhi", "National Capital Territory of Delhi")
    assert matches_state("orissa", "Odisha")
    assert not matches_state("Gujarat", None)


def test_industry_short_terms_match_whole_words_only():
    assert matches_industry("IT", "information technology consulting")
    assert not matches_industry("it", "capital goods")
    assert matches_industry("pharma", "pharmaceutical industry")
    assert matches_industry("bank", None, "Indian private sector bank")


def test_csr_focus_matches_canonical_areas():
    assert matches_csr_focus("Education", "Education, Healthcare")
    assert matches_csr_focus("schools", "Education")  # keyword -> same Schedule VII area
    assert matches_csr_focus("health", "Health care, Sanitation")
    assert not matches_csr_focus("Education", "Environment")
    assert not matches_csr_focus("Education", None)


# ----------------------------------------------------------------------------
# Merging and filtering
# ----------------------------------------------------------------------------
def test_merge_prefers_verified_values_and_keeps_all_sources():
    merged = merge_companies([infosys_mca(), infosys_wikidata()])
    assert len(merged) == 1
    company = merged[0]
    assert company.name == "Infosys Limited"  # first (higher-priority) source's name
    # MCA's registered state is verified; Wikidata's derived state is inferred.
    assert company.provenance["state"].status == VERIFIED
    assert company.provenance["state"].source.startswith("MCA")
    # Fields only Wikidata has are filled from it.
    assert company.values["website"] == "https://www.infosys.com/"
    assert {s.name for s in company.sources} == {"MCA company master data (data.gov.in)", "Wikidata"}
    assert company.identifiers["cin"] == "L85110KA1981PLC013115"
    assert company.identifiers["wikidata"] == "Q26989"
    assert company.listed_on == ["NSE", "BSE"]


def test_merge_does_not_join_records_with_conflicting_identifiers():
    a = make_company("Acme Limited", _identifiers={"cin": "U1"})
    b = make_company("Acme Limited", _identifiers={"cin": "U2"})
    assert len(merge_companies([a, b])) == 2


def test_merge_by_website_domain():
    a = make_company("Bajaj Auto", website="https://www.bajajauto.com/")
    b = make_company("Bajaj Auto Ltd (two-wheelers)", website="http://bajajauto.com")
    assert len(merge_companies([a, b])) == 1


def test_csr_focus_filter_counts_companies_without_published_focus():
    companies = [
        make_company("A", csr_focus="Education"),
        make_company("B", csr_focus="Environment"),
        make_company("C"),
    ]
    kept, no_focus = apply_filters(companies, DiscoveryQuery(csr_focus="education"))
    assert [c.name for c in kept] == ["A"]
    assert no_focus == 1


def test_city_filter_uses_location_hints():
    company = make_company("Tata Motors", city="Bombay House")
    company.location_hints = ["Bombay House", "Mumbai City district", "Maharashtra"]
    kept, _ = apply_filters([company], DiscoveryQuery(city="Mumbai"))
    assert kept


# ----------------------------------------------------------------------------
# Search endpoint
# ----------------------------------------------------------------------------
def test_search_requires_a_filter(client, use_service):
    use_service(FakeProvider("one"))
    response = client.get("/api/discover/companies")
    assert response.status_code == 400


def test_search_returns_merged_results_with_provenance(client, use_service):
    use_service(FakeProvider("mca", [infosys_mca]), FakeProvider("wikidata", [infosys_wikidata]))
    response = client.get("/api/discover/companies", params={"name": "infosys"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    result = body["results"][0]
    assert result["website"] == "https://www.infosys.com/"
    assert result["provenance"]["state"]["status"] == "verified"
    assert result["provenance"]["csr_focus"] == {"status": "unavailable", "source": None, "source_url": None}
    assert result["provenance"]["csr_spending"]["status"] == "unavailable"
    assert result["saved_company_id"] is None
    assert {s["key"]: s["result_count"] for s in body["sources"]} == {"mca": 1, "wikidata": 1}


def test_search_is_not_limited_to_saved_companies(client, use_service):
    # Nothing saved locally at all - discovery still returns real results.
    assert client.get("/api/companies").json() == []
    use_service(FakeProvider("wikidata", [infosys_wikidata]))
    body = client.get("/api/discover/companies", params={"industry": "IT"}).json()
    assert [r["name"] for r in body["results"]] == ["Infosys"]


def test_failing_provider_is_reported_not_fatal(client, use_service):
    use_service(
        FakeProvider("mca", error=RuntimeError("Rate limit exceeded")),
        FakeProvider("wikidata", [infosys_wikidata]),
    )
    body = client.get("/api/discover/companies", params={"name": "infosys"}).json()
    assert body["total"] == 1
    reports = {s["key"]: s for s in body["sources"]}
    assert "Rate limit exceeded" in reports["mca"]["error"]
    assert reports["mca"]["used"] is False
    assert reports["wikidata"]["used"] is True


def test_unconfigured_provider_is_skipped(client, use_service):
    skipped = FakeProvider("mca", [infosys_mca], configured=False)
    use_service(skipped, FakeProvider("wikidata", [infosys_wikidata]))
    body = client.get("/api/discover/companies", params={"name": "infosys"}).json()
    assert skipped.calls == 0
    assert body["results"][0]["name"] == "Infosys"


def test_pagination_reuses_cached_results(client, use_service):
    factories = [lambda i=i: make_company(f"Company {i:02d}", industry="Steel") for i in range(30)]
    provider = FakeProvider("one", factories)
    use_service(provider)
    first = client.get("/api/discover/companies", params={"industry": "steel", "page_size": 25}).json()
    second = client.get("/api/discover/companies", params={"industry": "steel", "page_size": 25, "page": 1}).json()
    assert first["total"] == second["total"] == 30
    assert len(first["results"]) == 25 and len(second["results"]) == 5
    assert provider.calls == 1


def test_csr_focus_filter_adds_explanatory_note(client, use_service):
    use_service(FakeProvider("one", [lambda: make_company("No Focus Co", industry="Steel")]))
    body = client.get("/api/discover/companies", params={"csr_focus": "Education"}).json()
    assert body["total"] == 0
    assert any("1 company was hidden because no configured source publishes their CSR focus" in note for note in body["notes"])


def test_results_flag_already_saved_companies(client, use_service):
    saved = client.post("/api/companies", json={"name": "Infosys Ltd"}).json()
    other = client.post("/api/companies", json={"name": "Some Other Name", "website": "https://cipla.com"}).json()
    use_service(
        FakeProvider(
            "wikidata",
            [infosys_wikidata, lambda: make_company("Cipla", website="http://www.cipla.com/")],
        )
    )
    infy = client.get("/api/discover/companies", params={"name": "infosys"}).json()["results"][0]
    cipla = client.get("/api/discover/companies", params={"name": "cipla"}).json()["results"][0]
    assert infy["saved_company_id"] == saved["id"]  # normalized-name match
    assert cipla["saved_company_id"] == other["id"]  # website-domain match


def test_sources_endpoint_reports_configuration(client, use_service):
    use_service(FakeProvider("mca", configured=False), FakeProvider("wikidata"))
    sources = {s["key"]: s for s in client.get("/api/discover/sources").json()}
    assert sources["mca"]["configured"] is False
    assert sources["wikidata"]["configured"] is True


# ----------------------------------------------------------------------------
# Save as lead
# ----------------------------------------------------------------------------
def _save_payload(**overrides):
    payload = {
        "name": "Infosys",
        "industry": "IT service management",
        "city": "Bengaluru",
        "state": "Karnataka",
        "website": "https://www.infosys.com/",
        "csr_focus": "Education, Healthcare",
        "employee_count": 300000,
        "provenance": {
            "industry": {"status": "verified", "source": "Wikidata", "source_url": "https://www.wikidata.org/wiki/Q26989"},
            "city": {"status": "verified", "source": "Wikidata"},
            "state": {"status": "inferred", "source": "Wikidata (from headquarters location)"},
            "website": {"status": "verified", "source": "Wikidata"},
            "csr_focus": {"status": "inferred", "source": "Company website"},
            "employee_count": {"status": "verified", "source": "Wikidata"},
            "csr_spending": {"status": "unavailable"},
        },
        "identifiers": {"wikidata": "Q26989", "isin": "INE009A01021"},
        "listed_on": ["NSE", "BSE"],
        "sources": [{"name": "Wikidata", "url": "https://www.wikidata.org/wiki/Q26989"}],
    }
    payload.update(overrides)
    return payload


def test_save_as_lead_creates_company_with_provenance_note(client):
    response = client.post("/api/discover/save", json=_save_payload())
    assert response.status_code == 201
    company = response.json()
    assert company["name"] == "Infosys"
    assert company["status"] == "New"
    # CRM features hang off the saved row: lead score is computed immediately.
    assert company["lead_score"]["score"] >= 0
    assert company["csr_focus"] == "Education, Healthcare"

    note = company["notes"][0]["body"]
    assert "Saved from company discovery" in note
    assert "Wikidata - https://www.wikidata.org/wiki/Q26989" in note
    assert "ISIN INE009A01021" in note
    assert "Inferred by the app - please double-check: state (Wikidata (from headquarters location)); CSR focus" in note
    assert "Not available from public sources: CSR spending, CSR report link" in note

    activity = [a["description"] for a in company["activity_logs"]]
    assert "Company 'Infosys' saved from discovery (Wikidata)" in activity

    # ...and it is now one of the NGO's saved leads.
    listed = client.get("/api/companies").json()
    assert [c["name"] for c in listed] == ["Infosys"]


def test_save_as_lead_detects_duplicates_and_allows_override(client):
    client.post("/api/companies", json={"name": "Infosys Limited"})
    duplicate = client.post("/api/discover/save", json=_save_payload(website=None))
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["existing_company_name"] == "Infosys Limited"

    forced = client.post("/api/discover/save?force=true", json=_save_payload(website=None))
    assert forced.status_code == 201


def test_save_as_lead_validates_payload(client):
    assert client.post("/api/discover/save", json=_save_payload(name="")).status_code == 422
    assert client.post("/api/discover/save", json=_save_payload(csr_spending=-1)).status_code == 422


def test_ai_and_crm_endpoints_require_a_saved_company(client):
    # Discovery results have no id, so company-scoped features can't be
    # reached for them; an unsaved id 404s.
    assert client.post("/api/companies/9999/notes", json={"body": "x"}).status_code == 404
    assert client.post("/api/companies/9999/summary").status_code == 404


# ----------------------------------------------------------------------------
# Wikidata provider
# ----------------------------------------------------------------------------
def _binding(**values):
    return {k: {"type": "literal", "value": v} for k, v in values.items()}


def test_wikidata_parse_detail_and_state_bindings():
    records = wikidata.parse_detail_bindings(
        [
            _binding(
                c="http://www.wikidata.org/entity/Q188514",
                label="Tata Motors Limited",
                desc="Indian automotive manufacturer",
                aliases="Tata Motors|TML",
                industries="automotive industry",
                hqId="http://www.wikidata.org/entity/Q4933964",
                hq="Bombay House",
                website="https://www.tatamotors.com/",
                exchanges="Bombay Stock Exchange|National Stock Exchange of India",
                employees="65000.0",
            ),
            _binding(c="http://www.wikidata.org/entity/Q1"),  # no label -> skipped
        ]
    )
    assert len(records) == 1
    record = records[0]
    assert record["qid"] == "Q188514"
    assert record["aliases"] == ["Tata Motors", "TML"]
    assert record["employees"] == 65000

    states = wikidata.parse_state_bindings(
        [_binding(hq="http://www.wikidata.org/entity/Q4933964", state="Maharashtra",
                  places="Mumbai City district|Konkan division|Maharashtra|India")]
    )
    assert states["Q4933964"] == {"state": "Maharashtra", "places": ["Mumbai City district", "Konkan division", "Maharashtra"]}

    record.update(state="Maharashtra", hq_places=states["Q4933964"]["places"])
    company = wikidata.record_to_company(record)
    # HQ is a building, so the city is derived from the admin hierarchy.
    assert company.values["city"] == "Mumbai"
    assert company.provenance["city"].status == INFERRED
    assert company.details["headquarters"] == "Bombay House"
    assert company.provenance["state"].status == INFERRED
    assert company.provenance["industry"].status == VERIFIED
    assert company.listed_on == ["BSE", "NSE"]
    assert company.sources[0].url == "https://www.wikidata.org/wiki/Q188514"


def _index_record(qid, name, **extra):
    record = {"qid": qid, "name": name, "aliases": [], "description": None, "industries": [], "hq": None,
              "hq_qid": None, "hq_places": [], "state": None, "website": None, "exchanges": [], "isin": None,
              "employees": None}
    record.update(extra)
    return record


def test_wikidata_index_search_matches_aliases(tmp_path):
    index = wikidata.WikidataIndex(tmp_path / "idx.json", 168, builder=lambda: [])
    index.set_records([
        _index_record("Q1", "Tata Consultancy Services", aliases=["TCS"], industries=["IT service management"]),
        _index_record("Q2", "Cipla", industries=["pharmaceutical industry"]),
    ])
    provider = wikidata.WikidataProvider(index=index, live_search=lambda q: pytest.fail("should use index"))
    assert [c.name for c in provider.search(DiscoveryQuery(name="TCS")).companies] == ["Tata Consultancy Services"]
    # Filter-only searches get the whole index; the service filters it.
    assert len(provider.search(DiscoveryQuery(industry="pharma")).companies) == 2


def test_wikidata_falls_back_to_live_search_while_index_builds(tmp_path):
    index = wikidata.WikidataIndex(tmp_path / "idx.json", 168, builder=lambda: [])
    live_calls = []

    def live(query):
        live_calls.append(query.name)
        return [_index_record("Q3", "Wipro")]

    provider = wikidata.WikidataProvider(index=index, live_search=live)
    result = provider.search(DiscoveryQuery(name="wipro"))
    assert [c.name for c in result.companies] == ["Wipro"]
    assert live_calls == ["wipro"]
    assert result.notes  # explains results are partial


def test_wikidata_index_persists_to_disk(tmp_path):
    path = tmp_path / "idx.json"
    built = wikidata.WikidataIndex(path, 168, builder=lambda: [_index_record("Q5", "Bajaj Auto")])
    built.ensure_fresh(background=False)
    assert path.exists()
    reloaded = wikidata.WikidataIndex(path, 168, builder=lambda: pytest.fail("should load from disk"))
    assert reloaded.is_ready() and not reloaded.is_stale()
    assert reloaded.records[0]["name"] == "Bajaj Auto"


def test_wikidata_failed_build_keeps_serving_and_records_error(tmp_path):
    def boom():
        raise RuntimeError("429 Too Many Requests")

    index = wikidata.WikidataIndex(tmp_path / "idx.json", 168, builder=boom)
    index.ensure_fresh(background=False)
    assert not index.is_ready()
    assert "429" in index.last_error
    assert not index.is_building()


# ----------------------------------------------------------------------------
# MCA (data.gov.in) provider
# ----------------------------------------------------------------------------
MCA_METADATA = {
    "field": [{"id": name.lower(), "name": name, "type": "keyword"} for name in mca.COLUMNS],
    "records": [],
}


def _mca_record(name, state="Karnataka", status="Active", **extra):
    record = {
        "corporate_identification_number": extra.pop("cin", "L85110KA1981PLC013115"),
        "company_name": name,
        "company_status": status,
        "company_class": "Public",
        "registered_state": state,
        "principal_business_activity": "Business Services",
        "registered_office_address": "Electronics City, Hosur Road Bangalore Karnataka 560100",
        "paidup_capital": "20750000000",
        "date_of_registration": "02-07-1981",
    }
    record.update(extra)
    return record


def test_mca_field_ids_and_record_parsing():
    ids = mca.field_ids_from_metadata({"field": [{"id": "CompanyName", "name": "COMPANY_NAME"}]})
    assert ids["COMPANY_NAME"] == "CompanyName"
    assert ids["REGISTERED_STATE"] == "registered_state"  # default when not in metadata

    company = mca.record_to_company(_mca_record("INFOSYS LIMITED"), mca.field_ids_from_metadata(MCA_METADATA), "u")
    assert company.name == "Infosys Limited"
    assert company.provenance["state"].status == VERIFIED
    assert company.provenance["industry"].status == VERIFIED
    assert company.values["city"] == "Bengaluru"  # from address: inferred
    assert company.provenance["city"].status == INFERRED
    assert company.identifiers["cin"] == "L85110KA1981PLC013115"
    assert company.details["Paid-up capital"] == "₹2,075.00 crore"


def test_mca_name_variants():
    assert mca.name_variants("Infosys") == ["INFOSYS", "INFOSYS LIMITED", "INFOSYS PRIVATE LIMITED"]
    assert mca.name_variants("tata steel ltd")[1] == "TATA STEEL LIMITED"


def test_mca_search_by_name_uses_exact_filters(monkeypatch):
    monkeypatch.setattr(settings, "data_gov_in_api_key", "test-key")
    calls = []

    def fetch(params):
        calls.append(params)
        if params.get("filters[company_name]") == "INFOSYS LIMITED":
            return {"records": [_mca_record("INFOSYS LIMITED")]}
        return MCA_METADATA if "filters[company_name]" not in params else {"records": []}

    provider = mca.McaProvider(fetch=fetch)
    assert provider.is_configured()
    result = provider.search(DiscoveryQuery(name="Infosys"))
    assert [c.name for c in result.companies] == ["Infosys Limited"]
    assert {c.get("filters[company_name]") for c in calls[1:]} == set(mca.name_variants("Infosys"))


def test_mca_state_browse_drops_inactive_companies(monkeypatch):
    monkeypatch.setattr(settings, "data_gov_in_api_key", "test-key")

    def fetch(params):
        if "filters[registered_state]" in params:
            assert params["filters[registered_state]"] == "Maharashtra"
            return {"records": [
                _mca_record("ALPHA LIMITED", state="Maharashtra", cin="A1"),
                _mca_record("BETA LIMITED", state="Maharashtra", status="Strike Off", cin="B1"),
            ]}
        return MCA_METADATA

    result = mca.McaProvider(fetch=fetch).search(DiscoveryQuery(state="maharashtra"))
    assert [c.name for c in result.companies] == ["Alpha Limited"]
    assert result.notes


def test_mca_needs_name_or_state(monkeypatch):
    monkeypatch.setattr(settings, "data_gov_in_api_key", "test-key")
    result = mca.McaProvider(fetch=lambda p: pytest.fail("no API call expected")).search(DiscoveryQuery(industry="steel"))
    assert result.companies == [] and result.notes


def test_mca_api_error_is_raised_for_the_service_to_report(monkeypatch):
    monkeypatch.setattr(settings, "data_gov_in_api_key", "test-key")
    provider = mca.McaProvider(fetch=lambda p: {"error": "Rate limit exceeded"})
    with pytest.raises(mca.OGDError):
        provider.search(DiscoveryQuery(name="infosys"))


def test_mca_not_configured_without_key(monkeypatch):
    monkeypatch.setattr(settings, "data_gov_in_api_key", "")
    assert not mca.McaProvider().is_configured()


# ----------------------------------------------------------------------------
# Local datasets provider
# ----------------------------------------------------------------------------
def test_dataset_nse_equity_list(tmp_path):
    (tmp_path / "EQUITY_L.csv").write_text(
        "SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE\n"
        "INFY,Infosys Limited,EQ,08-FEB-1995,5,1,INE009A01021,5\n"
        "TCS,Tata Consultancy Services Limited,EQ,25-AUG-2004,1,1,INE467B01029,1\n",
        encoding="utf-8",
    )
    provider = datasets.DatasetProvider(directory=tmp_path)
    assert provider.is_configured()
    result = provider.search(DiscoveryQuery(name="infosys"))
    assert len(result.companies) == 1
    company = result.companies[0]
    assert company.listed_on == ["NSE"]
    assert company.identifiers == {"isin": "INE009A01021", "nse_symbol": "INFY"}
    # It merges with Wikidata's record via the shared ISIN.
    assert len(merge_companies([company, infosys_wikidata()])) == 1


def test_dataset_csr_portal_export_aggregates_sectors_and_latest_year(tmp_path):
    (tmp_path / "csr_portal.csv").write_text(
        "Company Name,CIN,State,Financial Year,Development Sector,Amount Spent (INR Cr.)\n"
        "ACME LIMITED,L1,Maharashtra,2021-22,Education,1.5\n"
        "ACME LIMITED,L1,Maharashtra,2022-23,Education,2\n"
        "ACME LIMITED,L1,Maharashtra,2022-23,Health Care,0.5\n"
        "OTHER LIMITED,L2,Gujarat,2022-23,Environment,1\n",
        encoding="utf-8",
    )
    provider = datasets.DatasetProvider(directory=tmp_path)
    companies = provider.search(DiscoveryQuery(csr_focus="education")).companies
    assert [c.name for c in companies] == ["Acme Limited"]
    acme = companies[0]
    assert acme.values["csr_focus"] == "Education, Health Care"
    assert acme.values["csr_spending"] == 25_000_000  # (2 + 0.5) crore, latest year only
    assert acme.provenance["csr_spending"].status == VERIFIED
    assert acme.provenance["csr_spending"].source == "Dataset: csr_portal.csv"
    assert acme.details["CSR spend year"] == "2022-23"


def test_dataset_without_name_column_is_ignored(tmp_path):
    (tmp_path / "junk.csv").write_text("foo,bar\n1,2\n", encoding="utf-8")
    assert datasets.DatasetProvider(directory=tmp_path).search(DiscoveryQuery(name="x")).companies == []


def test_dataset_missing_directory_is_unconfigured(tmp_path):
    assert not datasets.DatasetProvider(directory=tmp_path / "nope").is_configured()


# ----------------------------------------------------------------------------
# CSR focus inference
# ----------------------------------------------------------------------------
def test_infer_csr_focus_from_company_csr_page():
    pages = {
        "https://acme.example/": (
            '<html><a href="/our-impact/csr-initiatives">Our CSR</a>'
            '<a href="/files/acme-brsr-2024.pdf">Business Responsibility Report</a>'
            "<p>We are next to a school.</p></html>"
        ),
        "https://acme.example/our-impact/csr-initiatives": (
            "<h1>Corporate Social Responsibility</h1><script>var health = 1;</script>"
            "<p>Our education programme funds scholarships and school libraries. "
            "We also run rural health camps and a mobile hospital.</p>"
        ),
    }
    result = csr_focus.infer_csr_focus("https://acme.example", fetch=pages.get)
    assert result["csr_focus"] == "Education, Healthcare"
    assert result["areas"][0] == {"area": "Education", "mentions": 3}
    assert result["source_urls"] == ["https://acme.example/our-impact/csr-initiatives"]
    assert result["csr_report_url"] == "https://acme.example/files/acme-brsr-2024.pdf"
    # The home page mentions "school" but isn't a CSR page, so it isn't counted.
    assert "https://acme.example/" not in result["source_urls"]


def test_infer_csr_focus_unavailable_when_nothing_found():
    result = csr_focus.infer_csr_focus("https://quiet.example", fetch=lambda url: None)
    assert result["csr_focus"] is None
    assert result["areas"] == []
    assert len(result["pages_checked"]) <= csr_focus.MAX_PAGES


def test_csr_focus_endpoint_validates_website(client):
    assert client.post("/api/discover/csr-focus", json={"website": "  "}).status_code == 400


def test_city_inference_prefers_last_city_in_address():
    from app.company_discovery.matching import MAJOR_INDIAN_CITIES, first_known_city, is_known_city

    assert first_known_city("Plot 4, Mumbai-Pune Highway, Pune Maharashtra 411001", MAJOR_INDIAN_CITIES) == "Pune"
    assert is_known_city("Bangalore", MAJOR_INDIAN_CITIES)
    assert not is_known_city("Bombay House", MAJOR_INDIAN_CITIES)


def test_wikidata_company_type_filter():
    # Kept: businesses, banks, PSUs, records with no type data.
    assert wikidata.looks_like_company(["multinational corporation", "public company", "business"])
    assert wikidata.looks_like_company(["bank", "financial institution"])
    assert wikidata.looks_like_company(["state-owned enterprise", "public sector undertaking"])
    assert wikidata.looks_like_company(["human resources consulting company"])
    assert wikidata.looks_like_company(["online shopping website", "business"])
    assert wikidata.looks_like_company(None)
    # Dropped: NGOs (even when also typed "business"), universities, people.
    assert not wikidata.looks_like_company(["nonprofit organization", "business"])
    assert not wikidata.looks_like_company(["research institute", "higher education institution"])
    assert not wikidata.looks_like_company(["human"])
    assert not wikidata.looks_like_company(["railway line"])
    # Real cases from sampling the live index:
    # media businesses typed only by what they run - kept
    assert wikidata.looks_like_company(["television station", "news broadcasting", "television channel"])
    assert wikidata.looks_like_company(["record label", "website", "film distributor"])
    assert wikidata.looks_like_company(["shipyard"])
    # hospital chain / coaching company with an explicit legal form - kept
    assert wikidata.looks_like_company(["hospital network", "public company"])
    assert wikidata.looks_like_company(["privately held company", "educational institution"])
    assert not wikidata.looks_like_company(["research institute", "university of technology", "business"])
    # mistyped on Wikidata, but the registered name says it's a company - kept
    assert wikidata.looks_like_company(["university"], name="Indian Immunologicals Limited")
    # ...unless it's a hard exclusion (Section 8 non-profits are "Limited" too)
    assert not wikidata.looks_like_company(["nonprofit organization"], name="Some Foundation Limited")
    # vaguely typed regional rural bank - kept via its industry
    assert wikidata.looks_like_company(["organization"], industries=["bank"])
    assert not wikidata.looks_like_company(["organization"], industries=["music industry"])
    # associations, clubs, religious bodies, the exchange itself - dropped
    assert not wikidata.looks_like_company(["nonprofit organization", "trade association"])
    assert not wikidata.looks_like_company(["sports club"])
    assert not wikidata.looks_like_company(["religious organization"])
    assert not wikidata.looks_like_company(["stock exchange", "futures exchange"])


def test_wikidata_district_hq_maps_to_city():
    record = _index_record("Q9", "ICICI Bank", hq="Mumbai City district", hq_places=["Konkan division", "Maharashtra"])
    company = wikidata.record_to_company(record)
    assert company.values["city"] == "Mumbai"
    assert company.provenance["city"].status == INFERRED


def test_old_format_index_is_served_but_marked_stale(tmp_path):
    import json

    path = tmp_path / "idx.json"
    path.write_text(json.dumps({"version": 1, "built_at": 9e12, "records": [_index_record("Q5", "Bajaj Auto")]}))
    index = wikidata.WikidataIndex(path, 168, builder=lambda: [])
    assert index.is_ready()
    assert index.is_stale()


def test_ranking_puts_listed_companies_first():
    from app.company_discovery.service import _rank_key

    startup = make_company("Aardvark AI", industry="software")
    listed = make_company("Zeta Infotech", industry="software")
    listed.listed_on = ["NSE"]
    ranked = sorted([startup, listed], key=lambda c: _rank_key(c, DiscoveryQuery(industry="software")))
    assert [c.name for c in ranked] == ["Zeta Infotech", "Aardvark AI"]


def test_infer_csr_focus_explains_javascript_only_sites():
    shell = "<html><body><div id='root'></div><script src='/app.js'></script></body></html>"
    result = csr_focus.infer_csr_focus("https://spa.example", fetch=lambda url: shell)
    assert result["csr_focus"] is None
    assert "JavaScript" in result["message"]


def test_infer_csr_focus_explains_missing_csr_page():
    page = "<html><p>" + "We make excellent widgets for industrial customers. " * 10 + "</p></html>"
    pages = {"https://plain.example/": page}  # every CSR path 404s
    result = csr_focus.infer_csr_focus("https://plain.example", fetch=pages.get)
    assert result["message"] == "No CSR page was found on the company's website."


def test_name_matching_is_at_word_starts():
    from app.company_discovery.base import name_contains

    assert name_contains("tata steel", "tata")
    assert name_contains("the tata power", "tata power")
    assert not name_contains("vitatalk", "tata")
    record = _index_record("Q7", "Vitatalk Networks")
    assert not wikidata.record_matches_name(record, "tata")


def test_failed_index_build_is_not_retried_immediately(tmp_path):
    attempts = []

    def failing_builder():
        attempts.append(1)
        raise RuntimeError("network down")

    index = wikidata.WikidataIndex(tmp_path / "idx.json", 168, builder=failing_builder)
    index.ensure_fresh(background=False)
    index.ensure_fresh(background=False)  # e.g. the next search
    assert len(attempts) == 1


def test_slow_provider_times_out_without_blocking_search(client, use_service, monkeypatch):
    import threading

    from app.company_discovery import service as service_module

    monkeypatch.setattr(service_module, "PROVIDER_TIMEOUT_SECONDS", 0.2)
    release = threading.Event()

    class SlowProvider(FakeProvider):
        def search(self, query):
            release.wait(5)
            return ProviderResult()

    use_service(SlowProvider("slow"), FakeProvider("wikidata", [infosys_wikidata]))
    try:
        body = client.get("/api/discover/companies", params={"name": "infosys"}).json()
    finally:
        release.set()
    reports = {s["key"]: s for s in body["sources"]}
    assert "timed out" in reports["slow"]["error"]
    assert body["total"] == 1


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:8000", "http://localhost/admin", "http://169.254.169.254/latest/meta-data",
     "http://10.0.0.5", "file:///etc/passwd", "ftp://example.com"],
)
def test_csr_focus_endpoint_refuses_non_public_addresses(client, url):
    response = client.post("/api/discover/csr-focus", json={"website": url})
    assert response.status_code == 400


def test_state_power_company_mistyped_as_regulator_is_kept():
    assert wikidata.looks_like_company(
        ["holding company", "regulatory agency"], name="Gujarat Urja Vikas Nigam Limited"
    )
    assert not wikidata.looks_like_company(["regulatory agency"], name="Securities and Exchange Board of India")


def test_get_json_waits_out_rate_limits_when_patient(monkeypatch):
    from app.company_discovery import http

    class FakeResponse:
        def __init__(self, status, payload=None, headers=None):
            self.status_code, self._payload, self.headers = status, payload, headers or {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise http.requests.HTTPError(f"{self.status_code} Client Error")

        def json(self):
            return self._payload

    responses = [FakeResponse(429, headers={"Retry-After": "1"}), FakeResponse(200, {"ok": True})]
    sleeps = []
    monkeypatch.setattr(http.requests, "get", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr(http.time, "sleep", sleeps.append)
    assert http.get_json("https://example.org", {}, retries=3) == {"ok": True}
    assert sleeps == [1.0]

    # Interactive callers (retries=0) fail fast instead of making the user wait.
    responses[:] = [FakeResponse(429)]
    with pytest.raises(http.requests.HTTPError):
        http.get_json("https://example.org", {})


def test_status_reports_failed_refresh_while_serving_old_index(tmp_path):
    def boom():
        raise RuntimeError("429 Too Many Requests")

    index = wikidata.WikidataIndex(tmp_path / "idx.json", 168, builder=boom)
    index.set_records([_index_record("Q5", "Bajaj Auto")], built_at=1.0)  # stale
    index.ensure_fresh(background=False)
    provider = wikidata.WikidataProvider(index=index, live_search=lambda q: [])
    assert "last refresh failed" in provider.status()
    assert [c.name for c in provider.search(DiscoveryQuery(name="bajaj")).companies] == ["Bajaj Auto"]
