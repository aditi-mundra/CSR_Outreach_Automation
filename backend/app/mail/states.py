"""Every status an email, a conversation (thread) or a follow-up can have,
and how conversation outcomes move a company along its lead pipeline.

Stored as plain strings (see models.py) so adding a state never needs a
database migration.
"""

from __future__ import annotations

from typing import Optional

from ..models import LeadStatus

# Outbound emails: draft -> sent | failed. Inbound replies: received.
EMAIL_STATUSES = ("draft", "sent", "failed", "received")

# Conversation outcome, in rough pipeline order.
THREAD_STATUSES: dict[str, str] = {
    "draft": "Draft",
    "awaiting_reply": "No Reply",
    "replied": "Replied",
    "positive": "Positive Reply",
    "neutral": "Neutral Reply",
    "negative": "Negative Reply",
    "needs_follow_up": "Needs Follow-up",
    "meeting_requested": "Meeting Requested",
    "meeting_scheduled": "Meeting Scheduled",
    "proposal_requested": "Proposal Requested",
    "proposal_sent": "Proposal Sent",
    "partnership_confirmed": "Partnership Confirmed",
    "closed": "Closed",
}

CLASSIFICATIONS: dict[str, str] = {
    "positive": "Positive",
    "negative": "Negative",
    "neutral": "Neutral",
    "needs_follow_up": "Needs Follow-up",
}
INTENTS = ("meeting_requested", "proposal_requested", "none")

FOLLOWUP_STATUSES = ("scheduled", "drafted", "sent", "cancelled")
MEETING_STATUSES = ("requested", "scheduled", "completed", "cancelled")

EMAIL_TYPES: dict[str, str] = {
    "first_outreach": "First Outreach",
    "follow_up": "Follow-up",
    "meeting_request": "Meeting Request",
    "thank_you": "Thank You",
    "proposal": "Proposal",
}

# Outcomes a new reply may overwrite automatically. Once staff (or a reply)
# have moved the conversation to a meeting / proposal / partnership stage,
# a later "neutral" reply must not drag it back.
AUTO_REPLACEABLE = {"draft", "awaiting_reply", "replied", "positive", "neutral", "negative", "needs_follow_up"}

# Conversation outcome -> the company lead status it implies. Applied
# forward-only (see advance_lead_status): a company already at "Meeting"
# isn't moved back to "Follow-up" by a later reply.
_THREAD_TO_LEAD: dict[str, LeadStatus] = {
    "awaiting_reply": LeadStatus.CONTACTED,
    "replied": LeadStatus.FOLLOW_UP,
    "positive": LeadStatus.FOLLOW_UP,
    "neutral": LeadStatus.FOLLOW_UP,
    "needs_follow_up": LeadStatus.FOLLOW_UP,
    "proposal_requested": LeadStatus.FOLLOW_UP,
    "meeting_requested": LeadStatus.MEETING,
    "meeting_scheduled": LeadStatus.MEETING,
    "proposal_sent": LeadStatus.PROPOSAL_SENT,
    "partnership_confirmed": LeadStatus.SUCCESSFUL,
}
_LEAD_ORDER = [
    LeadStatus.NEW,
    LeadStatus.CONTACTED,
    LeadStatus.FOLLOW_UP,
    LeadStatus.MEETING,
    LeadStatus.PROPOSAL_SENT,
    LeadStatus.SUCCESSFUL,
]


def lead_status_for(thread_status: str, current: LeadStatus) -> Optional[LeadStatus]:
    """The lead status a company should move to, or None to leave it.

    Never moves backwards, and never touches a company marked Not
    Interested - a negative reply is a suggestion for staff, not a
    decision the app makes for them.
    """
    target = _THREAD_TO_LEAD.get(thread_status)
    if target is None or current == LeadStatus.NOT_INTERESTED:
        return None
    if _LEAD_ORDER.index(target) > _LEAD_ORDER.index(current):
        return target
    return None


def thread_status_for_reply(classification: str, intent: Optional[str]) -> str:
    if intent in ("meeting_requested", "proposal_requested") and classification != "negative":
        return intent
    return classification


# Dashboard pipeline: the existing lead statuses plus "Replied", which is
# derived (a contacted company whose conversation has a reply) so no new
# value has to be added to the LeadStatus enum.
PIPELINE_STAGES = ["New", "Contacted", "Replied", "Meeting", "Proposal", "Won", "Lost"]
