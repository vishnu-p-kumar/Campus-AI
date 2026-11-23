from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuditLog, Notification, User
from app.security import get_current_user, require_roles

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/")
def list_notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(100)).all()
    return [{"id": n.id, "title": n.title, "message": n.message, "read": n.read_at is not None, "created_at": n.created_at} for n in rows]


@router.post("/", status_code=201)
def create_notification(payload: dict, actor: User = Depends(require_roles("placement_officer", "administrator")), db: Session = Depends(get_db)):
    user_id = int(payload.get("user_id", 0))
    title, message = str(payload.get("title", ""))[:180], str(payload.get("message", ""))[:2000]
    if not db.get(User, user_id) or not title or not message:
        raise HTTPException(status_code=422, detail="A valid user, title and message are required")
    record = Notification(user_id=user_id, title=title, message=message)
    db.add(record)
    db.flush()
    db.add(AuditLog(actor_user_id=actor.id, action="notification.create", resource_type="notification", resource_id=str(record.id)))
    db.commit()
    return {"id": record.id, "user_id": user_id, "title": title, "message": message}


@router.post("/{notification_id}/read")
def mark_read(notification_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(Notification, notification_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    row.read_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": row.id, "read": True}
