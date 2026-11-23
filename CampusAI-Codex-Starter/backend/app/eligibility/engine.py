from app.models import CompanyRequirement, StudentProfile
from app.schemas import EligibilityOutput


def evaluate_eligibility(student: StudentProfile | None, rule: CompanyRequirement | None, *, source_approved: bool = False) -> EligibilityOutput:
    if not student or not rule:
        return EligibilityOutput(decision="needs_manual_verification", reasons=["Student profile or approved company criteria are unavailable."], missing_fields=["student profile", "company criteria"])

    missing: list[str] = []
    reasons: list[str] = []
    if not rule.criteria_reviewed or rule.source_document_id is None or not source_approved:
        missing.append("approved source-linked eligibility criteria")
    checks = [
        ("cgpa", student.cgpa, rule.min_cgpa, lambda actual, limit: actual >= limit, "Minimum CGPA"),
        ("branch", student.branch, rule.eligible_branches, lambda actual, allowed: any(actual.casefold() == item.casefold() for item in allowed), "Branch"),
        ("graduation_year", student.graduation_year, rule.graduation_years, lambda actual, allowed: actual in allowed, "Graduation year"),
        ("active_backlogs", student.active_backlogs, rule.max_active_backlogs, lambda actual, limit: actual <= limit, "Active backlog count"),
        ("historical_backlogs", student.historical_backlogs, rule.max_historical_backlogs, lambda actual, limit: actual <= limit, "Historical backlog count"),
    ]
    failed = False
    for field, actual, expected, predicate, label in checks:
        if expected is None:
            continue
        if actual is None:
            missing.append(field)
        elif not predicate(actual, expected):
            failed = True
            reasons.append(f"{label} does not meet the company's published requirement.")
        else:
            reasons.append(f"{label} meets the company's published requirement.")

    required_skills = [str(skill).casefold() for skill in (rule.required_skills or [])]
    if required_skills:
        student_skills = [str(skill).casefold() for skill in (student.technical_skills or [])]
        if not student_skills:
            missing.append("technical_skills")
        else:
            missing_skills = [skill for skill in required_skills if skill not in student_skills]
            if missing_skills:
                failed = True
                reasons.append("The profile does not list required skills: " + ", ".join(missing_skills) + ".")
            else:
                reasons.append("The profile lists all required technical skills.")

    if missing:
        reasons.append("Some required profile information or company criteria are missing; manual review is needed.")
        decision = "needs_manual_verification"
    elif failed:
        decision = "not_eligible"
    else:
        decision = "eligible"
        if not reasons:
            reasons.append("The student satisfies all available company criteria.")
    return EligibilityOutput(decision=decision, reasons=reasons, missing_fields=missing, rule_version=rule.rule_version, source_document_id=rule.source_document_id)
