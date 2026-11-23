from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    Application, AuditLog, ChatMessage, Conversation, InterviewResponse, InterviewSession,
    Notification, PasswordResetToken, PlacementRecord, RefreshToken, ResumeAnalysis,
    SkillGapAnalysis, StudentProfile, User,
)
from app.schemas import StudentProfileOutput, UserOutput
from app.security import get_current_user, require_roles

router = APIRouter(prefix="/students", tags=["students"])


@router.get("/me", response_model=StudentProfileOutput)
def get_profile(user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    profile = db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
    if not profile:
        raise HTTPException(status_code=404, detail="Student profile not found")
    return profile


@router.put("/me")
def update_profile(user: User = Depends(require_roles("student"))):
    raise HTTPException(status_code=403, detail="Student profile details can only be changed by an administrator")


@router.get("/", response_model=list[UserOutput])
def list_students(_: User = Depends(require_roles("placement_officer", "administrator")), db: Session = Depends(get_db)):
    return db.scalars(select(User).where(User.role == "student").order_by(User.full_name)).all()


@router.delete("/me", status_code=204)
def delete_account(user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    user_id = user.id
    conversations = select(Conversation.id).where(Conversation.user_id == user_id)
    sessions = select(InterviewSession.id).where(InterviewSession.user_id == user_id)

    # Explicit child deletion keeps local SQLite behavior aligned with PostgreSQL
    # even when an application does not enable SQLite's foreign-key pragma.
    db.execute(delete(ChatMessage).where(ChatMessage.conversation_id.in_(conversations)))
    db.execute(delete(Conversation).where(Conversation.user_id == user_id))
    db.execute(delete(InterviewResponse).where(InterviewResponse.session_id.in_(sessions)))
    db.execute(delete(InterviewSession).where(InterviewSession.user_id == user_id))
    db.execute(delete(SkillGapAnalysis).where(SkillGapAnalysis.user_id == user_id))
    db.execute(delete(ResumeAnalysis).where(ResumeAnalysis.user_id == user_id))
    db.execute(delete(Application).where(Application.student_user_id == user_id))
    # Preserve the institution's placement outcome for aggregate reporting while
    # removing the student's direct identifier from that retained record.
    db.execute(update(PlacementRecord).where(PlacementRecord.student_user_id == user_id).values(student_user_id=None))
    db.execute(delete(Notification).where(Notification.user_id == user_id))
    db.execute(delete(RefreshToken).where(RefreshToken.user_id == user_id))
    db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user_id))
    db.execute(delete(StudentProfile).where(StudentProfile.user_id == user_id))
    db.execute(update(AuditLog).where(AuditLog.actor_user_id == user_id).values(actor_user_id=None))
    db.execute(update(AuditLog).where(AuditLog.resource_type == "user", AuditLog.resource_id == str(user_id)).values(resource_id=None))
    db.execute(delete(User).where(User.id == user_id))
    db.add(AuditLog(actor_user_id=None, action="student.account_delete", resource_type="user", resource_id=None,
                    details={"actor_erased": True}))
    db.commit()
    return Response(status_code=204)
