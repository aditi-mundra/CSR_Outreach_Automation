def _create_company(client):
    response = client.post("/api/companies", json={"name": "Acme Industries"})
    return response.json()["id"]


def test_add_multiple_contacts_to_company(client):
    company_id = _create_company(client)

    client.post(
        f"/api/companies/{company_id}/contacts",
        json={"name": "Jane Doe", "designation": "CSR Head", "email": "jane@acme.example.com"},
    )
    client.post(
        f"/api/companies/{company_id}/contacts",
        json={"name": "John Smith", "designation": "HR Head"},
    )

    response = client.get(f"/api/companies/{company_id}")
    contacts = response.json()["contacts"]
    assert len(contacts) == 2
    assert {c["name"] for c in contacts} == {"Jane Doe", "John Smith"}


def test_update_and_delete_contact(client):
    company_id = _create_company(client)
    contact = client.post(
        f"/api/companies/{company_id}/contacts", json={"name": "Jane Doe"}
    ).json()

    response = client.patch(
        f"/api/contacts/{contact['id']}", json={"designation": "Sustainability Head"}
    )
    assert response.status_code == 200
    assert response.json()["designation"] == "Sustainability Head"

    response = client.delete(f"/api/contacts/{contact['id']}")
    assert response.status_code == 204

    response = client.get(f"/api/companies/{company_id}")
    assert response.json()["contacts"] == []


def test_contact_for_missing_company_404(client):
    response = client.post("/api/companies/999/contacts", json={"name": "Jane Doe"})
    assert response.status_code == 404


def test_add_and_delete_note(client):
    company_id = _create_company(client)

    response = client.post(
        f"/api/companies/{company_id}/notes", json={"body": "Had a great first call."}
    )
    assert response.status_code == 201
    note = response.json()

    detail = client.get(f"/api/companies/{company_id}").json()
    assert len(detail["notes"]) == 1
    assert detail["notes"][0]["body"] == "Had a great first call."

    response = client.delete(f"/api/notes/{note['id']}")
    assert response.status_code == 204

    detail = client.get(f"/api/companies/{company_id}").json()
    assert detail["notes"] == []


def test_deleting_company_cascades_contacts_and_notes(client):
    company_id = _create_company(client)
    client.post(f"/api/companies/{company_id}/contacts", json={"name": "Jane Doe"})
    client.post(f"/api/companies/{company_id}/notes", json={"body": "note"})

    response = client.delete(f"/api/companies/{company_id}")
    assert response.status_code == 204

    # Cascade delete shouldn't leave orphaned rows reachable via any endpoint.
    assert client.get(f"/api/companies/{company_id}").status_code == 404


def test_duplicate_contact_email_rejected_with_409(client):
    company_id = _create_company(client)
    first = client.post(
        f"/api/companies/{company_id}/contacts",
        json={"name": "Jane Doe", "email": "jane@acme.example.com"},
    )
    assert first.status_code == 201

    # Same email, different spelling of the name - the re-scan case.
    response = client.post(
        f"/api/companies/{company_id}/contacts",
        json={"name": "J. Doe", "email": "JANE@acme.example.com"},
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["existing_contact_id"] == first.json()["id"]
    assert detail["existing_contact_name"] == "Jane Doe"

    assert len(client.get(f"/api/companies/{company_id}").json()["contacts"]) == 1


def test_duplicate_contact_name_rejected_with_409(client):
    company_id = _create_company(client)
    client.post(f"/api/companies/{company_id}/contacts", json={"name": "Jane Doe"})

    response = client.post(f"/api/companies/{company_id}/contacts", json={"name": "jane doe"})
    assert response.status_code == 409


def test_duplicate_contact_allowed_with_force(client):
    company_id = _create_company(client)
    client.post(
        f"/api/companies/{company_id}/contacts",
        json={"name": "Jane Doe", "email": "jane@acme.example.com"},
    )

    response = client.post(
        f"/api/companies/{company_id}/contacts?force=true",
        json={"name": "Jane Doe", "email": "jane@acme.example.com"},
    )
    assert response.status_code == 201
    assert len(client.get(f"/api/companies/{company_id}").json()["contacts"]) == 2


def test_same_contact_email_allowed_under_a_different_company(client):
    first_company = _create_company(client)
    second_company = client.post("/api/companies", json={"name": "Beta Corp"}).json()["id"]

    client.post(
        f"/api/companies/{first_company}/contacts",
        json={"name": "Jane Doe", "email": "jane@shared.example.com"},
    )
    # Duplicate detection is scoped per company on purpose - the same
    # professional appearing under two companies is a real situation.
    response = client.post(
        f"/api/companies/{second_company}/contacts",
        json={"name": "Jane Doe", "email": "jane@shared.example.com"},
    )
    assert response.status_code == 201


def test_contact_without_email_still_matches_on_name_only(client):
    company_id = _create_company(client)
    client.post(f"/api/companies/{company_id}/contacts", json={"name": "Jane Doe"})

    # No email on either side - name alone must still catch the duplicate.
    assert (
        client.post(f"/api/companies/{company_id}/contacts", json={"name": "Jane Doe"}).status_code
        == 409
    )


def test_duplicate_contact_flagged_when_names_match_but_emails_differ(client):
    company_id = _create_company(client)
    first = client.post(
        f"/api/companies/{company_id}/contacts",
        json={"name": "Jane Doe", "email": "jane@acme.example.com"},
    )

    # Email is checked first, but a miss there falls through to the name
    # check rather than passing - so two same-named people at one company
    # are still flagged, and the caller decides via "add anyway".
    response = client.post(
        f"/api/companies/{company_id}/contacts",
        json={"name": "Jane Doe", "email": "j.doe@acme.example.com"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["existing_contact_id"] == first.json()["id"]

    forced = client.post(
        f"/api/companies/{company_id}/contacts?force=true",
        json={"name": "Jane Doe", "email": "j.doe@acme.example.com"},
    )
    assert forced.status_code == 201
    assert len(client.get(f"/api/companies/{company_id}").json()["contacts"]) == 2
