"""Reply classification: Gemini when configured, keyword rules otherwise.

The keyword fallback exists so reply tracking still works without an AI
key. It reports a lower confidence and says it was keyword-based, so staff
know to read the reply themselves.
"""

from __future__ import annotations

import re
from typing import Optional

from .. import ai
from .providers.gmail import strip_quoted

_RULES: list[tuple[str, re.Pattern]] = [
    (
        "negative",
        re.compile(
            r"not (be )?interested|no budget|unable to (support|consider|proceed)|cannot (support|consider)|"
            r"decline|not able to|unsubscribe|remove (me|us) from|do not (contact|email)|not a fit|"
            r"no longer|already (committed|allocated)|regret to",
            re.I,
        ),
    ),
    (
        "neutral",
        re.compile(r"out of (the )?office|on leave|auto.?reply|automatic reply|currently away|vacation", re.I),
    ),
    (
        "positive",
        re.compile(
            r"interested|happy to|glad to|would love|let'?s (meet|connect|talk|discuss)|sounds (good|great)|"
            r"look(ing)? forward|keen to|schedule|set up a (call|meeting)",
            re.I,
        ),
    ),
    (
        "needs_follow_up",
        re.compile(
            r"\?|could you (share|send)|please (share|send)|more (details|information)|get back to you|"
            r"after (the )?(quarter|budget)|next (month|quarter|year)|forward(ed)? (this|your)",
            re.I,
        ),
    ),
]
_MEETING = re.compile(r"\b(meet|meeting|call|zoom|teams|google meet|catch up|schedule|available (on|at))\b", re.I)
_PROPOSAL = re.compile(r"\b(proposal|deck|budget|concept note|share (the )?details of the (project|programme))\b", re.I)


def keyword_classify(text: str) -> dict:
    body = strip_quoted(text) or text
    # Order matters: "not interested" is negative before "interested" is
    # positive, and an eager reply with a question is still positive.
    for label, pattern in _RULES:
        match = pattern.search(body)
        if match:
            classification, reason = label, f'Keyword match: "{match.group(0).strip()}".'
            break
    else:
        classification, reason = "neutral", "No clear signal found in the reply."
    intent = "none"
    if classification in ("positive", "needs_follow_up"):
        if _PROPOSAL.search(body):
            intent = "proposal_requested"
        elif _MEETING.search(body):
            intent = "meeting_requested"
    return {
        "classification": classification,
        "confidence": 0.3 if reason.startswith("No clear") else 0.5,
        "reasoning": reason + " Classified by keyword rules (AI not configured) - please read the reply.",
        "intent": intent,
        "method": "keywords",
    }


def classify(reply_text: str, *, company_name: str, ngo_name: str, our_email: Optional[str]) -> dict:
    text = strip_quoted(reply_text) or reply_text
    if ai.is_configured():
        result = ai.classify_reply(reply_text=text, company_name=company_name, ngo_name=ngo_name, our_email=our_email)
        if result:
            return {**result, "method": "ai"}
    return keyword_classify(text)
