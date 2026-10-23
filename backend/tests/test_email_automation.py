"""Email automation: drafts, manual-approval sending, reply sync and
classification, conversation outcomes, follow-ups, meetings, metrics,
OAuth/token handling and Gmail parsing.

No test talks to Google: a FakeProvider stands in for Gmail through the
`get_provider_lookup` dependency, and Gmail's own parsing is tested on
recorded-format payloads.
"""

import base64
from datetime import date, datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet

from app import ai, models
from app.config import settings
from app.database import get_db
from app.mail import classify, crypto, service, states, templates
from app.mail.providers import gmail
from app.mail.providers.base import (
    EmailProvider,
    ProviderAuthError,
    ProviderError,
    SentMessage,
    ThreadMessage,
    TokenSet,
)
from app.main import app
from app.models import LeadStatus
from app.routers.emails import get_provider_lookup

NOW = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)


class FakeProvider(EmailProvider):
    key = "gmail"
    label = "Gmail"

    def __init__(self):
        self.sent = []
        self.threads = {}
        self.fail_send = None
        self.refreshes = 0
        self.revoked = []
        self.exchanged = []

    def is_configured(self):
        return True

    def setup_hint(self):
        return "fake"

    def authorization_url(self, state):
        return f"https://accounts.example/auth?state={state}"

    def exchange_code(self, code):
        self.exchanged.append(code)
        return TokenSet("access-1", "refresh-1", datetime.now(timezone.utc) + timedelta(hours=1), "scopes", "ngo@example.org")

    def refresh_access_token(self, refresh_token):
        self.refreshes += 1
        return TokenSet(f"access-r{self.refreshes}", None, datetime.now(timezone.utc) + timedelta(hours=1))

    def send(self, access_token, message):
        if self.fail_send:
            raise self.fail_send
        self.sent.append((access_token, message))
        n = len(self.sent)
        thread_id = message.provider_thread_id or f"t{n}"
        self.threads.setdefault(thread_id, [])
        self.threads[thread_id].append(
            ThreadMessage(f"m{n}", "ngo@example.org", "NGO", message.to_email, message.subject, message.body,
                          datetime.now(timezone.utc), f"<m{n}@example.org>")
        )
        return SentMessage(f"m{n}", thread_id, f"<m{n}@example.org>")

    def thread_messages(self, access_token, provider_thread_id):
        return list(self.threads.get(provider_thread_id, []))

    def revoke(self, token):
        self.revoked.append(token)


@pytest.fixture()
def fake(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(settings, "token_encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "app_access_token", "")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setattr(settings, "max_emails_per_hour", 30)
    app.dependency_overrides[get_provider_lookup] = lambda: (lambda key: provider)
    yield provider
    app.dependency_overrides.pop(get_provider_lookup, None)


def db_session():
    return next(app.dependency_overrides[get_db]())


def setup_company(client, **overrides):
    payload = {"name": "Acme Industries", "website": "https://acme.example.com", "csr_focus": "Education"}
    payload.update(overrides)
    company = client.post("/api/companies", json=payload).json()
    priya = client.post(
        f"/api/companies/{company['id']}/contacts",
        json={"name": "Priya Sharma", "designation": "Head - CSR", "email": "priya@acme.example.com"},
    ).json()
    rahul = client.post(
        f"/api/companies/{company['id']}/contacts",
        json={"name": "Rahul Verma", "designation": "HR Director", "email": "rahul@acme.example.com"},
    ).json()
    return company, priya, rahul


def connect(client, fake):
    state = client.post("/api/email/oauth/gmail/start").json()["authorization_url"].split("state=")[1]
    response = client.get("/api/email/oauth/gmail/callback", params={"code": "c1", "state": state}, follow_redirects=False)
    assert response.status_code == 303 and "email=connected" in response.headers["location"]


def draft(client, company, contact, email_type="first_outreach"):
    response = client.post(
        "/api/emails/generate",
        json={"company_id": company["id"], "contact_id": contact["id"], "email_type": email_type},
    )
    assert response.status_code == 201, response.text
    return response.json()


def send(client, email, **changes):
    body = {"confirm": True, "to_email": email["to_email"], "subject": email["subject"], "body": email["body"], **changes}
    return client.post(f"/api/emails/{email['id']}/send", json=body)


def timeline(client, company_id):
    return [a["event_type"] for a in client.get(f"/api/companies/{company_id}").json()["activity_logs"]]


# ----------------------------------------------------------------------------
# Pure helpers
# ----------------------------------------------------------------------------
def test_template_rendering_and_fallbacks():
    context = templates.build_context(
        contact_name="Priya Sharma", contact_designation=None, company_name="Acme", csr_focus="Education, Health",
        ngo_name="Hope", ngo_work_area="education", sender_name="Asha", signature=None,
    )
    text = templates.render("Dear {contact_first_name}, {company_name}/{csr_focus} {unknown}.\n{signature}", context)
    assert text == "Dear Priya, Acme/Education .\nWarm regards,\nAsha\nHope"
    no_contact = templates.build_context(
        contact_name=None, contact_designation=None, company_name="Acme", csr_focus=None, ngo_name="Hope",
        ngo_work_area="x", sender_name=None, signature="-- Asha",
    )
    assert templates.render("Dear {contact_first_name} ({csr_focus}) {signature}", no_contact) == (
        "Dear there (community development) -- Asha"
    )
    assert templates.render("Broken {brace", no_contact) == "Broken {brace"


@pytest.mark.parametrize(
    "reply, classification, intent",
    [
        ("Thanks, but we are not interested at this time.", "negative", "none"),
        ("We have no budget left for this year, regret to inform you.", "negative", "none"),
        ("I am out of the office until Monday.", "neutral", "none"),
        ("Sounds great! Happy to set up a call next Tuesday?", "positive", "meeting_requested"),
        ("We'd be glad to review a proposal with the budget.", "positive", "proposal_requested"),
        ("Could you share more details about your programme?", "needs_follow_up", "none"),
        ("Noted.", "neutral", "none"),
    ],
)
def test_keyword_classifier(reply, classification, intent):
    result = classify.keyword_classify(reply + "\n\nOn Mon, 12 Oct 2026, NGO wrote:\n> We are very interested")
    assert (result["classification"], result["intent"], result["method"]) == (classification, intent, "keywords")
    assert 0 < result["confidence"] <= 0.5


def test_ai_classification_used_when_configured(monkeypatch):
    monkeypatch.setattr(ai, "is_configured", lambda: True)
    monkeypatch.setattr(
        ai, "classify_reply",
        lambda **kw: {"classification": "positive", "confidence": 0.92, "reasoning": "Asks to meet.", "intent": "meeting_requested"},
    )
    result = classify.classify("Let's meet", company_name="Acme", ngo_name="Hope", our_email=None)
    assert result["method"] == "ai" and result["confidence"] == 0.92


def test_lead_status_only_moves_forward():
    assert states.lead_status_for("awaiting_reply", LeadStatus.NEW) == LeadStatus.CONTACTED
    assert states.lead_status_for("meeting_scheduled", LeadStatus.CONTACTED) == LeadStatus.MEETING
    assert states.lead_status_for("positive", LeadStatus.MEETING) is None  # never backwards
    assert states.lead_status_for("partnership_confirmed", LeadStatus.NOT_INTERESTED) is None
    assert states.lead_status_for("negative", LeadStatus.CONTACTED) is None  # staff decide, not the app
    assert states.thread_status_for_reply("positive", "meeting_requested") == "meeting_requested"
    assert states.thread_status_for_reply("negative", "meeting_requested") == "negative"


def test_token_encryption_and_signed_state(monkeypatch):
    monkeypatch.setattr(settings, "token_encryption_key", "")
    assert not crypto.is_configured()
    with pytest.raises(crypto.EncryptionNotConfigured):
        crypto.encrypt("x")
    monkeypatch.setattr(settings, "token_encryption_key", Fernet.generate_key().decode())
    secret = crypto.encrypt("refresh-token")
    assert secret != "refresh-token" and crypto.decrypt(secret) == "refresh-token"
    state = crypto.make_state("gmail")
    assert crypto.verify_state(state, "gmail")
    assert not crypto.verify_state(state, "outlook")
    assert not crypto.verify_state(state[:-2] + "00", "gmail")
    monkeypatch.setattr(crypto.time, "time", lambda: 10**10)
    assert not crypto.verify_state(state, "gmail")  # expired
    monkeypatch.setattr(settings, "token_encryption_key", Fernet.generate_key().decode())
    assert crypto.decrypt(secret) is None  # key changed: unreadable, not an exception


# ----------------------------------------------------------------------------
# Gmail parsing (no network)
# ----------------------------------------------------------------------------
def _b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def test_gmail_parse_thread_bodies_bounces_and_quotes():
    data = {
        "messages": [
            {
                "id": "a1", "internalDate": "1760522400000",
                "payload": {
                    "mimeType": "multipart/alternative",
                    "headers": [
                        {"name": "From", "value": "Priya Sharma <Priya@Acme.example.com>"},
                        {"name": "To", "value": "ngo@example.org"},
                        {"name": "Subject", "value": "Re: Partnership"},
                        {"name": "Message-ID", "value": "<r1@acme>"},
                    ],
                    "parts": [
                        {"mimeType": "text/plain", "body": {"data": _b64("Yes, let's talk.\n\nOn Mon, 12 Oct 2026, NGO wrote:\n> Hello")}},
                        {"mimeType": "text/html", "body": {"data": _b64("<p>Yes</p>")}},
                    ],
                },
            },
            {
                "id": "b1", "internalDate": "1760522500000",
                "payload": {
                    "mimeType": "text/html",
                    "headers": [{"name": "From", "value": "Mail Delivery Subsystem <mailer-daemon@googlemail.com>"}],
                    "body": {"data": _b64("<div>Address not found<br>Your message wasn't delivered</div>")},
                },
            },
        ]
    }
    reply, bounce = gmail.parse_thread(data)
    assert reply.from_email == "priya@acme.example.com" and reply.from_name == "Priya Sharma"
    assert reply.rfc822_message_id == "<r1@acme>" and not reply.is_bounce
    assert gmail.strip_quoted(reply.body) == "Yes, let's talk."
    assert bounce.is_bounce and "Address not found" in bounce.body


def test_gmail_mime_threads_replies():
    from app.mail.providers.base import OutgoingMessage

    mime = gmail.build_mime(OutgoingMessage("ngo@example.org", "Asha", "priya@acme.com", "Priya", "Re: Hi", "Body", "t1", "<m1@x>"))
    assert mime["In-Reply-To"] == "<m1@x>" and mime["References"] == "<m1@x>"
    assert "Asha" in mime["From"] and mime["Message-ID"].endswith("@example.org>")


def test_gmail_authorization_url_requests_offline_send_and_read(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "client-123")
    url = gmail.GmailProvider().authorization_url("STATE")
    for part in ("client_id=client-123", "access_type=offline", "gmail.send", "gmail.readonly", "state=STATE"):
        assert part in url


# ----------------------------------------------------------------------------
# Drafts
# ----------------------------------------------------------------------------
def test_generate_draft_from_template_with_signature_and_timeline(client, fake):
    company, priya, _ = setup_company(client)
    client.patch("/api/email/settings", json={"sender_name": "Asha Rao", "signature": "Asha Rao\nA Ray of Hope"})
    email = draft(client, company, priya)
    assert email["status"] == "draft" and email["generated_by"] == "template"
    assert email["to_email"] == "priya@acme.example.com"
    assert email["subject"] == "Partnering with Acme Industries on Education"
    assert email["body"].startswith("Dear Priya,") and email["body"].endswith("Asha Rao\nA Ray of Hope")
    assert "email_generated" in timeline(client, company["id"])
    contact = client.get(f"/api/contacts/{priya['id']}").json()
    assert "email_generated" in [a["event_type"] for a in contact["activity_logs"]]
    assert client.get("/api/email-threads", params={"company_id": company["id"]}).json()[0]["status"] == "draft"


def test_generate_draft_with_ai_appends_signature(client, fake, monkeypatch):
    company, priya, _ = setup_company(client)
    client.patch("/api/email/settings", json={"signature": "-- Asha"})
    monkeypatch.setattr(ai, "is_configured", lambda: True)
    monkeypatch.setattr(ai, "generate_email", lambda **kw: {"subject": "AI subject", "body": "AI body"})
    email = draft(client, company, priya)
    assert (email["generated_by"], email["subject"], email["body"]) == ("ai", "AI subject", "AI body\n\n-- Asha")


def test_edit_duplicate_and_delete_drafts(client, fake):
    company, priya, rahul = setup_company(client)
    email = draft(client, company, priya)
    edited = client.patch(f"/api/emails/{email['id']}", json={"subject": "Edited", "contact_id": rahul["id"]}).json()
    assert edited["subject"] == "Edited" and edited["to_email"] == "rahul@acme.example.com"
    assert "draft_saved" in timeline(client, company["id"])

    copy = client.post(f"/api/emails/{email['id']}/duplicate", json={"contact_id": priya["id"]}).json()
    assert copy["thread_id"] != email["thread_id"] and copy["duplicated_from_id"] == email["id"]
    assert copy["subject"] == "Edited" and copy["to_email"] == "priya@acme.example.com"

    assert client.delete(f"/api/emails/{email['id']}").status_code == 204
    assert client.get(f"/api/emails/{email['id']}").status_code == 404
    other = setup_company(client, name="Other Co", website="https://other.example.com")[1]
    assert client.post(f"/api/emails/{copy['id']}/duplicate", json={"contact_id": other["id"]}).status_code == 400
    assert client.post("/api/emails/generate", json={"company_id": company["id"], "email_type": "spam"}).status_code == 400


# ----------------------------------------------------------------------------
# Sending
# ----------------------------------------------------------------------------
def test_send_needs_connection_confirmation_and_a_saved_contact(client, fake):
    company, priya, _ = setup_company(client)
    email = draft(client, company, priya)
    response = send(client, email)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "not_connected"
    connect(client, fake)
    assert send(client, email, confirm=False).status_code == 400
    stranger = send(client, email, to_email="someone@gmail.com")
    assert stranger.status_code == 400 and "saved for this company" in stranger.json()["detail"]
    assert fake.sent == []


def test_send_uses_exactly_the_approved_content(client, fake):
    company, priya, _ = setup_company(client)
    connect(client, fake)
    email = draft(client, company, priya)
    response = send(client, email, subject="Approved subject", body="Approved body", followup_days=7)
    assert response.status_code == 200, response.text
    sent = response.json()
    assert sent["status"] == "sent" and sent["approved_at"] and sent["sent_at"]
    assert sent["subject"] == "Approved subject" and sent["from_email"] == "ngo@example.org"
    token, message = fake.sent[0]
    assert (token, message.subject, message.body, message.to_email) == ("access-1", "Approved subject", "Approved body", "priya@acme.example.com")

    detail = client.get(f"/api/companies/{company['id']}").json()
    assert detail["status"] == "Contacted" and detail["last_contacted_date"] == date.today().isoformat()
    assert detail["follow_up_date"] == (date.today() + timedelta(days=7)).isoformat()
    events = timeline(client, company["id"])
    assert {"email_sent", "status_changed", "followup_scheduled"} <= set(events)
    thread = client.get(f"/api/email-threads/{sent['thread_id']}").json()
    assert thread["status"] == "awaiting_reply" and thread["status_label"] == "No Reply"
    assert [e["event_type"] for e in thread["events"]][:3] == ["generated", "sent", "status_changed"]
    assert send(client, sent).status_code == 409  # can't send twice
    assert client.patch(f"/api/emails/{sent['id']}", json={"subject": "x"}).status_code == 409
    assert client.delete(f"/api/emails/{sent['id']}").status_code == 409


def test_failed_send_is_recorded_and_retryable(client, fake):
    company, priya, _ = setup_company(client)
    connect(client, fake)
    email = draft(client, company, priya)
    fake.fail_send = ProviderError("Gmail error 500: backend error")
    response = send(client, email)
    assert response.status_code == 502
    failed = client.get(f"/api/emails/{email['id']}").json()
    assert failed["status"] == "failed" and "backend error" in failed["error"]
    assert "email_failed" in timeline(client, company["id"])
    fake.fail_send = None
    assert send(client, failed).json()["status"] == "sent"


def test_expired_access_token_is_refreshed_and_revoked_grant_needs_reconnect(client, fake):
    company, priya, _ = setup_company(client)
    connect(client, fake)
    db = db_session()
    account = db.query(models.EmailAccount).one()
    assert account.encrypted_refresh_token != "refresh-1"  # stored encrypted
    account.access_token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.commit()
    send(client, draft(client, company, priya))
    assert fake.refreshes == 1 and fake.sent[0][0] == "access-r1"

    account.access_token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.commit()
    fake.refresh_access_token = lambda token: (_ for _ in ()).throw(ProviderAuthError("revoked"))
    response = send(client, draft(client, company, priya))
    assert response.status_code == 502
    status = client.get("/api/email/account").json()["account"]
    assert status["status"] == "error" and "revoked" in status["last_error"]


def test_hourly_send_cap(client, fake, monkeypatch):
    company, priya, rahul = setup_company(client)
    connect(client, fake)
    monkeypatch.setattr(settings, "max_emails_per_hour", 1)
    assert send(client, draft(client, company, priya)).status_code == 200
    assert send(client, draft(client, company, rahul)).status_code == 429


def test_access_token_guards_mailbox_actions(client, fake, monkeypatch):
    company, priya, _ = setup_company(client)
    connect(client, fake)
    monkeypatch.setattr(settings, "app_access_token", "s3cret")
    email = draft(client, company, priya)  # drafting isn't guarded
    blocked = send(client, email)
    assert blocked.status_code == 401 and blocked.json()["detail"]["code"] == "access_token_required"
    assert client.post("/api/email/sync").status_code == 401
    assert client.delete("/api/email/account").status_code == 401
    assert client.post("/api/email/oauth/gmail/start").status_code == 401
    body = {"confirm": True, "to_email": email["to_email"], "subject": email["subject"], "body": email["body"]}
    ok = client.post(f"/api/emails/{email['id']}/send", json=body, headers={"X-App-Access-Token": "s3cret"})
    assert ok.status_code == 200


# ----------------------------------------------------------------------------
# Replies
# ----------------------------------------------------------------------------
def _reply(fake, thread_key, text, sender="priya@acme.example.com", msg_id="r1", bounce=False):
    fake.threads[thread_key].append(
        ThreadMessage(msg_id, sender, "Priya Sharma", "ngo@example.org", "Re: x", text,
                      datetime.now(timezone.utc), f"<{msg_id}@acme>", is_bounce=bounce)
    )


def test_sync_records_reply_classifies_and_moves_pipeline(client, fake):
    company, priya, _ = setup_company(client)
    connect(client, fake)
    sent = send(client, draft(client, company, priya), followup_days=7).json()
    _reply(fake, "t1", "Sounds great - happy to set up a call next week?")

    result = client.post("/api/email/sync").json()
    assert (result["threads_checked"], result["new_replies"]) == (1, 1)
    thread = client.get(f"/api/email-threads/{sent['thread_id']}").json()
    reply = thread["emails"][-1]
    assert reply["direction"] == "inbound" and reply["status"] == "received"
    assert reply["classification"]["classification"] == "positive"
    assert reply["classification"]["intent"] == "meeting_requested"
    assert reply["classification"]["method"] == "keywords" and reply["classification"]["reasoning"]
    assert thread["status"] == "meeting_requested"
    assert thread["followups"][0]["status"] == "cancelled" and thread["followups"][0]["cancel_reason"] == "Reply received"
    assert client.get(f"/api/companies/{company['id']}").json()["status"] == "Meeting"
    assert "reply_received" in timeline(client, company["id"])

    again = client.post("/api/email/sync").json()
    assert again["new_replies"] == 0  # idempotent


def test_manual_override_keeps_history(client, fake):
    company, priya, _ = setup_company(client)
    connect(client, fake)
    sent = send(client, draft(client, company, priya)).json()
    _reply(fake, "t1", "Noted.")
    client.post("/api/email/sync")
    reply = client.get(f"/api/email-threads/{sent['thread_id']}").json()["emails"][-1]
    assert reply["classification"]["classification"] == "neutral"

    override = client.post(f"/api/emails/{reply['id']}/classification", json={"classification": "needs_follow_up"})
    assert override.status_code == 200 and override.json()["method"] == "manual"
    updated = client.get(f"/api/emails/{reply['id']}").json()
    assert [c["method"] for c in updated["classification_history"]] == ["keywords", "manual"]
    assert updated["thread_status"] == "needs_follow_up"
    assert client.post(f"/api/emails/{reply['id']}/classification", json={"classification": "maybe"}).status_code == 400
    assert client.post(f"/api/emails/{sent['id']}/classification", json={"classification": "positive"}).status_code == 400


def test_sync_handles_bounces_and_mail_sent_from_gmail(client, fake):
    company, priya, _ = setup_company(client)
    connect(client, fake)
    sent = send(client, draft(client, company, priya)).json()
    _reply(fake, "t1", "Address not found", sender="mailer-daemon@googlemail.com", msg_id="b1", bounce=True)
    _reply(fake, "t1", "Sending the brochure we discussed.", sender="ngo@example.org", msg_id="o1")
    result = client.post("/api/email/sync").json()
    assert (result["bounces"], result["new_replies"]) == (1, 0)
    emails = client.get(f"/api/email-threads/{sent['thread_id']}").json()["emails"]
    assert emails[0]["status"] == "failed" and emails[0]["error"].startswith("Bounced")
    assert any(e["generated_by"] == "gmail" and e["status"] == "sent" for e in emails)
    assert client.post("/api/email/sync").json()["bounces"] == 0


def test_manual_thread_status_drives_lead_status_and_timeline(client, fake):
    company, priya, _ = setup_company(client)
    connect(client, fake)
    sent = send(client, draft(client, company, priya)).json()
    thread_id = sent["thread_id"]
    client.patch(f"/api/email-threads/{thread_id}", json={"status": "proposal_sent"})
    assert client.get(f"/api/companies/{company['id']}").json()["status"] == "Proposal Sent"
    assert "proposal_sent" in timeline(client, company["id"])
    client.patch(f"/api/email-threads/{thread_id}", json={"status": "awaiting_reply"})
    assert client.get(f"/api/companies/{company['id']}").json()["status"] == "Proposal Sent"  # never backwards
    assert client.patch(f"/api/email-threads/{thread_id}", json={"status": "bogus"}).status_code == 400


# ----------------------------------------------------------------------------
# Follow-ups & meetings
# ----------------------------------------------------------------------------
def test_due_followup_becomes_an_in_thread_draft_never_sent(client, fake):
    company, priya, _ = setup_company(client)
    connect(client, fake)
    sent = send(client, draft(client, company, priya), followup_days=3).json()
    assert client.post("/api/followups/generate-due").json() == []  # not due yet

    db = db_session()
    drafted = service.generate_due_followups(db, today=date.today() + timedelta(days=3))
    assert len(drafted) == 1 and len(fake.sent) == 1  # drafted, not sent
    followup = client.get("/api/followups", params={"status": "drafted"}).json()[0]
    follow_email = client.get(f"/api/emails/{followup['draft_email_id']}").json()
    assert follow_email["status"] == "draft" and follow_email["thread_id"] == sent["thread_id"]
    assert follow_email["subject"].startswith("Re: ") and follow_email["email_type"] == "follow_up"
    assert "followup_drafted" in timeline(client, company["id"])

    send(client, follow_email)
    # Sent as a reply in the same Gmail conversation.
    assert fake.sent[1][1].in_reply_to == "<m1@example.org>" and fake.sent[1][1].provider_thread_id == "t1"
    assert client.get("/api/followups", params={"status": "sent"}).json()[0]["id"] == followup["id"]


def test_schedule_and_cancel_followups(client, fake):
    company, priya, _ = setup_company(client)
    connect(client, fake)
    sent = send(client, draft(client, company, priya)).json()
    created = client.post("/api/followups", json={"thread_id": sent["thread_id"], "days": 14}).json()
    assert created["due_date"] == (date.today() + timedelta(days=14)).isoformat() and created["interval_days"] == 14
    on_date = client.post("/api/followups", json={"company_id": company["id"], "contact_id": priya["id"],
                                                  "due_date": (date.today() + timedelta(days=30)).isoformat()})
    assert on_date.status_code == 201
    assert client.post("/api/followups", json={"company_id": company["id"], "due_date": "2020-01-01"}).status_code == 400
    assert client.post("/api/followups", json={"company_id": company["id"]}).status_code == 400
    cancelled = client.patch(f"/api/followups/{created['id']}", json={"status": "cancelled"}).json()
    assert cancelled["status"] == "cancelled"
    assert client.patch(f"/api/followups/{created['id']}", json={"status": "sent"}).status_code == 400
    assert len(client.get("/api/followups", params={"status": "open"}).json()) == 1


def test_followups_from_a_draft_only_conversation_need_a_sent_email(client, fake):
    company, priya, _ = setup_company(client)
    email = draft(client, company, priya)
    response = client.post(f"/api/email-threads/{email['thread_id']}/followup-draft")
    assert response.status_code == 409


def test_meeting_scheduling_updates_conversation_and_lead(client, fake):
    company, priya, _ = setup_company(client)
    connect(client, fake)
    sent = send(client, draft(client, company, priya)).json()
    meeting = client.post("/api/meetings", json={
        "company_id": company["id"], "thread_id": sent["thread_id"], "title": "Intro call",
        "scheduled_at": "2026-11-02T10:30:00Z", "location": "Google Meet",
    })
    assert meeting.status_code == 201 and meeting.json()["contact_id"] == priya["id"]
    assert client.get(f"/api/email-threads/{sent['thread_id']}").json()["status"] == "meeting_scheduled"
    assert client.get(f"/api/companies/{company['id']}").json()["status"] == "Meeting"
    assert "meeting_scheduled" in timeline(client, company["id"])
    updated = client.patch(f"/api/meetings/{meeting.json()['id']}", json={"status": "completed"}).json()
    assert updated["status"] == "completed"
    assert client.post("/api/meetings", json={"company_id": company["id"], "title": "x", "status": "maybe"}).status_code == 400


# ----------------------------------------------------------------------------
# Dashboard
# ----------------------------------------------------------------------------
def test_dashboard_outreach_metrics_and_pipeline(client, fake):
    company, priya, rahul = setup_company(client)
    other, other_contact, _ = setup_company(client, name="Bharat Pharma", website="https://bharat.example.com")
    setup_company(client, name="New Co", website="https://new.example.com")
    connect(client, fake)
    first = send(client, draft(client, company, priya), followup_days=7).json()
    send(client, draft(client, other, other_contact))
    draft(client, company, rahul)  # generated, never sent
    _reply(fake, "t1", "We are not interested, thank you.")
    client.post("/api/email/sync")
    client.patch(f"/api/email-threads/{first['thread_id']}", json={"status": "partnership_confirmed"})

    data = client.get("/api/dashboard").json()
    metrics = data["outreach"]
    assert metrics["total_companies"] == 3 and metrics["contacts"] == 6
    assert (metrics["emails_generated"], metrics["emails_sent"], metrics["replies_received"]) == (3, 2, 1)
    assert (metrics["positive_replies"], metrics["negative_replies"]) == (0, 1)
    assert metrics["partnerships"] == 1 and metrics["reply_rate"] == 50.0
    assert metrics["conversion_rate"] == 50.0 and metrics["positive_reply_rate"] == 0.0
    assert metrics["overdue_followups"] == 0
    pipeline = {p["stage"]: p["count"] for p in data["pipeline"]}
    assert pipeline == {"New": 1, "Contacted": 1, "Replied": 0, "Meeting": 0, "Proposal": 0, "Won": 1, "Lost": 0}
    assert "kpis" in data and "follow_ups" in data  # existing fields kept


# ----------------------------------------------------------------------------
# OAuth & settings
# ----------------------------------------------------------------------------
def test_oauth_start_requires_server_setup(client, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "")
    monkeypatch.setattr(settings, "app_access_token", "")
    response = client.post("/api/email/oauth/gmail/start")
    assert response.status_code == 409 and "GOOGLE_CLIENT_ID" in response.json()["detail"]
    monkeypatch.setattr(settings, "google_client_id", "id")
    monkeypatch.setattr(settings, "google_client_secret", "secret")
    monkeypatch.setattr(settings, "token_encryption_key", "")
    response = client.post("/api/email/oauth/gmail/start")
    assert response.status_code == 409 and "TOKEN_ENCRYPTION_KEY" in response.json()["detail"]
    assert client.post("/api/email/oauth/outlook/start").status_code == 404


def test_oauth_callback_rejects_forged_state_and_connects_with_valid_one(client, fake):
    bad = client.get("/api/email/oauth/gmail/callback", params={"code": "c", "state": "forged.sig"}, follow_redirects=False)
    assert bad.status_code == 303 and "email=error" in bad.headers["location"]
    denied = client.get("/api/email/oauth/gmail/callback", params={"error": "access_denied"}, follow_redirects=False)
    assert "email=error" in denied.headers["location"]
    assert fake.exchanged == []

    connect(client, fake)
    status = client.get("/api/email/account").json()
    assert status["account"]["email_address"] == "ngo@example.org" and status["account"]["status"] == "connected"
    assert "token" not in str(status["account"]).lower().replace("access_token_required", "")
    assert status["encryption_configured"] and status["providers"][0]["capabilities"]["opens"] is False

    assert client.delete("/api/email/account").status_code == 204
    assert fake.revoked == ["refresh-1"]
    assert client.get("/api/email/account").json()["account"] is None


def test_settings_and_templates(client):
    defaults = client.get("/api/email/settings").json()
    assert defaults["followup_intervals"] == [3, 7, 14, 30] and defaults["default_followup_days"] == 7
    updated = client.patch("/api/email/settings", json={"followup_intervals": [30, 5, 5], "sender_name": "Asha"}).json()
    assert updated["followup_intervals"] == [5, 30] and updated["sender_name"] == "Asha"
    assert client.patch("/api/email/settings", json={"followup_intervals": [0]}).status_code == 422

    templates_list = client.get("/api/email/templates").json()
    assert {t["email_type"] for t in templates_list} == set(states.EMAIL_TYPES)
    first = templates_list[0]
    assert client.patch(f"/api/email/templates/{first['id']}", json={"subject": "Hello {company_name}"}).json()["subject"] == "Hello {company_name}"
    reset = client.post("/api/email/templates/reset").json()
    assert reset[0]["subject"] != "Hello {company_name}"
    meta = client.get("/api/email/meta").json()
    assert meta["thread_statuses"]["awaiting_reply"] == "No Reply"


# ----------------------------------------------------------------------------
# Existing behaviour kept
# ----------------------------------------------------------------------------
def test_deleting_company_or_contact_with_email_history(client, fake):
    company, priya, _ = setup_company(client)
    connect(client, fake)
    sent = send(client, draft(client, company, priya), followup_days=3).json()
    assert client.delete(f"/api/contacts/{priya['id']}").status_code == 204
    kept = client.get(f"/api/emails/{sent['id']}").json()
    assert kept["status"] == "sent" and kept["contact_id"] is None

    assert client.delete(f"/api/companies/{company['id']}").status_code == 204
    db = db_session()
    assert db.query(models.Email).count() == 0 and db.query(models.EmailThread).count() == 0
    assert db.query(models.FollowUp).count() == 0


def test_legacy_copy_only_email_generator_unchanged(client, fake):
    company, priya, _ = setup_company(client)
    response = client.post(f"/api/companies/{company['id']}/generate-email", json={"email_type": "first_outreach"})
    assert response.json() == {"configured": False, "subject": None, "body": None}
    assert client.get("/api/emails").json() == []  # no draft created by the old endpoint
