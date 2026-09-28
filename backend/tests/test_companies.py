def _create_company(client, **overrides):
    name = overrides.get("name", "Acme Industries")
    slug = name.lower().replace(" ", "-")
    payload = {
        "name": name,
        "industry": "Manufacturing",
        "city": "Pune",
        "state": "Maharashtra",
        "website": f"https://{slug}.example.com",
        "csr_focus": "Education",
        "csr_spending": 5_000_000,
        "revenue": 500_000_000,
        "employee_count": 1200,
    }
    payload.update(overrides)
    response = client.post("/api/companies", json=payload)
    assert response.status_code == 201
    return response.json()


def test_health_check(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_and_get_company(client):
    created = _create_company(client)
    company_id = created["id"]
    assert created["status"] == "New"

    response = client.get(f"/api/companies/{company_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Acme Industries"
    assert body["contacts"] == []
    assert body["notes"] == []


def test_get_missing_company_404(client):
    response = client.get("/api/companies/999")
    assert response.status_code == 404


def test_list_companies_filters(client):
    _create_company(client, name="Acme Industries", industry="Manufacturing", city="Pune")
    _create_company(client, name="Beta Health", industry="Healthcare", city="Mumbai")

    response = client.get("/api/companies", params={"industry": "Manufacturing"})
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0]["name"] == "Acme Industries"

    response = client.get("/api/companies", params={"city": "Mumbai"})
    results = response.json()
    assert len(results) == 1
    assert results[0]["name"] == "Beta Health"


def test_list_companies_csr_spending_range(client):
    _create_company(client, name="Small Spender", csr_spending=100_000)
    _create_company(client, name="Big Spender", csr_spending=10_000_000)

    response = client.get("/api/companies", params={"min_csr_spending": 1_000_000})
    results = response.json()
    assert len(results) == 1
    assert results[0]["name"] == "Big Spender"


def test_update_company_status_and_follow_up(client):
    created = _create_company(client)
    company_id = created["id"]

    response = client.patch(
        f"/api/companies/{company_id}",
        json={"status": "Contacted", "follow_up_date": "2026-10-01"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "Contacted"
    assert body["follow_up_date"] == "2026-10-01"


def test_delete_company(client):
    created = _create_company(client)
    company_id = created["id"]

    response = client.delete(f"/api/companies/{company_id}")
    assert response.status_code == 204

    response = client.get(f"/api/companies/{company_id}")
    assert response.status_code == 404


def test_company_list_includes_contact_count(client):
    created = _create_company(client)
    company_id = created["id"]

    client.post(
        f"/api/companies/{company_id}/contacts",
        json={"name": "Jane Doe", "designation": "CSR Head"},
    )

    response = client.get("/api/companies")
    results = response.json()
    assert results[0]["contact_count"] == 1


def test_csr_report_url_set_and_cleared_via_patch(client):
    company_id = _create_company(client)["id"]

    response = client.patch(
        f"/api/companies/{company_id}",
        json={"csr_report_url": "https://acme.example.com/csr-report-2026.pdf"},
    )
    assert response.status_code == 200
    assert response.json()["csr_report_url"] == "https://acme.example.com/csr-report-2026.pdf"
    # The website is a separate field and must survive an edit to the report link.
    assert response.json()["website"] == "https://acme-industries.example.com"

    # update_company uses exclude_unset, so an explicit null clears the field
    # rather than being treated as "not provided".
    response = client.patch(f"/api/companies/{company_id}", json={"csr_report_url": None})
    assert response.status_code == 200
    assert response.json()["csr_report_url"] is None
