from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import logging
from smtplib import SMTP
from urllib.parse import urlencode
import secrets
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuditLog, PasswordResetToken, RefreshToken, StudentProfile, User
from app.schemas import LoginInput, PasswordResetComplete, PasswordResetRequest, RegisterInput, TokenOutput, UserOutput
from app.security import get_current_user, hash_password, issue_access_token, new_refresh_token, refresh_token_hash, verify_password
from app.core.config import settings

router = APIRouter(prefix="/auth", tags=["authentication"])
logger = logging.getLogger(__name__)


def validate_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if settings.environment.casefold() == "production" and not origin:
        raise HTTPException(status_code=403, detail="Origin header is required for cookie-based session requests")
    if origin and origin not in settings.allowed_origins:
        raise HTTPException(status_code=403, detail="Cross-origin session request rejected")


def issue_session(user: User, db: Session) -> tuple[TokenOutput, str]:
    access, lifetime = issue_access_token(user)
    raw_refresh = new_refresh_token()
    db.add(RefreshToken(
        token_hash=refresh_token_hash(raw_refresh),
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
    ))
    db.commit()
    return TokenOutput(access_token=access, expires_in=lifetime, user=user), raw_refresh


def consume_refresh_token(db: Session, raw_refresh: str, now: datetime | None = None) -> int | None:
    """Atomically revoke a valid refresh token and return its owner once."""
    token_row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == refresh_token_hash(raw_refresh)))
    current_time = now or datetime.now(timezone.utc)
    if not token_row or token_row.revoked or token_row.expires_at.replace(tzinfo=timezone.utc) <= current_time:
        return None
    return db.execute(
        update(RefreshToken)
        .where(RefreshToken.id == token_row.id, RefreshToken.revoked.is_(False),
               RefreshToken.expires_at > current_time)
        .values(revoked=True)
        .execution_options(synchronize_session=False)
        .returning(RefreshToken.user_id)
    ).scalar_one_or_none()


def consume_password_reset_token(db: Session, raw_token: str, email: str, now: datetime | None = None) -> int | None:
    """Atomically consume a valid reset token for its matching active account."""
    token_row = db.scalar(select(PasswordResetToken).where(
        PasswordResetToken.token_hash == refresh_token_hash(raw_token)
    ))
    current_time = now or datetime.now(timezone.utc)
    if not token_row or token_row.used or token_row.expires_at.replace(tzinfo=timezone.utc) <= current_time:
        return None
    user = db.get(User, token_row.user_id)
    if not user or user.email != email.lower() or not user.is_active:
        return None
    return db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.id == token_row.id, PasswordResetToken.used.is_(False),
               PasswordResetToken.expires_at > current_time)
        .values(used=True)
        .execution_options(synchronize_session=False)
        .returning(PasswordResetToken.user_id)
    ).scalar_one_or_none()


def set_refresh_cookie(response: Response, token: str) -> None:
    production = settings.environment.casefold() == "production"
    response.set_cookie(
        "campusai_refresh", token, httponly=True, secure=production,
        samesite="none" if production else "lax", path=f"{settings.api_prefix}/auth", max_age=settings.refresh_token_expire_days * 86400,
    )


@router.post("/register", response_model=TokenOutput, status_code=status.HTTP_201_CREATED)
def register(data: RegisterInput, request: Request, response: Response, db: Session = Depends(get_db)):
    validate_origin(request)
    email = str(data.email).lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user = User(email=email, full_name=data.full_name.strip(), password_hash=hash_password(data.password), role="student")
    user.student_profile = StudentProfile()
    db.add(user)
    db.commit()
    db.refresh(user)
    token, refresh = issue_session(user, db)
    set_refresh_cookie(response, refresh)
    return token


@router.post("/login", response_model=TokenOutput)
def login(data: LoginInput, request: Request, response: Response, db: Session = Depends(get_db)):
    validate_origin(request)
    user = db.scalar(select(User).where(User.email == str(data.email).lower()))
    if not user or not verify_password(data.password, user.password_hash) or not user.is_active:
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    token, refresh = issue_session(user, db)
    set_refresh_cookie(response, refresh)
    return token


@router.post("/refresh", response_model=TokenOutput)
def refresh(request: Request, response: Response, raw_refresh: str | None = Cookie(default=None, alias="campusai_refresh"), db: Session = Depends(get_db)):
    validate_origin(request)
    if not raw_refresh:
        raise HTTPException(status_code=401, detail="Refresh token is missing")
    user_id = consume_refresh_token(db, raw_refresh)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Refresh token is invalid or expired")
    user = db.get(User, user_id)
    if not user or not user.is_active:
        db.commit()
        raise HTTPException(status_code=401, detail="Account is unavailable")
    db.commit()
    token, refresh = issue_session(user, db)
    set_refresh_cookie(response, refresh)
    return token


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, raw_refresh: str | None = Cookie(default=None, alias="campusai_refresh"), db: Session = Depends(get_db)):
    validate_origin(request)
    token_row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == refresh_token_hash(raw_refresh))) if raw_refresh else None
    if token_row:
        token_row.revoked = True
        db.commit()
    production = settings.environment.casefold() == "production"
    response.delete_cookie("campusai_refresh", path=f"{settings.api_prefix}/auth", httponly=True, secure=production, samesite="none" if production else "lax")


@router.post("/password-reset/request")
def request_password_reset(data: PasswordResetRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == str(data.email).lower(), User.is_active.is_(True)))
    if user:
        raw_token = secrets.token_urlsafe(40)
        expires = datetime.now(timezone.utc) + timedelta(minutes=30)
        db.add(PasswordResetToken(token_hash=refresh_token_hash(raw_token), user_id=user.id, expires_at=expires))
        db.commit()
        if settings.smtp_host and settings.smtp_from_email:
            try:
                query = urlencode({"email": user.email, "token": raw_token})
                message = EmailMessage()
                message["Subject"] = "Reset your CampusAI password"
                message["From"] = settings.smtp_from_email
                message["To"] = user.email
                message.set_content(f"Use this link within 30 minutes to reset your CampusAI password:\n{settings.password_reset_url}?{query}\n\nIf you did not request this, ignore this email.")
                with SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
                    smtp.starttls()
                    if settings.smtp_username and settings.smtp_password:
                        smtp.login(settings.smtp_username, settings.smtp_password)
                    smtp.send_message(message)
            except Exception:
                logger.exception("Password reset email delivery failed for user id %s", user.id)
    return {"message": "If an active account exists for this email, password reset instructions have been sent.",
            "email_delivery_configured": bool(settings.smtp_host and settings.smtp_from_email)}


@router.post("/password-reset/complete")
def complete_password_reset(data: PasswordResetComplete, db: Session = Depends(get_db)):
    user_id = consume_password_reset_token(db, data.token, str(data.email).lower())
    if user_id is None:
        raise HTTPException(status_code=400, detail="Password reset link is invalid or expired")
    user = db.get(User, user_id)
    user.password_hash = hash_password(data.new_password)
    db.query(RefreshToken).filter(RefreshToken.user_id == user.id).update({"revoked": True})
    db.add(AuditLog(actor_user_id=user.id, action="auth.password_reset", resource_type="user", resource_id=str(user.id)))
    db.commit()
    return {"message": "Password updated. Sign in with your new password."}


@router.get("/me", response_model=UserOutput)
def me(user: User = Depends(get_current_user)):
    return user
