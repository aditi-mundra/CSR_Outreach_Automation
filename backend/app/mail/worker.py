"""Background loop: check for replies and turn due follow-ups into drafts.

Runs every EMAIL_SYNC_MINUTES in a daemon thread inside the API process -
no separate worker or queue, matching the project's "keep infrastructure
simple" rule. It only reads mail and creates drafts; it never sends.
On Render's free tier the process sleeps when idle, so checks happen
while the app is in use; the "Check for replies" button always works.
"""

from __future__ import annotations

import logging
import threading

from ..config import settings
from ..database import SessionLocal

logger = logging.getLogger("mail.worker")

_started = False
_stop = threading.Event()


def run_once() -> dict:
    from . import service

    db = SessionLocal()
    try:
        drafted = service.generate_due_followups(db)
        summary = {"followups_drafted": len(drafted)}
        try:
            summary.update(service.sync(db))
        except service.MailError as exc:
            summary["error"] = exc.message
        return summary
    finally:
        db.close()


def _loop(interval_seconds: int) -> None:
    while not _stop.wait(interval_seconds):
        try:
            result = run_once()
            if result.get("new_replies") or result.get("followups_drafted"):
                logger.info("Email sync: %s", result)
        except Exception:  # never let the loop die
            logger.exception("Email sync failed")


def start() -> None:
    global _started
    if _started or settings.email_sync_minutes <= 0:
        return
    _started = True
    threading.Thread(target=_loop, args=(settings.email_sync_minutes * 60,), name="email-sync", daemon=True).start()
