from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models import Application, AuditLog, ChatMessage, Company, Document, EvaluationRun, InterviewSession, PlacementDrive, PlacementRecord, StudentProfile, User
from app.schemas import AdminStudentCreateInput, AdminStudentUpdateInput, AdminUserOutput, AdminUserUpdate
from app.security import hash_password, require_roles

router = APIRouter(prefix="/admin", tags=["administration"])


def _student_record(user: User) -> dict:
    profile = user.student_profile
    return {
        "id": user.id, "full_name": user.full_name, "email": user.email,
        "profile": {key: getattr(profile, key) for key in (
            "student_id", "department", "branch", "graduation_year", "cgpa", "semester",
            "active_backlogs", "historical_backlogs", "technical_skills", "soft_skills",
            "certifications", "projects", "placement_status",
        )} if profile else {},
    }


@router.get("/students")
def student_records(_: User = Depends(require_roles("administrator")), db: Session = Depends(get_db)):
    users = db.scalars(select(User).options(joinedload(User.student_profile)).where(User.role == "student").order_by(User.full_name)).unique().all()
    return [_student_record(user) for user in users]


@router.post("/students", status_code=201)
def create_student(data: AdminStudentCreateInput, actor: User = Depends(require_roles("administrator")), db: Session = Depends(get_db)):
    email = str(data.email).lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this username/email already exists")
    values = data.model_dump(exclude={"email", "full_name", "password"})
    for key in ("student_id", "department", "branch"):
        if values[key] == "":
            values[key] = None
    user = User(email=email, full_name=data.full_name.strip(), password_hash=hash_password(data.password), role="student")
    user.student_profile = StudentProfile(**values)
    db.add(user)
    db.flush()
    db.add(AuditLog(actor_user_id=actor.id, action="student.create", resource_type="user", resource_id=str(user.id), details={"username": email}))
    try:
        db.commit()
    except IntegrityError as cause:
        db.rollback()
        raise HTTPException(status_code=409, detail="The username/email or student ID is already in use") from cause
    db.refresh(user)
    return _student_record(user)


@router.put("/students/{student_user_id}")
def update_student(student_user_id: int, data: AdminStudentUpdateInput, actor: User = Depends(require_roles("administrator")), db: Session = Depends(get_db)):
    user = db.scalar(select(User).options(joinedload(User.student_profile)).where(User.id == student_user_id, User.role == "student"))
    if not user:
        raise HTTPException(status_code=404, detail="Student not found")
    updates = data.model_dump(exclude_unset=True)
    password = updates.pop("password", None)
    if "email" in updates and updates["email"] is not None:
        updates["email"] = str(updates["email"]).lower()
        existing = db.scalar(select(User.id).where(User.email == updates["email"], User.id != user.id))
        if existing:
            raise HTTPException(status_code=409, detail="An account with this username/email already exists")
    profile_fields = set(AdminStudentCreateInput.model_fields) - {"email", "full_name", "password"}
    if not user.student_profile:
        user.student_profile = StudentProfile(user_id=user.id)
    for key, value in updates.items():
        if key in profile_fields:
            setattr(user.student_profile, key, None if key in {"student_id", "department", "branch"} and value == "" else value)
        elif value is not None:
            setattr(user, key, str(value).strip() if key == "full_name" else value)
    if password:
        user.password_hash = hash_password(password)
    audit_details = {key: value for key, value in updates.items() if key != "password"}
    if password:
        audit_details["password_changed"] = True
    db.add(AuditLog(actor_user_id=actor.id, action="student.update", resource_type="user", resource_id=str(user.id), details=audit_details))
    try:
        db.commit()
    except IntegrityError as cause:
        db.rollback()
        raise HTTPException(status_code=409, detail="The username/email or student ID is already in use") from cause
    db.refresh(user)
    return _student_record(user)


@router.get("/users", response_model=list[AdminUserOutput])
def users(_: User = Depends(require_roles("administrator")), db: Session = Depends(get_db)):
    return db.scalars(select(User).order_by(User.created_at.desc())).all()


@router.patch("/users/{user_id}", response_model=AdminUserOutput)
def update_user(user_id: int, data: AdminUserUpdate, actor: User = Depends(require_roles("administrator")), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    updates = data.model_dump(exclude_unset=True)
    if target.id == actor.id and (updates.get("role", target.role) != "administrator" or updates.get("is_active", True) is False):
        raise HTTPException(status_code=409, detail="You cannot disable or demote your own administrator account")
    next_role = updates.get("role", target.role)
    next_active = updates.get("is_active", target.is_active)
    if target.role == "administrator" and target.is_active and (next_role != "administrator" or not next_active):
        active_admins = db.scalar(select(func.count()).select_from(User).where(User.role == "administrator", User.is_active.is_(True))) or 0
        if active_admins <= 1:
            raise HTTPException(status_code=409, detail="At least one active administrator must remain")
    for key, value in updates.items():
        setattr(target, key, value)
    db.add(AuditLog(actor_user_id=actor.id, action="user.update", resource_type="user", resource_id=str(target.id), details=updates))
    db.commit()
    db.refresh(target)
    return target


@router.get("/analytics")
def analytics(_: User = Depends(require_roles("placement_officer", "administrator")), db: Session = Depends(get_db)):
    def count(model, *criteria):
        query = select(func.count()).select_from(model)
        for criterion in criteria:
            query = query.where(criterion)
        return db.scalar(query) or 0
    return {
        "students": count(User, User.role == "student"),
        "companies": count(Company),
        "open_drives": count(PlacementDrive, PlacementDrive.status == "open"),
        "documents_pending_review": count(Document, Document.approval_status == "pending"),
        "documents_approved": count(Document, Document.approval_status == "approved"),
        "interview_sessions": count(InterviewSession),
        "placements": count(PlacementRecord),
        "evaluation_runs": count(EvaluationRun),
        "chat_messages": count(ChatMessage),
    }


@router.get("/audit-logs")
def audit_logs(_: User = Depends(require_roles("administrator")), db: Session = Depends(get_db), limit: int = 100):
    limit = max(1, min(limit, 500))
    entries = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)).all()
    return [{"id": row.id, "actor_user_id": row.actor_user_id, "action": row.action, "resource_type": row.resource_type,
             "resource_id": row.resource_id, "details": row.details, "created_at": row.created_at} for row in entries]


@router.get("/evaluation-runs")
def evaluation_runs(_: User = Depends(require_roles("placement_officer", "administrator")), db: Session = Depends(get_db)):
    rows = db.scalars(select(EvaluationRun).order_by(EvaluationRun.created_at.desc())).all()
    return [{"id": row.id, "name": row.name, "system": row.system, "dataset_name": row.dataset_name,
             "status": row.status, "metrics": row.metrics, "created_at": row.created_at} for row in rows]


@router.get("/applications")
def applications(_: User = Depends(require_roles("placement_officer", "administrator")), db: Session = Depends(get_db)):
    rows = db.execute(select(Application, User, PlacementDrive, Company).join(User, User.id == Application.student_user_id).join(PlacementDrive, PlacementDrive.id == Application.drive_id).join(Company, Company.id == PlacementDrive.company_id).order_by(Application.applied_at.desc()).limit(500)).all()
    return [{"id": application.id, "student_user_id": student.id, "student_name": student.full_name, "student_email": student.email,
             "drive_id": drive.id, "company_id": company.id, "company": company.name, "role": drive.role, "status": application.status, "applied_at": application.applied_at, "resume_filename": application.resume_filename}
            for application, student, drive, company in rows]


@router.get("/placement-records")
def placement_records(_: User = Depends(require_roles("placement_officer", "administrator")), db: Session = Depends(get_db)):
    rows = db.execute(select(PlacementRecord, User, Company).outerjoin(User, User.id == PlacementRecord.student_user_id).join(Company, Company.id == PlacementRecord.company_id).order_by(PlacementRecord.placed_at.desc())).all()
    return [{"id": record.id, "student": student.full_name if student else "Former student (account deleted)", "student_email": student.email if student else None, "company": company.name,
             "role": record.role, "package_lpa": record.package_lpa, "placed_at": record.placed_at}
            for record, student, company in rows]
