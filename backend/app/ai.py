"""Google Gemini integration for AI-assisted content (Phase 3).

Every public function here degrades gracefully when GEMINI_API_KEY
isn't set - callers check `is_configured()` first and show a "not
configured" state rather than erroring, the same pattern as
Hunter/Apollo in app/enrichment.py (Phase 2).

Everything produced here is a DRAFT for NGO staff to review and edit -
nothing in this module sends an email or takes any outreach action on
its own.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import requests

from .config import settings

logger = logging.getLogger("ai")

REQUEST_TIMEOUT_SECONDS = 20
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

EMAIL_TYPE_LABELS = {
    "first_outreach": "a first outreach / introduction email",
    "follow_up": "a polite follow-up email after no response yet",
    "meeting_request": "an email requesting a meeting",
    "thank_you": "a thank-you email after a positive interaction",
}

EMAIL_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "body": {"type": "string"},
    },
    "required": ["subject", "body"],
}


def is_configured() -> bool:
    return bool(settings.gemini_api_key)


def _call_gemini(prompt: str, *, json_schema: Optional[dict] = None) -> Optional[str]:
    """Low-level Gemini call. Returns the raw text response, or None on any failure."""
    if not settings.gemini_api_key:
        return None

    body: dict = {"contents": [{"parts": [{"text": prompt}]}]}
    if json_schema is not None:
        body["generationConfig"] = {
            "responseMimeType": "application/json",
            "responseSchema": json_schema,
        }

    url = GEMINI_ENDPOINT.format(model=settings.gemini_model)
    try:
        response = requests.post(
            url, params={"key": settings.gemini_api_key}, json=body, timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Gemini request failed: %s", exc)
        return None

    try:
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, ValueError) as exc:
        logger.warning("Unexpected Gemini response shape: %s", exc)
        return None


def explain_lead_score(company_name: str, factors: dict, score: int, priority: str) -> Optional[str]:
    prompt = (
        "You are helping an NGO's outreach team understand a CSR lead score.\n"
        f"Company: {company_name}\n"
        f"Total score: {score}/100 ({priority} priority)\n"
        f"Score breakdown (points out of a max per factor): {factors}\n\n"
        "Write 2-3 short bullet points (plain text, one per line, no markdown headers) "
        "explaining why this company scored this way, in plain language for non-technical "
        "NGO staff."
    )
    return _call_gemini(prompt)


def generate_email(
    *,
    ngo_name: str,
    ngo_work_area: str,
    company_name: str,
    contact_name: Optional[str],
    contact_designation: Optional[str],
    csr_focus: Optional[str],
    email_type: str,
    context: Optional[str] = None,
    sender_name: Optional[str] = None,
) -> Optional[dict]:
    kind = EMAIL_TYPE_LABELS.get(email_type, email_type)
    prompt = (
        f"Write {kind} from {ngo_name}, an NGO focused on {ngo_work_area}, "
        f"to {contact_name or 'the CSR contact'} ({contact_designation or 'CSR contact'}) "
        f"at {company_name}. {company_name}'s CSR focus area is "
        f"{csr_focus or 'not specified'}. Keep it concise, professional, and warm. This is "
        "a DRAFT the NGO staff will review and edit before sending - do not include "
        "placeholder brackets like [Name], write natural text throughout."
    )
    if sender_name:
        prompt += f" Sign it from {sender_name}. Do not add a signature block - one is appended separately."
    if context:
        prompt += f"\n\nThe conversation so far (most recent last):\n{context[:4000]}"
    raw = _call_gemini(prompt, json_schema=EMAIL_JSON_SCHEMA)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return {"subject": data["subject"], "body": data["body"]}
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning("Could not parse Gemini email JSON (%s): %r", exc, raw)
        return None


REPLY_CLASSIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "classification": {"type": "string", "enum": ["positive", "negative", "neutral", "needs_follow_up"]},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
        "intent": {"type": "string", "enum": ["meeting_requested", "proposal_requested", "none"]},
    },
    "required": ["classification", "confidence", "reasoning", "intent"],
}


def classify_reply(*, reply_text: str, company_name: str, ngo_name: str, our_email: Optional[str]) -> Optional[dict]:
    """Classify a company's reply to our CSR outreach. Returns
    {classification, confidence (0-1), reasoning, intent} or None.
    """
    prompt = (
        f"{ngo_name}, an NGO, emailed {company_name} about a possible CSR partnership. "
        "Classify the company's reply below.\n\n"
        "classification:\n"
        "- positive: interested, wants to proceed, asks for details, a meeting or a proposal\n"
        "- negative: declines, not interested, no budget, unsubscribe / do not contact\n"
        "- neutral: acknowledgement, out-of-office, forwarded internally, no clear stance\n"
        "- needs_follow_up: asks the NGO a question or for information before deciding, or says "
        "to get back later\n"
        "intent: meeting_requested if they propose or agree to a call/meeting; proposal_requested if "
        "they ask for a proposal/deck/budget; otherwise none.\n"
        "confidence: 0 to 1. reasoning: one or two plain sentences citing the reply.\n\n"
        + (f"Our original email:\n{our_email[:1500]}\n\n" if our_email else "")
        + f"Their reply:\n{reply_text[:4000]}"
    )
    raw = _call_gemini(prompt, json_schema=REPLY_CLASSIFICATION_SCHEMA)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        confidence = max(0.0, min(1.0, float(data["confidence"])))
        return {
            "classification": data["classification"],
            "confidence": confidence,
            "reasoning": str(data["reasoning"]).strip(),
            "intent": data.get("intent") or "none",
        }
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning("Could not parse Gemini classification JSON (%s): %r", exc, raw)
        return None


def generate_company_summary(
    *,
    company_name: str,
    industry: Optional[str],
    city: Optional[str],
    state: Optional[str],
    csr_focus: Optional[str],
    csr_spending: Optional[float],
    ngo_name: str,
    ngo_work_area: str,
) -> Optional[str]:
    location = " ".join(part for part in [city, state] if part) or "an unspecified location"
    spending_clause = (
        f" with reported CSR spending around Rs. {csr_spending:,.0f}." if csr_spending else "."
    )
    prompt = (
        f"Write a short (4-6 sentence) briefing for an NGO outreach team about {company_name}, "
        f"a company in the {industry or 'unspecified'} industry based in {location}. "
        f"Its CSR focus area is {csr_focus or 'not publicly specified'}{spending_clause} "
        f"Cover: a brief business overview, their apparent CSR initiatives/focus, how well "
        f"this fits {ngo_name} (which works on {ngo_work_area}), and 2-3 key talking points "
        "for an initial conversation. Plain text, no markdown headers."
    )
    return _call_gemini(prompt)


def generate_meeting_brief(
    *,
    company_name: str,
    industry: Optional[str],
    city: Optional[str],
    state: Optional[str],
    csr_focus: Optional[str],
    notes: list[str],
) -> Optional[str]:
    location = " ".join(part for part in [city, state] if part) or "an unspecified location"
    notes_text = "\n".join(f"- {note}" for note in notes) if notes else "(no notes recorded yet)"
    prompt = (
        f"Prepare a short meeting brief for an NGO team about to meet with {company_name} "
        f"({industry or 'unspecified industry'}, {location}). Their CSR focus area is "
        f"{csr_focus or 'not publicly specified'}. Past notes on this relationship:\n"
        f"{notes_text}\n\n"
        "Include: company background (2-3 sentences), likely CSR priorities, 3-4 suggested "
        "discussion points, 2-3 questions to ask, and 1-2 collaboration ideas. Plain text, "
        "no markdown headers."
    )
    return _call_gemini(prompt)
