from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.eligibility.engine import evaluate_eligibility
from app.models import Application, Company, CompanyRequirement, PlacementDrive, StudentProfile, User
from app.security import require_roles

router = APIRouter(tags=["dashboard"])


@router.get("/students/me/dashboard")
def student_dashboard(user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    profile = db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
    upcoming = db.scalars(select(PlacementDrive).options(joinedload(PlacementDrive.company).joinedload(Company.requirements).joinedload(CompanyRequirement.source_document)).where(
        PlacementDrive.status == "open", (PlacementDrive.application_deadline.is_(None)) | (PlacementDrive.application_deadline >= datetime.now(timezone.utc))
    ).order_by(PlacementDrive.drive_date).limit(8)).unique().all()
    apps = db.scalars(select(Application).options(joinedload(Application.drive).joinedload(PlacementDrive.company)).where(Application.student_user_id == user.id).order_by(Application.applied_at.desc()).limit(8)).unique().all()
    fields = ["department", "branch", "graduation_year", "cgpa", "semester", "active_backlogs", "historical_backlogs", "technical_skills"]
    completed = sum(bool(getattr(profile, field)) if isinstance(getattr(profile, field), list) else getattr(profile, field) is not None for field in fields) if profile else 0
    eligible = []
    manual_count = 0
    for drive in upcoming:
        rule = drive.company.requirements
        source_approved = bool(rule and rule.source_document and rule.source_document.approval_status == "approved")
        result = evaluate_eligibility(profile, rule, source_approved=source_approved)
        if result.decision == "eligible":
            eligible.append({"drive_id": drive.id, "company": drive.company.name, "role": drive.role, "deadline": drive.application_deadline})
        elif result.decision == "needs_manual_verification":
            manual_count += 1
    return {
        "student": {"name": user.full_name, "email": user.email},
        "profile_completion": round(completed / len(fields) * 100),
        "eligibility_review_needed": manual_count,
        "eligible_drives": eligible,
        "upcoming_drives": [{"id": d.id, "company": d.company.name, "title": d.title, "role": d.role, "deadline": d.application_deadline, "date": d.drive_date} for d in upcoming],
        "applications": [{"id": a.id, "company": a.drive.company.name, "role": a.drive.role, "status": a.status, "applied_at": a.applied_at} for a in apps],
        "profile": profile,
    }


@router.get("/students/me/applications")
def my_applications(user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    apps = db.scalars(select(Application).options(joinedload(Application.drive).joinedload(PlacementDrive.company)).where(Application.student_user_id == user.id).order_by(Application.applied_at.desc())).unique().all()
    return [{"id": a.id, "drive_id": a.drive_id, "company": a.drive.company.name, "role": a.drive.role, "status": a.status, "applied_at": a.applied_at} for a in apps]
