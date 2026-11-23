from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models import AuditLog, Company, CompanyRequirement, CompanyRequirementVersion, Document, User
from app.schemas import CompanyInput, CompanyOutput, EligibilityOutput
from app.security import get_current_user, require_roles
from app.eligibility.engine import evaluate_eligibility

router = APIRouter(prefix="/companies", tags=["companies"])
RULE_FIELDS = ("min_cgpa", "eligible_branches", "graduation_years", "max_active_backlogs", "max_historical_backlogs", "required_skills", "criteria_reviewed", "source_document_id")


def rule_snapshot(rule: CompanyRequirement) -> dict:
    return {key: getattr(rule, key) for key in RULE_FIELDS}


def company_output(company: Company) -> CompanyOutput:
    rule = company.requirements
    return CompanyOutput(
        id=company.id, name=company.name, industry=company.industry, description=company.description,
        website=company.website, job_roles=company.job_roles or [],
        min_cgpa=rule.min_cgpa if rule else None,
        eligible_branches=rule.eligible_branches if rule else None,
        graduation_years=rule.graduation_years if rule else None,
        max_active_backlogs=rule.max_active_backlogs if rule else None,
        max_historical_backlogs=rule.max_historical_backlogs if rule else None,
        required_skills=rule.required_skills if rule else [],
        criteria_reviewed=bool(rule and rule.criteria_reviewed),
        source_document_id=rule.source_document_id if rule else None,
    )


@router.get("/", response_model=list[CompanyOutput])
def list_companies(q: str | None = Query(default=None, max_length=100), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(Company).options(
        joinedload(Company.requirements).joinedload(CompanyRequirement.source_document)
    ).order_by(Company.name)
    if q:
        query = query.where(Company.name.ilike(f"%{q}%"))
    companies = db.scalars(query).unique().all()
    if user.role == "student":
        companies = [company for company in companies if evaluate_eligibility(
            user.student_profile, company.requirements,
            source_approved=bool(company.requirements and company.requirements.source_document
                                 and company.requirements.source_document.approval_status == "approved"),
        ).decision == "eligible"]
    return [company_output(item) for item in companies]


@router.post("/", response_model=CompanyOutput, status_code=201)
def create_company(data: CompanyInput, actor: User = Depends(require_roles("placement_officer", "administrator")), db: Session = Depends(get_db)):
    if db.scalar(select(Company.id).where(Company.name == data.name.strip())):
        raise HTTPException(status_code=409, detail="Company already exists")
    company = Company(name=data.name.strip(), industry=data.industry, description=data.description, website=str(data.website) if data.website else None, job_roles=data.job_roles)
    if data.source_document_id:
        source = db.get(Document, data.source_document_id)
        if not source or source.approval_status != "approved":
            raise HTTPException(status_code=422, detail="Eligibility rules must reference an approved source document")
    company.requirements = CompanyRequirement(**data.model_dump(include={"min_cgpa", "eligible_branches", "graduation_years", "max_active_backlogs", "max_historical_backlogs", "required_skills", "criteria_reviewed", "source_document_id"}))
    db.add(company)
    db.flush()
    db.flush()
    db.add(CompanyRequirementVersion(requirement_id=company.requirements.id, version=1, snapshot=rule_snapshot(company.requirements), changed_by=actor.id))
    db.add(AuditLog(actor_user_id=actor.id, action="company.create", resource_type="company", resource_id=str(company.id)))
    db.commit()
    db.refresh(company)
    return company_output(company)


@router.put("/{company_id}", response_model=CompanyOutput)
def update_company(company_id: int, data: CompanyInput, actor: User = Depends(require_roles("placement_officer", "administrator")), db: Session = Depends(get_db)):
    company = db.scalar(select(Company).options(joinedload(Company.requirements).joinedload(CompanyRequirement.source_document)).where(Company.id == company_id))
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    company.name = data.name.strip()
    company.industry, company.description = data.industry, data.description
    company.website, company.job_roles = str(data.website) if data.website else None, data.job_roles
    if data.source_document_id:
        source = db.get(Document, data.source_document_id)
        if not source or source.approval_status != "approved":
            raise HTTPException(status_code=422, detail="Eligibility rules must reference an approved source document")
    if not company.requirements:
        company.requirements = CompanyRequirement(company_id=company.id)
        db.flush()
        company.requirements.rule_version = 1
    else:
        company.requirements.rule_version += 1
    for key in RULE_FIELDS:
        setattr(company.requirements, key, getattr(data, key))
    db.flush()
    db.add(CompanyRequirementVersion(requirement_id=company.requirements.id, version=company.requirements.rule_version,
                                     snapshot=rule_snapshot(company.requirements), changed_by=actor.id))
    db.add(AuditLog(actor_user_id=actor.id, action="company.update", resource_type="company", resource_id=str(company.id)))
    db.commit()
    db.refresh(company)
    return company_output(company)


@router.get("/{company_id}/eligibility-rules/versions")
def rule_versions(company_id: int, _: User = Depends(require_roles("placement_officer", "administrator")), db: Session = Depends(get_db)):
    company = db.get(Company, company_id)
    if not company or not company.requirements:
        raise HTTPException(status_code=404, detail="Company eligibility rules not found")
    versions = db.scalars(select(CompanyRequirementVersion).where(CompanyRequirementVersion.requirement_id == company.requirements.id).order_by(CompanyRequirementVersion.version.desc())).all()
    return [{"version": row.version, "snapshot": row.snapshot, "changed_by": row.changed_by, "created_at": row.created_at} for row in versions]


@router.get("/{company_id}/eligibility", response_model=EligibilityOutput)
def check_eligibility(company_id: int, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    company = db.scalar(select(Company).options(joinedload(Company.requirements)).where(Company.id == company_id))
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    source_approved = bool(company.requirements and company.requirements.source_document
                           and company.requirements.source_document.approval_status == "approved")
    return evaluate_eligibility(user.student_profile, company.requirements, source_approved=source_approved)
