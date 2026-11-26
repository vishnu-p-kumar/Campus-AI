from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="student", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    student_profile: Mapped["StudentProfile | None"] = relationship(back_populates="user", cascade="all, delete-orphan", uselist=False)


class StudentProfile(Base):
    __tablename__ = "student_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    student_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    department: Mapped[str | None] = mapped_column(String(120))
    branch: Mapped[str | None] = mapped_column(String(120))
    graduation_year: Mapped[int | None] = mapped_column(Integer)
    cgpa: Mapped[float | None] = mapped_column(Float)
    semester: Mapped[int | None] = mapped_column(Integer)
    active_backlogs: Mapped[int | None] = mapped_column(Integer)
    historical_backlogs: Mapped[int | None] = mapped_column(Integer)
    technical_skills: Mapped[list] = mapped_column(JSON, default=list)
    soft_skills: Mapped[list] = mapped_column(JSON, default=list)
    certifications: Mapped[list] = mapped_column(JSON, default=list)
    projects: Mapped[list] = mapped_column(JSON, default=list)
    placement_status: Mapped[str] = mapped_column(String(40), default="seeking")
    user: Mapped[User] = relationship(back_populates="student_profile")


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    industry: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(String(500))
    job_roles: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    requirements: Mapped["CompanyRequirement | None"] = relationship(back_populates="company", cascade="all, delete-orphan", uselist=False)


class CompanyRequirement(Base):
    __tablename__ = "company_requirements"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), unique=True)
    min_cgpa: Mapped[float | None] = mapped_column(Float)
    eligible_branches: Mapped[list | None] = mapped_column(JSON)
    graduation_years: Mapped[list | None] = mapped_column(JSON)
    max_active_backlogs: Mapped[int | None] = mapped_column(Integer)
    max_historical_backlogs: Mapped[int | None] = mapped_column(Integer)
    required_skills: Mapped[list] = mapped_column(JSON, default=list)
    rule_version: Mapped[int] = mapped_column(Integer, default=1)
    criteria_reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", use_alter=True, name="fk_requirement_document"))
    company: Mapped[Company] = relationship(back_populates="requirements")
    versions: Mapped[list["CompanyRequirementVersion"]] = relationship(back_populates="requirement", cascade="all, delete-orphan")
    source_document: Mapped["Document | None"] = relationship(foreign_keys=[source_document_id])


class CompanyRequirementVersion(Base):
    __tablename__ = "company_requirement_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("company_requirements.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    requirement: Mapped[CompanyRequirement] = relationship(back_populates="versions")


class PlacementDrive(Base):
    __tablename__ = "placement_drives"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(180))
    role: Mapped[str] = mapped_column(String(180))
    package_lpa: Mapped[float | None] = mapped_column(Float)
    location: Mapped[str | None] = mapped_column(String(180))
    application_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    drive_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    selection_process: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    company: Mapped[Company] = relationship()


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("student_user_id", "drive_id", name="uq_student_drive_application"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    drive_id: Mapped[int] = mapped_column(ForeignKey("placement_drives.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="applied")
    resume_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resume_storage_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    drive: Mapped["PlacementDrive"] = relationship()


class PlacementRecord(Base):
    __tablename__ = "placement_records"
    __table_args__ = (UniqueConstraint("student_user_id", "drive_id", name="uq_placement_record_student_drive"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    student_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="RESTRICT"), index=True)
    drive_id: Mapped[int] = mapped_column(ForeignKey("placement_drives.id", ondelete="RESTRICT"), unique=True)
    role: Mapped[str] = mapped_column(String(180))
    package_lpa: Mapped[float | None] = mapped_column(Float)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SkillGapAnalysis(Base):
    __tablename__ = "skill_gap_analyses"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    resume_analysis_id: Mapped[int | None] = mapped_column(ForeignKey("resume_analyses.id", ondelete="SET NULL"))
    job_title: Mapped[str | None] = mapped_column(String(180))
    job_description_hash: Mapped[str] = mapped_column(String(64))
    required_skills: Mapped[list] = mapped_column(JSON, default=list)
    matching_skills: Mapped[list] = mapped_column(JSON, default=list)
    missing_skills: Mapped[list] = mapped_column(JSON, default=list)
    roadmap: Mapped[list] = mapped_column(JSON, default=list)
    ai_guidance: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ai_status: Mapped[str] = mapped_column(String(24), default="not_configured")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(240))
    category: Mapped[str] = mapped_column(String(80), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), index=True)
    academic_year: Mapped[str | None] = mapped_column(String(20), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(1000))
    version: Mapped[int] = mapped_column(Integer, default=1)
    effective_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    expiry_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    ingestion_status: Mapped[str] = mapped_column(String(24), default="completed", server_default="completed", index=True)
    ingestion_error: Mapped[str | None] = mapped_column(String(300))
    suggested_category: Mapped[str | None] = mapped_column(String(80))
    classification_score: Mapped[float | None] = mapped_column(Float)
    metadata_candidates: Mapped[dict] = mapped_column(JSON, default=dict)
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    page_number: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(240))
    text: Mapped[str] = mapped_column(Text)
    vector_id: Mapped[str | None] = mapped_column(String(80), index=True)
    document: Mapped[Document] = relationship(back_populates="chunks")
    __table_args__ = (UniqueConstraint("document_id", "chunk_index", name="uq_document_chunk"),)


class DocumentIngestionJob(Base):
    __tablename__ = "document_ingestion_jobs"
    __table_args__ = (Index("ix_document_ingestion_jobs_ready", "status", "available_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[str | None] = mapped_column(String(36))
    payload: Mapped[bytes | None] = mapped_column(LargeBinary)
    last_error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(180), default="New conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    resource_type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str | None] = mapped_column(String(80))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResumeAnalysis(Base):
    __tablename__ = "resume_analyses"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    skills: Mapped[list] = mapped_column(JSON, default=list)
    education: Mapped[list] = mapped_column(JSON, default=list)
    projects: Mapped[list] = mapped_column(JSON, default=list)
    experience: Mapped[list] = mapped_column(JSON, default=list)
    quality_feedback: Mapped[list] = mapped_column(JSON, default=list)
    ai_review: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ai_status: Mapped[str] = mapped_column(String(24), default="not_configured")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InterviewSession(Base):
    __tablename__ = "interview_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(32))
    language: Mapped[str] = mapped_column(String(8), default="en")
    focus: Mapped[str | None] = mapped_column(Text)
    question_type: Mapped[str] = mapped_column(String(24), default="typed")
    question_limit: Mapped[int] = mapped_column(Integer, default=5)
    current_question: Mapped[str | None] = mapped_column(Text)
    current_options: Mapped[list | None] = mapped_column(JSON, default=list)
    current_correct_answer: Mapped[str | None] = mapped_column(String(1))
    current_reference_answer: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="active")
    score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InterviewResponse(Base):
    __tablename__ = "interview_responses"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("interview_sessions.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    feedback: Mapped[dict] = mapped_column(JSON, default=dict)
    score: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180))
    system: Mapped[str] = mapped_column(String(32))
    dataset_name: Mapped[str] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(32), default="completed")
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(180))
    message: Mapped[str] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthRateLimitBucket(Base):
    """Shared fixed-window auth throttling state; stores no raw client address."""
    __tablename__ = "auth_rate_limit_buckets"
    rate_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_start: Mapped[int] = mapped_column(Integer, primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    __table_args__ = (Index("ix_auth_rate_limit_bucket_window", "window_start"),)
