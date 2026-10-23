"""Outreach dashboard (Phase 4): KPI tiles, follow-up reminders, and a
recent-activity feed, all in one call to match the "Dashboard" screen in
docs/PROJECT_OVERVIEW.md.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import crud, models, schemas
from ..database import get_db
from ..mail import service as mail_service
from .emails import followup_out

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=schemas.DashboardResponse)
def get_dashboard(db: Session = Depends(get_db)):
    kpis = crud.get_dashboard_kpis(db)
    follow_ups = crud.get_follow_ups(db)
    activity = crud.get_recent_activity(db)
    outreach = mail_service.outreach_metrics(db)
    email_followups = (
        db.query(models.FollowUp)
        .filter(models.FollowUp.status.in_(("scheduled", "drafted")))
        .order_by(models.FollowUp.due_date)
        .limit(20)
        .all()
    )

    return schemas.DashboardResponse(
        kpis=schemas.DashboardKPIs(**kpis),
        follow_ups=schemas.FollowUps(
            overdue=[schemas.FollowUpItem.model_validate(c) for c in follow_ups["overdue"]],
            due_today=[schemas.FollowUpItem.model_validate(c) for c in follow_ups["due_today"]],
            upcoming=[schemas.FollowUpItem.model_validate(c) for c in follow_ups["upcoming"]],
        ),
        recent_activity=[
            schemas.ActivityLogOut(
                id=a.id,
                company_id=a.company_id,
                company_name=a.company.name,
                event_type=a.event_type,
                description=a.description,
                created_at=a.created_at,
            )
            for a in activity
        ],
        outreach=schemas.OutreachMetrics(**outreach["metrics"]),
        pipeline=[schemas.PipelineStage(**stage) for stage in outreach["pipeline"]],
        email_followups=[followup_out(f) for f in email_followups],
    )
