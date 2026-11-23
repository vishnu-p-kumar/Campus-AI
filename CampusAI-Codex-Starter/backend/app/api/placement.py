from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.documents.locking import lock_document_scope
from app.models import Application, AuditLog, Company, CompanyRequirement, Notification, PlacementDrive, PlacementRecord, ResumeAnalysis, StudentProfile, User
from app.schemas import DriveInput, DriveOutput
from app.security import get_current_user, require_roles
from app.eligibility.engine import evaluate_eligibility

router = APIRouter(prefix="/placement-drives", tags=["placement drives"])


def deadline_passed(deadline: datetime | None, *, now: datetime | None = None) -> bool:
    if deadline is None:
        return False
    current = now or datetime.now(timezone.utc)
    normalized_deadline = deadline.replace(tzinfo=timezone.utc) if deadline.tzinfo is None else deadline.astimezone(timezone.utc)
    normalized_now = current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current.astimezone(timezone.utc)
    return normalized_deadline < normalized_now


def drive_output(drive: PlacementDrive) -> DriveOutput:
    return DriveOutput(
        id=drive.id, company_id=drive.company_id, title=drive.title, role=drive.role,
        package_lpa=drive.package_lpa, location=drive.location, application_deadline=drive.application_deadline,
        drive_date=drive.drive_date, selection_process=drive.selection_process or [],
        status="closed" if drive.status == "open" and deadline_passed(drive.application_deadline) else drive.status,
        company_name=drive.company.name,
    )


def persist_application(db: Session, student_user_id: int, drive_id: int) -> Application:
    application = Application(student_user_id=student_user_id, drive_id=drive_id)
    db.add(application)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(select(Application.id).where(
            Application.student_user_id == student_user_id,
            Application.drive_id == drive_id,
        ))
        if existing:
            raise HTTPException(status_code=409, detail="You have already applied") from exc
        raise
    return application


def load_application_drive(db: Session, drive_id: int) -> PlacementDrive | None:
    return db.scalar(select(PlacementDrive).options(
        joinedload(PlacementDrive.company)
        .joinedload(Company.requirements)
        .joinedload(CompanyRequirement.source_document)
    ).where(PlacementDrive.id == drive_id))


def lock_application_for_update(db: Session, application_id: int) -> Application | None:
    """Serialize status transitions for one application on databases with row locks."""
    return db.scalar(
        select(Application)
        .where(Application.id == application_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


@router.get("/", response_model=list[DriveOutput])
def list_drives(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    drives = db.scalars(select(PlacementDrive).options(
        joinedload(PlacementDrive.company)
        .joinedload(Company.requirements)
        .joinedload(CompanyRequirement.source_document)
    ).order_by(PlacementDrive.drive_date)).unique().all()
    if user.role == "student":
        drives = [drive for drive in drives if evaluate_eligibility(
            user.student_profile, drive.company.requirements,
            source_approved=bool(drive.company.requirements and drive.company.requirements.source_document
                                 and drive.company.requirements.source_document.approval_status == "approved"),
        ).decision == "eligible"]
    return [drive_output(drive) for drive in drives]


@router.post("/", response_model=DriveOutput, status_code=201)
def create_drive(data: DriveInput, actor: User = Depends(require_roles("placement_officer", "administrator")), db: Session = Depends(get_db)):
    if not db.get(Company, data.company_id):
        raise HTTPException(status_code=404, detail="Company not found")
    drive = PlacementDrive(**data.model_dump())
    db.add(drive)
    db.flush()
    db.add(AuditLog(actor_user_id=actor.id, action="placement_drive.create", resource_type="placement_drive", resource_id=str(drive.id)))
    db.commit()
    return drive_output(db.scalar(select(PlacementDrive).options(joinedload(PlacementDrive.company)).where(PlacementDrive.id == drive.id)))


@router.put("/{drive_id}", response_model=DriveOutput)
def update_drive(drive_id: int, data: DriveInput, actor: User = Depends(require_roles("placement_officer", "administrator")), db: Session = Depends(get_db)):
    drive = db.get(PlacementDrive, drive_id)
    if not drive:
        raise HTTPException(status_code=404, detail="Drive not found")
    if not db.get(Company, data.company_id):
        raise HTTPException(status_code=404, detail="Company not found")
    for key, value in data.model_dump().items():
        setattr(drive, key, value)
    db.add(AuditLog(actor_user_id=actor.id, action="placement_drive.update", resource_type="placement_drive", resource_id=str(drive.id)))
    db.commit()
    return drive_output(db.scalar(select(PlacementDrive).options(joinedload(PlacementDrive.company)).where(PlacementDrive.id == drive.id)))


@router.get("/{drive_id}/eligible-students")
def eligible_students(drive_id: int, _: User = Depends(require_roles("placement_officer", "administrator")), db: Session = Depends(get_db)):
    drive = db.scalar(select(PlacementDrive).options(joinedload(PlacementDrive.company).joinedload(Company.requirements).joinedload(CompanyRequirement.source_document)).where(PlacementDrive.id == drive_id))
    if not drive:
        raise HTTPException(status_code=404, detail="Drive not found")
    users = db.scalars(select(User).options(joinedload(User.student_profile)).where(User.role == "student", User.is_active.is_(True)).order_by(User.full_name)).unique().all()
    result = []
    for student in users:
        rule = drive.company.requirements
        source_approved = bool(rule and rule.source_document and rule.source_document.approval_status == "approved")
        decision = evaluate_eligibility(student.student_profile, rule, source_approved=source_approved)
        if decision.decision == "eligible":
            result.append({"user_id": student.id, "student_id": student.student_profile.student_id, "name": student.full_name,
                           "branch": student.student_profile.branch, "decision": decision.decision, "reasons": decision.reasons,
                           "source_document_id": decision.source_document_id})
    return result


@router.patch("/{drive_id}/close", response_model=DriveOutput)
def close_drive(drive_id: int, actor: User = Depends(require_roles("placement_officer", "administrator")), db: Session = Depends(get_db)):
    drive = db.scalar(select(PlacementDrive).options(joinedload(PlacementDrive.company)).where(PlacementDrive.id == drive_id))
    if not drive:
        raise HTTPException(status_code=404, detail="Drive not found")
    drive.status = "closed"
    db.add(AuditLog(actor_user_id=actor.id, action="placement_drive.close", resource_type="placement_drive", resource_id=str(drive.id)))
    db.commit()
    return drive_output(drive)


@router.post("/{drive_id}/apply", status_code=201)
def apply_to_drive(drive_id: int, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    drive = load_application_drive(db, drive_id)
    if not drive:
        raise HTTPException(status_code=404, detail="Open placement drive not found")
    if drive.status != "open":
        raise HTTPException(status_code=404, detail="Open placement drive not found")
    if deadline_passed(drive.application_deadline):
        raise HTTPException(status_code=409, detail="The application deadline for this placement drive has passed")
    resume = db.scalar(select(ResumeAnalysis.id).where(ResumeAnalysis.user_id == user.id).limit(1))
    if resume is None:
        raise HTTPException(status_code=409, detail="Upload and analyze your resume before applying to placement drives.")
    rule = drive.company.requirements
    if rule:
        db.execute(select(CompanyRequirement.id).where(CompanyRequirement.id == rule.id).with_for_update())
        db.expire_all()
        drive = load_application_drive(db, drive_id)
        if not drive or drive.status != "open":
            raise HTTPException(status_code=404, detail="Open placement drive not found")
        if deadline_passed(drive.application_deadline):
            raise HTTPException(status_code=409, detail="The application deadline for this placement drive has passed")
        rule = drive.company.requirements
    source_document = rule.source_document if rule else None
    if source_document:
        lock_document_scope(db, source_document.title, source_document.company_id, source_document.academic_year)
        db.expire_all()
        drive = load_application_drive(db, drive_id)
        if not drive or drive.status != "open":
            raise HTTPException(status_code=404, detail="Open placement drive not found")
        if deadline_passed(drive.application_deadline):
            raise HTTPException(status_code=409, detail="The application deadline for this placement drive has passed")
        rule = drive.company.requirements
    source_approved = bool(rule and rule.source_document and rule.source_document.approval_status == "approved")
    result = evaluate_eligibility(user.student_profile, rule, source_approved=source_approved)
    if result.decision != "eligible":
        raise HTTPException(status_code=409, detail={"message": "Application requires eligibility review", "eligibility": result.model_dump()})
    existing = db.scalar(select(Application.id).where(Application.student_user_id == user.id, Application.drive_id == drive.id))
    if existing:
        raise HTTPException(status_code=409, detail="You have already applied")
    application = persist_application(db, user.id, drive.id)
    return {"id": application.id, "status": application.status, "drive_id": drive.id}


@router.patch("/applications/{application_id}/status")
def update_application_status(application_id: int, payload: dict, actor: User = Depends(require_roles("placement_officer", "administrator")), db: Session = Depends(get_db)):
    status_value = str(payload.get("status", ""))
    if status_value not in {"applied", "screening", "interview", "selected", "rejected", "withdrawn"}:
        raise HTTPException(status_code=422, detail="Unsupported application status")
    application = lock_application_for_update(db, application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    previous_status = application.status
    application.status = status_value
    drive = db.get(PlacementDrive, application.drive_id)
    placement = db.scalar(select(PlacementRecord).where(PlacementRecord.student_user_id == application.student_user_id, PlacementRecord.drive_id == application.drive_id))
    if status_value == "selected" and not placement and drive:
        db.add(PlacementRecord(student_user_id=application.student_user_id, company_id=drive.company_id, drive_id=drive.id,
                               role=drive.role, package_lpa=drive.package_lpa))
    elif status_value != "selected" and placement:
        db.delete(placement)
    if status_value != previous_status:
        db.add(Notification(
            user_id=application.student_user_id,
            title="Placement application updated",
            message=f"Your application for {drive.role if drive else 'a placement drive'} changed from {previous_status} to {status_value}.",
        ))
    db.add(AuditLog(actor_user_id=actor.id, action="application.status", resource_type="application", resource_id=str(application.id), details={"status": status_value}))
    db.commit()
    return {"id": application.id, "status": application.status}
