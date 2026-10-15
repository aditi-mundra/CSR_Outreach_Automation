"""CSR contact discovery: role taxonomy, work-info-only rules, extraction,
report parsing, the service (crawl/merge/score), endpoints, contact
search/profile/notes, and the startup column upgrade.

No test touches the network: the service is built with injected fetch /
robots / report / third-party functions, and endpoints run against it via
a dependency override.
"""

import pytest
from sqlalchemy import create_engine, inspect, text

from app import enrichment
from app.contact_discovery import extract, policy, reports, roles
from app.contact_discovery.service import CompanyContext, ContactDiscoveryService, infer_email_pattern
from app.main import app
from app.routers.contact_discovery import get_contact_discovery_service
from app.schema_upgrade import add_missing_columns


# ----------------------------------------------------------------------------
# Fixtures / fakes
# ----------------------------------------------------------------------------
class AllowAll:
    def can_fetch(self, agent, url):
        return True


class Disallow:
    def __init__(self, *blocked):
        self.blocked = blocked

    def can_fetch(self, agent, url):
        return not any(url.endswith(path) for path in self.blocked)


HOME = """<html><body>
<nav><a href="/csr">CSR</a> <a href="/about-us/leadership">Leadership</a> <a href="/contact-us">Contact us</a>
<a href="/careers">Careers</a> <a href="https://othersite.com/csr">Partner CSR</a>
<a href="/files/csr-report-2024.pdf">CSR Report 2024</a></nav>
<p>Welcome to Acme Industries Limited.</p></body></html>"""

LEADERSHIP = """<html><body><h1>Leadership</h1>
<div class="card"><h4>Priya Sharma</h4><p>Head - CSR</p>
  <a href="mailto:priya.sharma@acme.example.com">Email</a>
  <a href="https://www.linkedin.com/in/priya-sharma-csr/"><i class="icon"></i></a></div>
<div class="card"><h4>Rahul Verma</h4><p>Chief Human Resources Officer</p>
  <a href="mailto:rahul.verma@gmail.com">Email</a></div>
<div class="card"><h4>Arjun Nair</h4><p>Managing Director</p></div>
<div class="card"><h4>Meena Iyer</h4><p>Regional Manager - West, Pune</p></div>
</body></html>"""

CSR_PAGE = """<html><body><h1>Corporate Social Responsibility</h1>
<p>Our programmes reach 200 schools.</p>
<h3>CSR Committee</h3>
<table><tr><th>Name</th><th>Position</th></tr>
<tr><td>Mr. N. Chandrasekaran</td><td>Chairman</td></tr>
<tr><td>Ms. Priya Sharma</td><td>Member</td></tr></table>
<h3>Audit Committee</h3>
<table><tr><td>Mr. Vikram Yadav</td><td>Chairman</td></tr></table>
<p>Write to csr@acme.example.com for partnerships.</p>
</body></html>"""

CONTACT_PAGE = """<html><body><h1>Contact us</h1>
<address>Registered Office: Acme House, Senapati Bapat Road, Pune 411016</address>
<p>Tel: +91 20 6645 1000 | Mobile: +91 98765 43210</p>
<p>General enquiries: info@acme.example.com</p>
<p>Media: corpcomm@acme.example.com</p>
</body></html>"""

SITE = {
    "https://acme.example.com/": HOME,
    "https://acme.example.com/about-us/leadership": LEADERSHIP,
    "https://acme.example.com/csr": CSR_PAGE,
    "https://acme.example.com/contact-us": CONTACT_PAGE,
}


def make_service(site=None, robots=None, report_scanner=None, third_party=None, configured=False, fetched=None):
    site = SITE if site is None else site

    def fetch(url):
        if fetched is not None:
            fetched.append(url)
        return site.get(url)

    return ContactDiscoveryService(
        fetch=fetch,
        robots_for=lambda base: robots or AllowAll(),
        url_guard=lambda url: True,
        report_scanner=report_scanner or (lambda url: {"people": [], "pages_read": 0, "relevant_pages": [], "message": None}),
        third_party=third_party or (lambda domain: []),
        third_party_configured=lambda: configured,
        delay_seconds=0,
    )


ACME = CompanyContext(name="Acme Industries Ltd", website="https://acme.example.com", city="Mumbai", state="Maharashtra")


def by_name(result, name):
    return next(c for c in result["contacts"] if c["name"] == name)


@pytest.fixture()
def fake_service():
    service = make_service()
    app.dependency_overrides[get_contact_discovery_service] = lambda: service
    yield service
    app.dependency_overrides.pop(get_contact_discovery_service, None)


def _create_company(client, **overrides):
    payload = {"name": "Acme Industries Ltd", "website": "https://acme.example.com", "city": "Mumbai",
               "state": "Maharashtra", "industry": "Manufacturing"}
    payload.update(overrides)
    response = client.post("/api/companies", json=payload)
    assert response.status_code == 201
    return response.json()


# ----------------------------------------------------------------------------
# Roles
# ----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "title, category, priority",
    [
        ("Head - CSR", "CSR Head", 1),
        ("CSR Manager", "CSR Manager", 1),
        ("Vice President, Corporate Social Responsibility", "CSR Head", 1),
        ("Chief Sustainability Officer", "Sustainability Head", 1),
        ("Head ESG", "ESG Head", 1),
        ("Director, Acme Foundation", "Foundation Director", 1),
        ("Chairman, CSR Committee", "CSR Committee", 1),
        ("GM - CSR", "CSR Head", 1),
        ("HR Director", "HR Director", 2),
        ("Human Resources Manager", "HR Manager", 2),
        ("Chief Human Resources Officer", "HR Director", 2),
        ("Head - Corporate Communications", "Corporate Communications Head", 2),
        ("Public Relations Head", "Public Relations Head", 2),
        ("Head, Corporate Affairs", "Corporate Affairs Head", 2),
        ("Regional Manager - West", "Regional Manager", 3),
        ("Branch Manager", "Branch Manager", 3),
        ("General Manager", "General Manager", 3),
        ("Business Unit Head", "Business Unit Head", 3),
        ("Head of Operations", "Operations Head", 3),
    ],
)
def test_classify_target_roles(title, category, priority):
    match = roles.classify(title)
    assert match is not None and (match.category, match.priority) == (category, priority)


@pytest.mark.parametrize(
    "title",
    ["Managing Director", "Independent Director", "CSR Policy", "CSR Committee", "Our CSR Team", "HR Solutions",
     "CSR Intern", "Chief Financial Officer", "Talent Acquisition Manager"],
)
def test_classify_rejects_non_targets_and_headings(title):
    assert roles.classify(title) is None


def test_bare_committee_role_only_counts_inside_csr_committee_section():
    assert roles.classify("Chairman") is None
    assert roles.classify("Chairman", committee_context=True).category == "CSR Committee"
    assert roles.committee_designation("Chairperson") == "Chairperson, CSR Committee"
    assert roles.committee_designation("Member") == "Member, CSR Committee"


def test_mailbox_roles_match_whole_tokens():
    assert roles.mailbox_role("csr") == ("CSR Team", 1)
    assert roles.mailbox_role("csr.india") == ("CSR Team", 1)
    assert roles.mailbox_role("hr") == ("HR Team", 2)
    assert roles.mailbox_role("corpcomm") == ("Corporate Communications Team", 2)
    assert roles.mailbox_role("prakash") is None  # not "pr@"
    assert roles.is_general_mailbox("info") and not roles.is_general_mailbox("priya.sharma")


# ----------------------------------------------------------------------------
# Work-info-only policy
# ----------------------------------------------------------------------------
def test_company_email_must_be_on_company_domain():
    assert policy.is_company_email("csr@acme.com", "acme.com")
    assert policy.is_company_email("csr@in.acme.com", "acme.com")
    assert policy.is_company_email("csr@acme.co.in", "acme.com")  # sibling country domain
    assert not policy.is_company_email("priya@gmail.com", "acme.com")
    assert not policy.is_company_email("priya@othercorp.com", "acme.com")
    assert not policy.is_company_email("logo@2x.png", "acme.com")


def test_mobile_numbers_are_never_office_phones():
    assert not policy.is_office_phone("+91 98765 43210")
    assert not policy.is_office_phone("09876543210")
    assert not policy.is_office_phone("+91 22 6665 8282", "Mobile:")
    assert not policy.is_office_phone("+91 22 6665 8282", "Fax:")
    assert policy.is_office_phone("+91 22 6665 8282", "Tel:")
    assert policy.is_office_phone("020-2567 8900")
    assert policy.is_office_phone("1800 209 8282")
    # Outside India digits can't tell mobile from landline - needs an office label.
    assert not policy.is_office_phone("+44 20 7946 0958", "")
    assert policy.is_office_phone("+44 20 7946 0958", "Tel:")


def test_linkedin_profile_links_only():
    assert policy.is_linkedin_profile("https://www.linkedin.com/in/priya-sharma/")
    assert policy.is_linkedin_profile("https://in.linkedin.com/in/priya")
    assert not policy.is_linkedin_profile("https://www.linkedin.com/company/acme/")


# ----------------------------------------------------------------------------
# Extraction
# ----------------------------------------------------------------------------
def test_clean_person_name():
    assert extract.clean_person_name("Dr. (Ms.) Priya Sharma") == "Priya Sharma"
    assert extract.clean_person_name("N. Chandrasekaran") == "N. Chandrasekaran"
    assert extract.clean_person_name("K.V. Ramana Rao") == "K.V. Ramana Rao"
    assert extract.clean_person_name("PRIYA SHARMA") == "Priya Sharma"
    assert extract.clean_person_name("Leela D'Souza") == "Leela D'Souza"
    for not_a_name in ("Read More", "CSR Committee", "Board of Directors", "Annual Report 2024", "Contact Us", "Priya"):
        assert extract.clean_person_name(not_a_name) is None


def test_extract_leadership_cards_attach_details_to_the_right_person():
    page = extract.extract_page(LEADERSHIP, "https://acme.example.com/about-us/leadership", "acme.example.com")
    people = {p.name: p for p in page.people}
    assert set(people) == {"Priya Sharma", "Rahul Verma", "Meena Iyer"}  # MD isn't a target role
    priya = people["Priya Sharma"]
    assert (priya.designation, priya.role_category, priya.priority) == ("Head - CSR", "CSR Head", 1)
    assert priya.email == "priya.sharma@acme.example.com" and priya.email_status == "verified"
    assert priya.linkedin_url == "https://www.linkedin.com/in/priya-sharma-csr/"
    assert people["Rahul Verma"].email is None  # personal gmail dropped
    assert people["Meena Iyer"].location == "Pune"


def test_extract_csr_committee_table_but_not_other_committees():
    page = extract.extract_page(CSR_PAGE, "https://acme.example.com/csr", "acme.example.com")
    committee = {p.name: p.designation for p in page.people if p.role_category == "CSR Committee"}
    assert committee == {"N. Chandrasekaran": "Chairperson, CSR Committee", "Priya Sharma": "Member, CSR Committee"}
    assert "Vikram Yadav" not in {p.name for p in page.people}
    assert [(m.email, m.label) for m in page.mailboxes] == [("csr@acme.example.com", "CSR Team")]


def test_extract_inline_json_ld_and_press_quotes():
    html = """<script type="application/ld+json">{"@context":"https://schema.org","@graph":[
      {"@type":"Person","name":"Anita Rao","jobTitle":"Chief Sustainability Officer",
       "email":"anita.rao@acme.example.com","sameAs":["https://www.linkedin.com/in/anitarao"]}]}</script>
    <p>Mr. K.V. Ramana Rao, General Manager - Corporate Communications, Acme Industries Ltd</p>
    <p>"This is our biggest programme yet," said Sunil Mehta, Head of Foundation Initiatives, at the launch in Pune.</p>"""
    people = {p.name: p for p in extract.extract_page(html, "https://acme.example.com/news", "acme.example.com").people}
    assert people["Anita Rao"].method == "structured"
    assert people["Anita Rao"].email == "anita.rao@acme.example.com"
    assert people["Anita Rao"].linkedin_url == "https://www.linkedin.com/in/anitarao"
    assert people["K.V. Ramana Rao"].designation == "General Manager - Corporate Communications"
    assert people["Sunil Mehta"].method == "prose" and people["Sunil Mehta"].role_category == "Foundation Director"


def test_extract_contact_page_keeps_office_lines_and_drops_mobiles():
    page = extract.extract_page(CONTACT_PAGE, "https://acme.example.com/contact-us", "acme.example.com")
    assert [p.phone for p in page.phones] == ["+91 20 6645 1000"]
    assert page.office_city == "Pune"
    labels = {m.email: m.label for m in page.mailboxes}
    assert labels == {"info@acme.example.com": "General enquiries", "corpcomm@acme.example.com": "Corporate Communications Team"}


def test_inline_titles_stop_before_trailing_prose():
    html = """<h3>Rishab Bajaj, General Manager, EV Strategy, - Interaction with NDTV Profit</h3>
    <h3>Samardeep Subandh, President (Intracity Business Unit</h3>"""
    people = {p.name: p.designation for p in extract.extract_page(html, "https://acme.example.com/", "acme.example.com").people}
    assert people == {
        "Rishab Bajaj": "General Manager, EV Strategy",
        "Samardeep Subandh": "President (Intracity Business Unit)",
    }


def test_phone_key_matches_formats_of_the_same_number():
    assert policy.phone_key("+912027407000") == policy.phone_key("+91 (020) 2740 7000") == policy.phone_key("020-27407000")


def test_untitled_individual_emails_are_not_kept():
    html = "<p>Questions? Write to priya.sharma@acme.example.com</p>"
    page = extract.extract_page(html, "https://acme.example.com/", "acme.example.com")
    assert page.people == [] and page.mailboxes == []


# ----------------------------------------------------------------------------
# Reports
# ----------------------------------------------------------------------------
REPORT_PAGE_TEXT = """Annual Report on CSR Activities
2. Composition of CSR Committee:
Sl. No. Name of Director Designation / Nature of Directorship Meetings held Meetings attended
1 Mr. N. Chandrasekaran Chairman, Non-Executive Director 3 3
2 Ms. Hema Ravichandar Member, Independent Director 3 3
3 Mr. T. V. Narendran Member, Executive Director 3 2
Nomination and Remuneration Committee
1 Mr. Someone Else Chairman 4 4
"""

BRSR_TEXT = """Details of the highest authority responsible for implementation and oversight of the
Business Responsibility policy (ies).
Name: Ms. Anita Rao Designation: Chief Sustainability Officer Telephone: 022 6665 8282
"""


def test_parse_report_text_committee_rows():
    hits = reports.parse_report_text(REPORT_PAGE_TEXT, "https://acme.example.com/r.pdf#page=42")
    committee = {h.name: h.designation for h in hits}
    assert committee == {
        "N. Chandrasekaran": "Chairperson, CSR Committee",
        "Hema Ravichandar": "Member, CSR Committee",
        "T.V. Narendran": "Member, CSR Committee",
    }
    assert all(h.method == "report" and h.source_url.endswith("#page=42") for h in hits)


def test_parse_report_text_brsr_authority():
    hits = reports.parse_report_text(BRSR_TEXT, "https://acme.example.com/brsr.pdf#page=7")
    assert len(hits) == 1
    assert hits[0].name == "Anita Rao"
    assert hits[0].role_category == "Sustainability Head"
    assert "BRSR" in hits[0].designation


def test_scan_report_reports_fetch_problems():
    result = reports.scan_report("https://acme.example.com/big.pdf", fetch=lambda url: (None, "too large"))
    assert result["people"] == [] and result["message"] == "too large"


# ----------------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------------
def test_infer_email_pattern_needs_agreement():
    assert infer_email_pattern([("Priya Sharma", "priya.sharma@acme.com")]) == "first.last"
    assert infer_email_pattern([("Priya Sharma", "psharma@acme.com")]) == "flast"
    assert infer_email_pattern([("Priya Sharma", "priya.sharma@acme.com"), ("Rahul Verma", "rverma@acme.com")]) is None


def test_find_crawls_hint_pages_in_priority_order_and_respects_scope():
    fetched = []
    result = make_service(fetched=fetched).find(ACME)
    assert fetched[0] == "https://acme.example.com/"
    assert fetched.index("https://acme.example.com/csr") < fetched.index("https://acme.example.com/about-us/leadership")
    assert fetched.index("https://acme.example.com/about-us/leadership") < fetched.index("https://acme.example.com/contact-us")
    assert not any("careers" in url or "othersite" in url for url in fetched)
    assert result["report_links"] == ["https://acme.example.com/files/csr-report-2024.pdf"]


def test_press_pages_are_capped_even_when_their_slug_mentions_csr():
    links = "".join(f'<a href="/media/press-releases/csr-story-{n}">CSR story {n}</a>' for n in range(6))
    site = {"https://acme.example.com/": f"<html><body><p>Acme Industries home page with news.</p>{links}</body></html>"}
    fetched = []
    make_service(site=site, fetched=fetched).find(ACME)
    assert len([u for u in fetched if "press-releases" in u]) == 2


def test_find_merges_sightings_and_scores_confidence():
    result = make_service().find(ACME)
    names = [c["name"] for c in result["contacts"]]
    # Priority 1 first, Priority 3 last; the company's own name never appears as a person.
    assert names[-1] == "Meena Iyer"
    assert [c["priority"] for c in result["contacts"]] == sorted(c["priority"] for c in result["contacts"])

    priya = by_name(result, "Priya Sharma")
    assert priya["designation"] == "Head - CSR"  # the CSR Head title beats the committee seat
    assert {s["url"] for s in priya["sources"]} == {
        "https://acme.example.com/csr",
        "https://acme.example.com/about-us/leadership",
    }
    assert priya["provenance"]["email"]["status"] == "verified"
    assert priya["provenance"]["linkedin_url"]["status"] == "verified"
    assert priya["confidence"] > by_name(result, "N. Chandrasekaran")["confidence"]
    assert any("2 separate sources" in reason for reason in priya["confidence_reasons"])


def test_find_labels_company_level_fallbacks_honestly():
    result = make_service().find(ACME)
    rahul = by_name(result, "Rahul Verma")
    assert rahul["email"] == "rahul.verma@acme.example.com"  # first.last pattern from Priya's published address
    assert rahul["provenance"]["email"]["status"] == "inferred"
    assert rahul["phone"] == "+91 20 6645 1000"
    assert "not a direct line" in rahul["provenance"]["phone"]["source"]
    assert rahul["office_location"] == "Pune"
    assert rahul["provenance"]["office_location"]["status"] == "inferred"
    assert rahul["linkedin_url"] is None and rahul["provenance"]["linkedin_url"]["status"] == "unavailable"
    assert "linkedin.com/search" in rahul["linkedin_search_url"]

    meena = by_name(result, "Meena Iyer")
    assert meena["provenance"]["office_location"]["status"] == "verified"


def test_find_turns_role_mailboxes_into_team_contacts_and_lists_contact_points():
    result = make_service().find(ACME)
    csr_team = by_name(result, "CSR Team")
    assert csr_team["is_shared_mailbox"] and csr_team["email"] == "csr@acme.example.com"
    assert csr_team["provenance"]["name"]["status"] == "inferred"
    assert by_name(result, "Corporate Communications Team")["priority"] == 2
    points = {(p["kind"], p["value"]) for p in result["contact_points"]}
    assert points == {("email", "info@acme.example.com"), ("phone", "+91 20 6645 1000")}
    assert not any("98765" in p["value"] for p in result["contact_points"])


def test_find_explains_robots_block_and_offers_searches():
    result = make_service(robots=Disallow("/")).find(ACME)
    assert result["contacts"] == []
    assert result["pages_blocked"] == ["https://acme.example.com/"]
    assert any("robots.txt" in m for m in result["messages"])
    assert any("linkedin.com/search" in s["url"] for s in result["suggested_searches"])


def test_find_without_website():
    result = make_service().find(CompanyContext(name="Acme Industries Ltd"))
    assert result["contacts"] == [] and result["pages_checked"] == []
    assert any("No website is known" in m for m in result["messages"])


def test_find_falls_back_to_common_paths_for_javascript_shells():
    site = {"https://acme.example.com/": "<html><body><div id='root'></div></body></html>",
            "https://acme.example.com/csr": CSR_PAGE}
    fetched = []
    result = make_service(site=site, fetched=fetched).find(ACME)
    assert "https://acme.example.com/csr" in fetched
    assert by_name(result, "N. Chandrasekaran")


def test_find_scans_report_only_when_asked():
    scanned = []

    def scanner(url):
        scanned.append(url)
        hits = reports.parse_report_text(REPORT_PAGE_TEXT, url + "#page=42")
        return {"people": hits, "pages_read": 120, "relevant_pages": [42], "message": None}

    service = make_service(report_scanner=scanner)
    assert service.find(ACME)["report"]["scanned"] is False and scanned == []
    result = service.find(ACME, include_reports=True)
    assert scanned == ["https://acme.example.com/files/csr-report-2024.pdf"]
    assert result["report"]["relevant_pages"] == [42]
    hema = by_name(result, "Hema Ravichandar")
    assert hema["sources"][0]["source_type"] == "csr_report"
    # Seen on the website and in the report: two sources.
    assert len(by_name(result, "N. Chandrasekaran")["sources"]) == 2


def test_third_party_results_are_classified_and_never_keep_phones():
    rows = [
        {"name": "Kavita Joshi", "designation": "Sustainability Manager", "email": "kavita.joshi@acme.example.com",
         "phone": "+91 98200 00000", "linkedin_url": "https://www.linkedin.com/in/kavitajoshi",
         "source_url": "https://hunter.io/domain-search/acme.example.com"},
        {"name": "Sam Lee", "designation": "Software Engineer", "email": "sam@acme.example.com"},
    ]
    result = make_service(site={}, third_party=lambda domain: rows, configured=True).find(ACME)
    assert [c["name"] for c in result["contacts"]] == ["Kavita Joshi"]
    kavita = result["contacts"][0]
    assert kavita["phone"] is None and kavita["sources"][0]["source_type"] == "third_party"


def test_find_results_are_cached_until_refresh():
    fetched = []
    service = make_service(fetched=fetched)
    service.find(ACME)
    count = len(fetched)
    assert service.find(ACME)["cached"] is True and len(fetched) == count
    service.find(ACME, refresh=True)
    assert len(fetched) == 2 * count


def test_enrichment_title_filter_defaults_unchanged():
    data = {"data": {"emails": [{"value": "a@x.com", "position": "CSR Manager"}, {"value": "b@x.com", "position": "Regional Manager"}]}}
    assert [r["email"] for r in enrichment.parse_hunter_response(data, "x.com")] == ["a@x.com"]
    keep_all = lambda title: True  # noqa: E731
    assert len(enrichment.parse_hunter_response(data, "x.com", keep_all)) == 2


# ----------------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------------
def test_search_for_saved_lead_flags_already_saved_contacts_and_logs(client, fake_service):
    company = _create_company(client)
    client.post(f"/api/companies/{company['id']}/contacts", json={"name": "Priya Sharma", "email": "priya.sharma@acme.example.com"})

    response = client.post("/api/contact-discovery/search", json={"company_id": company["id"]})
    assert response.status_code == 200
    body = response.json()
    assert body["saved_company_id"] == company["id"]
    assert by_name(body, "Priya Sharma")["saved_contact_id"] is not None
    assert by_name(body, "Rahul Verma")["saved_contact_id"] is None
    assert body["log_id"]

    logs = client.get("/api/contact-discovery/logs", params={"company_id": company["id"]}).json()
    assert len(logs) == 1 and logs[0]["candidates_found"] == len(body["contacts"])
    assert "https://acme.example.com/csr" in logs[0]["pages_checked"]


def test_search_for_unsaved_company(client, fake_service):
    response = client.post(
        "/api/contact-discovery/search",
        json={"name": "Acme Industries Ltd", "website": "https://acme.example.com", "city": "Mumbai"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["saved_company_id"] is None and len(body["contacts"]) > 3


def test_search_validation(client, fake_service):
    assert client.post("/api/contact-discovery/search", json={"company_id": 999}).status_code == 404
    assert client.post("/api/contact-discovery/search", json={"name": "  "}).status_code == 400


def _candidates(client):
    body = client.post("/api/contact-discovery/search", json={"name": "Acme Industries Ltd", "website": "https://acme.example.com"}).json()
    return body["contacts"]


def _to_save(candidate):
    keys = ["name", "designation", "role_category", "priority", "office_location", "email", "phone", "linkedin_url",
            "source_url", "confidence", "provenance", "sources"]
    return {k: candidate[k] for k in keys}


def test_save_contacts_for_unsaved_company_creates_lead_once(client, fake_service):
    candidates = _candidates(client)
    priya = next(c for c in candidates if c["name"] == "Priya Sharma")
    meena = next(c for c in candidates if c["name"] == "Meena Iyer")
    company_payload = {"name": "Acme Industries Ltd", "website": "https://acme.example.com", "city": "Mumbai",
                       "sources": [{"name": "Wikidata", "url": "https://www.wikidata.org/wiki/Q1"}]}

    response = client.post(
        "/api/contact-discovery/save",
        json={"company": company_payload, "contacts": [_to_save(priya), _to_save(meena)]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["company_created"] is True and len(body["saved"]) == 2
    company_id = body["company_id"]
    saved_priya = body["saved"][0]
    assert saved_priya["origin"] == "discovery" and saved_priya["priority"] == 1
    assert saved_priya["provenance"]["email"]["status"] == "verified"

    # The search made before the lead existed is now part of its history.
    logs = client.get("/api/contact-discovery/logs", params={"company_id": company_id}).json()
    assert len(logs) == 1 and logs[0]["company_name"] == "Acme Industries Ltd"

    # The lead got its provenance note; saving again attaches to the same lead
    # and reports duplicates instead of creating them.
    detail = client.get(f"/api/companies/{company_id}").json()
    assert any("Saved from company discovery" in n["body"] for n in detail["notes"])
    again = client.post("/api/contact-discovery/save", json={"company": company_payload, "contacts": [_to_save(priya)]}).json()
    assert again["company_created"] is False and again["company_id"] == company_id
    assert again["saved"] == [] and again["duplicates"][0]["existing_contact_name"] == "Priya Sharma"

    forced = client.post(
        "/api/contact-discovery/save", json={"company_id": company_id, "contacts": [_to_save(priya)], "force": True}
    ).json()
    assert len(forced["saved"]) == 1


def test_save_matches_duplicates_by_linkedin(client, fake_service):
    company = _create_company(client)
    client.post(f"/api/companies/{company['id']}/contacts", json={"name": "P. Sharma", "linkedin_url": "https://in.linkedin.com/in/priya-sharma-csr"})
    priya = next(c for c in _candidates(client) if c["name"] == "Priya Sharma")
    priya["email"] = None
    body = client.post("/api/contact-discovery/save", json={"company_id": company["id"], "contacts": [_to_save(priya)]}).json()
    assert body["saved"] == [] and body["duplicates"][0]["existing_contact_name"] == "P. Sharma"


def test_save_enforces_work_info_rules_on_client_data(client, fake_service):
    company = _create_company(client)
    response = client.post(
        "/api/contact-discovery/save",
        json={"company_id": company["id"], "contacts": [
            {"name": "Rahul Verma", "designation": "HR Director", "email": "rahul@gmail.com", "phone": "+91 98765 43210",
             "linkedin_url": "https://example.com/not-linkedin"}]},
    )
    body = response.json()
    saved = body["saved"][0]
    assert saved["email"] is None and saved["phone"] is None and saved["linkedin_url"] is None
    assert saved["provenance"]["email"]["status"] == "unavailable"
    assert len(body["dropped"]) == 2


def test_save_requires_a_company(client):
    response = client.post("/api/contact-discovery/save", json={"contacts": [{"name": "X Y"}]})
    assert response.status_code == 400


def test_contact_search_filters(client, fake_service):
    acme = _create_company(client)
    other = _create_company(client, name="Bharat Pharma", website="https://bharat.example.com", city="Hyderabad",
                            state="Telangana", industry="Pharmaceuticals")
    for candidate in _candidates(client):
        if candidate["name"] in ("Priya Sharma", "Meena Iyer"):
            client.post("/api/contact-discovery/save", json={"company_id": acme["id"], "contacts": [_to_save(candidate)]})
    client.post(f"/api/companies/{other['id']}/contacts", json={"name": "Kiran Rao", "designation": "HR Manager"})

    def names(**params):
        return {c["name"] for c in client.get("/api/contacts", params=params).json()}

    assert names() == {"Priya Sharma", "Meena Iyer", "Kiran Rao"}
    assert names(company="acme") == {"Priya Sharma", "Meena Iyer"}
    assert names(name="kiran") == {"Kiran Rao"}
    assert names(designation="csr") == {"Priya Sharma"}
    assert names(designation="Regional Manager") == {"Meena Iyer"}  # matches role category too
    assert names(industry="pharma") == {"Kiran Rao"}
    assert names(state="telangana") == {"Kiran Rao"}
    # Contact's own office (Meena: stated; Priya: inferred from the contact page) or the company's HQ city.
    assert names(city="pune") == {"Priya Sharma", "Meena Iyer"}
    assert names(city="mumbai") == {"Priya Sharma", "Meena Iyer"}
    assert names(city="hyderabad") == {"Kiran Rao"}
    assert names(priority=3) == {"Meena Iyer"}
    row = client.get("/api/contacts", params={"name": "kiran"}).json()[0]
    assert row["company_name"] == "Bharat Pharma" and row["company_state"] == "Telangana"


def test_contact_profile_sources_notes_and_timeline(client, fake_service):
    company = _create_company(client)
    priya = next(c for c in _candidates(client) if c["name"] == "Priya Sharma")
    saved = client.post("/api/contact-discovery/save", json={"company_id": company["id"], "contacts": [_to_save(priya)]}).json()
    contact_id = saved["saved"][0]["id"]

    note = client.post(f"/api/contacts/{contact_id}/notes", json={"body": "Met at the CSR summit."})
    assert note.status_code == 201 and note.json()["contact_id"] == contact_id
    client.patch(f"/api/contacts/{contact_id}", json={"office_location": "Mumbai"})

    profile = client.get(f"/api/contacts/{contact_id}").json()
    assert profile["company"]["name"] == "Acme Industries Ltd" and profile["company"]["status"] == "New"
    assert {s["source_type"] for s in profile["sources"]} == {"website"}
    assert len(profile["sources"]) == 2
    assert [n["body"] for n in profile["notes"]] == ["Met at the CSR summit."]
    events = [a["event_type"] for a in profile["activity_logs"]]
    assert set(events) == {"contact_added", "note_added", "contact_updated"}
    assert profile["office_location"] == "Mumbai"

    # The contact note is still a company note, and the company timeline has it too.
    detail = client.get(f"/api/companies/{company['id']}").json()
    assert any(n["contact_id"] == contact_id for n in detail["notes"])
    assert client.get("/api/contacts/999").status_code == 404
    assert client.post("/api/contacts/999/notes", json={"body": "x"}).status_code == 404


def test_deleting_a_contact_keeps_its_notes_on_the_company(client):
    company = _create_company(client)
    contact = client.post(f"/api/companies/{company['id']}/contacts", json={"name": "Jane Doe"}).json()
    client.post(f"/api/contacts/{contact['id']}/notes", json={"body": "Prefers email."})
    assert client.delete(f"/api/contacts/{contact['id']}").status_code == 204
    notes = client.get(f"/api/companies/{company['id']}").json()["notes"]
    assert [n["body"] for n in notes] == ["Prefers email."] and notes[0]["contact_id"] is None


def test_manual_contacts_are_marked_manual(client):
    company = _create_company(client)
    contact = client.post(f"/api/companies/{company['id']}/contacts", json={"name": "Jane Doe"}).json()
    assert contact["origin"] == "manual" and contact["provenance"] is None


# ----------------------------------------------------------------------------
# Startup column upgrade
# ----------------------------------------------------------------------------
def test_add_missing_columns_upgrades_an_old_database_in_place():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE companies (id INTEGER PRIMARY KEY, name VARCHAR(255) NOT NULL)"))
        conn.execute(text(
            "CREATE TABLE contacts (id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, name VARCHAR(255) NOT NULL)"
        ))
        conn.execute(text("INSERT INTO contacts (id, company_id, name) VALUES (1, 1, 'Jane Doe')"))

    added = add_missing_columns(engine)
    assert "contacts.priority" in added and "contacts.provenance" in added and "companies.csr_report_url" in added
    columns = {c["name"] for c in inspect(engine).get_columns("contacts")}
    assert {"office_location", "role_category", "priority", "confidence", "provenance", "origin"} <= columns
    with engine.connect() as conn:
        assert conn.execute(text("SELECT name, priority FROM contacts")).fetchall() == [("Jane Doe", None)]
    assert add_missing_columns(engine) == []  # idempotent


# ----------------------------------------------------------------------------
# Regressions found running against real company websites
# ----------------------------------------------------------------------------
def test_article_teasers_are_not_people():
    html = """<div><h4>Client Success</h4><p>Global Publishing Leader Achieves 10% Growth by Modernizing Operations</p></div>"""
    assert extract.extract_page(html, "https://acme.example.com/", "acme.example.com").people == []


def test_city_in_a_biography_is_not_an_office_location():
    html = """<div><h4>Amit Dalmia</h4><p>Member - CSR Committee</p>
    <p>Mr. Dalmia graduated from St. Xavier's College in Kolkata and has over 25 years of experience in
    finance, strategy and corporate governance across several listed companies.</p></div>
    <div><h4>Neha Kulkarni</h4><p>CSR Manager</p><p>Based in Pune</p></div>"""
    people = {p.name: p for p in extract.extract_page(html, "https://acme.example.com/csr", "acme.example.com").people}
    assert people["Amit Dalmia"].location is None
    assert people["Neha Kulkarni"].location == "Pune"


def test_crawl_ignores_product_and_article_pages_whose_path_mentions_csr_words():
    home = """<html><body><p>Acme Industries - engineering for a sustainable future.</p>
    <a href="/sustainability/services/impact-intelligence">Impact Intelligence</a>
    <a href="/client-success/building-a-real-time-payments-foundation-for-a-leading-us-fintech">Building a payments foundation for a leading US fintech</a>
    <a href="/sustainability/">Sustainability</a></body></html>"""
    fetched = []
    make_service(site={"https://acme.example.com/": home}, fetched=fetched).find(ACME)
    assert "https://acme.example.com/sustainability/" in fetched
    assert not any("impact-intelligence" in u or "client-success" in u for u in fetched)


def test_load_robots_uses_our_user_agent_and_rfc_status_rules(monkeypatch):
    from app.contact_discovery import service as service_module

    class Response:
        def __init__(self, status, body=""):
            self.status_code, self.text = status, body

    seen_agents = []

    def fake_get(url, headers, timeout):
        seen_agents.append(headers["User-Agent"])
        return responses[url]

    monkeypatch.setattr(service_module.requests, "get", fake_get)
    responses = {
        "https://a.example/robots.txt": Response(200, "User-agent: *\nDisallow: /private/"),
        "https://b.example/robots.txt": Response(403),
        "https://c.example/robots.txt": Response(404),
        "https://d.example/robots.txt": Response(503),
    }
    agent = service_module.scraping.USER_AGENT
    a = service_module.load_robots("https://a.example")
    assert a.can_fetch(agent, "https://a.example/csr") and not a.can_fetch(agent, "https://a.example/private/x")
    assert not service_module.load_robots("https://b.example").can_fetch(agent, "https://b.example/csr")
    assert service_module.load_robots("https://c.example").can_fetch(agent, "https://c.example/csr")
    assert not service_module.load_robots("https://d.example").can_fetch(agent, "https://d.example/csr")
    assert set(seen_agents) == {agent}


def test_indian_office_line_preferred_over_overseas_offices():
    contact = """<html><body><h1>Contact us</h1><p>New York: Tel +1 (212) 686 6655</p>
    <p>Bengaluru: Tel +91 080 4004 4444</p></body></html>"""
    site = {"https://acme.example.com/": HOME, "https://acme.example.com/contact-us": contact,
            "https://acme.example.com/about-us/leadership": LEADERSHIP}
    result = make_service(site=site).find(ACME)
    assert by_name(result, "Rahul Verma")["phone"] == "+91 080 4004 4444"
    assert result["contact_points"][0]["value"] == "+91 080 4004 4444"


def test_report_links_ranked_for_committee_and_press_pdfs_dropped():
    from app.contact_discovery.service import rank_report_links

    links = [
        "https://acme.example.com/news/press_releases/esg-rating.pdf",
        "https://acme.example.com/media/esg-all-in-one.pdf",
        "https://acme.example.com/files/csr-report-2024.pdf",
        "https://acme.example.com/files/csr-report-2024.pdf",
        "https://acme.example.com/files/BRSR-2025.pdf",
        "https://acme.example.com/files/Acme-Annual-Report-2025.pdf",
    ]
    assert rank_report_links(links) == [
        "https://acme.example.com/files/Acme-Annual-Report-2025.pdf",
        "https://acme.example.com/files/BRSR-2025.pdf",
        "https://acme.example.com/files/csr-report-2024.pdf",
    ]


def test_report_scan_tries_a_second_report_when_the_first_names_nobody():
    home = HOME.replace("</nav>", '<a href="/files/Acme-Annual-Report-2025.pdf">Annual Report</a></nav>')
    scanned = []

    def scanner(url):
        scanned.append(url)
        if "Annual" in url:
            return {"people": [], "pages_read": 300, "relevant_pages": [], "message": "none"}
        return {"people": reports.parse_report_text(REPORT_PAGE_TEXT, url + "#page=3"), "pages_read": 20,
                "relevant_pages": [3], "message": None}

    site = dict(SITE, **{"https://acme.example.com/": home})
    result = make_service(site=site, report_scanner=scanner).find(ACME, include_reports=True)
    assert scanned == ["https://acme.example.com/files/Acme-Annual-Report-2025.pdf",
                       "https://acme.example.com/files/csr-report-2024.pdf"]
    assert result["report"]["pages_read"] == 320
    assert by_name(result, "Hema Ravichandar")


# Layouts copied from a real FY2025-26 annual report (Corporate Governance
# Report + Annexure on CSR), names replaced.
GOVERNANCE_TEXT = """Email: investor@acme.example.com
D. Corporate Social Responsibility (CSR) Committee
The CSR Committee comprises two Independent Directors and a Non-Executive Director as members as on March
31, 2026:
 1. Meera Kapoor - Chairperson
 2. Dr. S. B. (Ravi) Joshi
 3. Farhan R. Mistry
The CSR Committee met twice during the financial year 2025-26. Attendance details are as follows:
Name of the Member
Meera Kapoor   2 2 100
Dr. S. B. (Ravi) Joshi   2 2 100
Farhan R. Mistry   2 2 100
• Formulate and recommend a CSR policy to the Board
E. Risk Management Committee
 1. Dr. S. B. (Ravi) Joshi – Chairman
 2. Kiran Bose
"""

ANNEXURE_TEXT = """2. Composition of the CSR Committee
Sr.
No. Name of Director Designation/ Nature of Directorship Number of Meetings
1. Meera Kapoor
Chairperson Non Executive Promoter Director
2 2
2. Dr. S.B (Ravi) Joshi
Committee Member & Non-Executive Independent
Director
2 2
3. Provide the web link where the composition of the CSR committee is disclosed
"""


def test_parse_real_annual_report_layouts():
    governance = {h.name: h.designation for h in reports.parse_report_text(GOVERNANCE_TEXT, "r.pdf#page=74")}
    assert governance == {
        "Meera Kapoor": "Chairperson, CSR Committee",
        "S.B. Joshi": "Member, CSR Committee",
        "Farhan R. Mistry": "Member, CSR Committee",
    }  # Risk Management Committee members excluded
    annexure = {extract.name_key(h.name): h.designation for h in reports.parse_report_text(ANNEXURE_TEXT, "r.pdf#page=106")}
    assert annexure == {"meera kapoor": "Chairperson, CSR Committee", "s b joshi": "Member, CSR Committee"}


def test_pdf_ligatures_are_normalized():
    hits = reports.parse_report_text("Name: Ms. Anita Rao Designation: Chief Sustainability Oﬃcer Telephone: 022", "r.pdf#page=1")
    assert hits[0].role_category == "Sustainability Head"


def test_phone_fragments_are_rejected():
    assert not policy.is_office_phone("000 800 100")
    assert policy.is_office_phone("000 800 100 4175")


def test_a_large_section_cannot_crowd_out_leadership_pages():
    products = "".join(f'<a href="/sustainability/services/sustainable-product-{n}">Sustainable product {n}</a>' for n in range(15))
    home = f"""<html><body><p>Acme Industries home page.</p>{products}
    <a href="/financials/annual-results">Results</a>
    <a href="/company-overview/leadership/executive-council">Executive Council</a></body></html>"""
    fetched = []
    make_service(site={"https://acme.example.com/": home}, fetched=fetched).find(ACME)
    assert "https://acme.example.com/company-overview/leadership/executive-council" in fetched
    assert len([u for u in fetched if "sustainable-product" in u]) == 4
    assert not any("financials" in u for u in fetched)


def test_office_address_cards_are_not_people():
    html = """<div><h4>Dubai One Central</h4><p>Wipro Ltd (Wipro APMEA Head office) (DWTCA Branch)</p></div>
    <div><h4>Neha Kulkarni</h4><p>Branch Manager</p></div>"""
    people = [p.name for p in extract.extract_page(html, "https://acme.example.com/contact-us", "acme.example.com").people]
    assert people == ["Neha Kulkarni"]


def test_explicitly_indian_lines_beat_ambiguous_and_foreign_ones():
    contact = """<html><body><h1>Contact us</h1><p>Seattle: Tel 425-476-3335</p>
    <p>London: Tel +44 (0)20 7717 4444</p><p>Bengaluru: Tel 080 2844 0011</p></body></html>"""
    site = {"https://acme.example.com/": HOME, "https://acme.example.com/contact-us": contact,
            "https://acme.example.com/about-us/leadership": LEADERSHIP}
    result = make_service(site=site).find(ACME)
    assert [p["value"] for p in result["contact_points"]] == ["080 2844 0011", "425-476-3335", "+44 (0)20 7717 4444"]
    assert by_name(result, "Rahul Verma")["phone"] == "080 2844 0011"


@pytest.mark.parametrize(
    "phone, mobile",
    [
        ("+91 98765 43210", True), ("98765-43210", True), ("+91-9876543210", True), ("09876543210", True),
        ("+91 70123 45678", True), ("+918028440011", True),  # ambiguous run of digits: treated as mobile
        ("080 2844 0011", False), ("+91 80 2844 0011", False), ("(080) 2844 0011", False),
        ("+91 (0)79 2656 1234", False), ("+91 22 6665 8282", False), ("+912027407000", False),
        ("1800 209 8282", False), ("+44 20 7717 4444", False),
    ],
)
def test_indian_mobile_detection_by_how_the_number_is_written(phone, mobile):
    assert policy.is_indian_mobile(phone) is mobile
