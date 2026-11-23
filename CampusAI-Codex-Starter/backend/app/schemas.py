from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl


class RegisterInput(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=6, max_length=128)


class LoginInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetComplete(BaseModel):
    email: EmailStr
    token: str = Field(min_length=20, max_length=256)
    new_password: str = Field(min_length=6, max_length=128)


class TokenOutput(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: "UserOutput"


class UserOutput(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    role: str
    model_config = ConfigDict(from_attributes=True)


class AdminUserOutput(UserOutput):
    # Existing/legacy rows can contain reserved test domains such as
    # example.invalid. Admin listings must still serialize those records so a
    # single historical account cannot break the entire administration page.
    email: str
    is_active: bool
    created_at: datetime


class AdminUserUpdate(BaseModel):
    role: str | None = Field(default=None, pattern="^(student|placement_officer|administrator)$")
    is_active: bool | None = None


class StudentProfileInput(BaseModel):
    student_id: str | None = Field(default=None, max_length=80)
    department: str | None = Field(default=None, max_length=120)
    branch: str | None = Field(default=None, max_length=120)
    graduation_year: int | None = Field(default=None, ge=2000, le=2100)
    cgpa: float | None = Field(default=None, ge=0, le=10)
    semester: int | None = Field(default=None, ge=1, le=12)
    active_backlogs: int | None = Field(default=None, ge=0)
    historical_backlogs: int | None = Field(default=None, ge=0)
    technical_skills: list[str] = Field(default_factory=list, max_length=100)
    soft_skills: list[str] = Field(default_factory=list, max_length=100)
    certifications: list[str] = Field(default_factory=list, max_length=100)
    projects: list[str] = Field(default_factory=list, max_length=100)


class StudentProfileOutput(StudentProfileInput):
    id: int
    user_id: int
    placement_status: str
    model_config = ConfigDict(from_attributes=True)


class AdminStudentCreateInput(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=6, max_length=128)
    student_id: str | None = Field(default=None, max_length=80)
    department: str | None = Field(default=None, max_length=120)
    branch: str | None = Field(default=None, max_length=120)
    graduation_year: int | None = Field(default=None, ge=2000, le=2100)
    cgpa: float | None = Field(default=None, ge=0, le=10)
    semester: int | None = Field(default=None, ge=1, le=12)
    active_backlogs: int | None = Field(default=None, ge=0)
    historical_backlogs: int | None = Field(default=None, ge=0)
    technical_skills: list[str] = Field(default_factory=list, max_length=100)
    soft_skills: list[str] = Field(default_factory=list, max_length=100)
    certifications: list[str] = Field(default_factory=list, max_length=100)
    projects: list[str] = Field(default_factory=list, max_length=100)
    placement_status: str = Field(default="seeking", pattern="^(seeking|placed|not_seeking)$")


class AdminStudentUpdateInput(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    password: str | None = Field(default=None, min_length=6, max_length=128)
    student_id: str | None = Field(default=None, max_length=80)
    department: str | None = Field(default=None, max_length=120)
    branch: str | None = Field(default=None, max_length=120)
    graduation_year: int | None = Field(default=None, ge=2000, le=2100)
    cgpa: float | None = Field(default=None, ge=0, le=10)
    semester: int | None = Field(default=None, ge=1, le=12)
    active_backlogs: int | None = Field(default=None, ge=0)
    historical_backlogs: int | None = Field(default=None, ge=0)
    technical_skills: list[str] | None = Field(default=None, max_length=100)
    soft_skills: list[str] | None = Field(default=None, max_length=100)
    certifications: list[str] | None = Field(default=None, max_length=100)
    projects: list[str] | None = Field(default=None, max_length=100)
    placement_status: str | None = Field(default=None, pattern="^(seeking|placed|not_seeking)$")


class CompanyInput(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    industry: str | None = None
    description: str | None = None
    website: HttpUrl | None = None
    job_roles: list[str] = Field(default_factory=list)
    min_cgpa: float | None = Field(default=None, ge=0, le=10)
    eligible_branches: list[str] | None = None
    graduation_years: list[int] | None = None
    max_active_backlogs: int | None = Field(default=None, ge=0)
    max_historical_backlogs: int | None = Field(default=None, ge=0)
    required_skills: list[str] = Field(default_factory=list)
    criteria_reviewed: bool = False
    source_document_id: int | None = None


class CompanyOutput(BaseModel):
    id: int
    name: str
    industry: str | None
    description: str | None
    website: str | None
    job_roles: list[str]
    min_cgpa: float | None = None
    eligible_branches: list[str] | None = None
    graduation_years: list[int] | None = None
    max_active_backlogs: int | None = None
    max_historical_backlogs: int | None = None
    required_skills: list[str] = []
    criteria_reviewed: bool = False
    source_document_id: int | None = None


class DriveInput(BaseModel):
    company_id: int
    title: str = Field(min_length=1, max_length=180)
    role: str = Field(min_length=1, max_length=180)
    package_lpa: float | None = Field(default=None, ge=0)
    location: str | None = None
    application_deadline: datetime | None = None
    drive_date: datetime | None = None
    selection_process: list[str] = Field(default_factory=list)


class DriveOutput(DriveInput):
    id: int
    status: str
    company_name: str


class EligibilityOutput(BaseModel):
    decision: str
    reasons: list[str]
    missing_fields: list[str]
    rule_version: int | None = None
    source_document_id: int | None = None


class ChatInput(BaseModel):
    question: str = Field(min_length=3, max_length=3000)
    conversation_id: int | None = None
    language: str = Field(default="en", pattern="^(en|hi|kn)$")
    historical_as_of: datetime | None = None
    category: str | None = Field(default=None, max_length=80)
    company_id: int | None = None
    academic_year: str | None = Field(default=None, max_length=20)
    document_version: int | None = Field(default=None, ge=1)


class AuthorizedUrlInput(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


class PlacementWebSearchSettingInput(BaseModel):
    enabled: bool


class ChatOutput(BaseModel):
    conversation_id: int
    answer: str
    confidence: float
    confidence_label: str
    evidence_minimum_score: float
    citation_coverage: float
    citations: list[dict]
    temporal_warnings: list[str]
    claim_support: list[dict]
    abstained: bool


class EvaluationQuestionInput(BaseModel):
    question_id: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=3, max_length=3000)
    language: str = Field(default="en", pattern="^(en|hi|kn)$")
    relevant_chunk_ids: list[int] = Field(default_factory=list, max_length=100)
    expected_abstain: bool
    as_of: datetime | None = None


class EvaluationRunInput(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    dataset_name: str = Field(min_length=1, max_length=180)
    system: str = Field(default="confidence_temporal_hybrid", pattern="^(bm25|confidence_temporal_hybrid)$")
    questions: list[EvaluationQuestionInput] = Field(min_length=1, max_length=250)
