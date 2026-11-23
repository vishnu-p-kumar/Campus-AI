"""Strict JSONL preflight for reproducible, de-identified experiments."""
from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, ValidationError, field_validator


class DatasetModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


PositiveInt = Annotated[StrictInt, Field(ge=1)]


class StudentCase(DatasetModel):
    cgpa: StrictInt | StrictFloat | None = Field(default=None, ge=0, le=10)
    branch: StrictStr | None = None
    graduation_year: PositiveInt | None = None
    active_backlogs: StrictInt | None = Field(default=None, ge=0)
    historical_backlogs: StrictInt | None = Field(default=None, ge=0)
    technical_skills: list[StrictStr] = Field(default_factory=list)


class RequirementCase(DatasetModel):
    min_cgpa: StrictInt | StrictFloat | None = Field(default=None, ge=0, le=10)
    eligible_branches: list[StrictStr] | None = None
    graduation_years: list[PositiveInt] | None = None
    max_active_backlogs: StrictInt | None = Field(default=None, ge=0)
    max_historical_backlogs: StrictInt | None = Field(default=None, ge=0)
    required_skills: list[StrictStr] = Field(default_factory=list)
    criteria_reviewed: StrictBool
    source_document_id: PositiveInt | None
    rule_version: PositiveInt | None = None


class EligibilityCase(DatasetModel):
    student: StudentCase
    requirements: RequirementCase
    source_approved: StrictBool


class AnswerAnnotation(DatasetModel):
    answer_correct: StrictBool | None = None
    faithful: StrictBool | None = None
    citation_correct: StrictBool | None = None
    unsupported_claims: StrictInt | None = Field(default=None, ge=0)
    temporal_correct: StrictBool | None = None
    current_policy_correct: StrictBool | None = None
    historical_retrieval_correct: StrictBool | None = None
    version_identification_correct: StrictBool | None = None
    outdated_warning_correct: StrictBool | None = None
    conflict_detection_correct: StrictBool | None = None
    eligibility_actual: Literal["eligible", "not_eligible", "needs_manual_verification"] | None = None
    reviewer_id: StrictStr | None = None


class ExperimentQuestion(DatasetModel):
    question_id: StrictStr = Field(min_length=1, max_length=80)
    question: StrictStr = Field(min_length=3, max_length=3000)
    relevant_chunk_ids: list[PositiveInt] = Field(max_length=100)
    expected_abstain: StrictBool
    dataset_version: StrictStr | None = Field(default=None, min_length=1)
    language: Literal["en", "hi", "kn"] = "en"
    as_of: datetime | None = None
    category: StrictStr | None = None
    company_id: StrictInt | None = Field(default=None, ge=1)
    academic_year: StrictStr | None = None
    document_version: StrictInt | None = Field(default=None, ge=1)
    expected_answer: StrictStr | None = None
    eligibility_case: EligibilityCase | None = None
    annotation: AnswerAnnotation | None = None

    @field_validator("as_of", mode="before")
    @classmethod
    def parse_as_of(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("as_of must be an RFC3339 date-time string")
        if not re.search(r"(?:Z|[+-]\d{2}:\d{2})$", value):
            raise ValueError("as_of must include an RFC3339 timezone")
        if not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
            value,
        ):
            raise ValueError("as_of must use the RFC3339 date-time format")
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("as_of must include a timezone")
        return parsed


def _safe_validation_message(exc: ValidationError) -> str:
    fields = []
    for error in exc.errors(include_input=False, include_url=False):
        path = ".".join(str(part) for part in error["loc"])
        fields.append(f"{path}: {error['msg']}")
    return "; ".join(fields)


def _parse_dataset(text: str) -> list[dict]:
    rows: list[dict] = []
    seen_ids: set[str] = set()
    for line_number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Dataset line {line_number} contains invalid JSON (column {exc.colno}).") from exc
        try:
            parsed = ExperimentQuestion.model_validate(item)
        except ValidationError as exc:
            raise ValueError(f"Dataset line {line_number} is invalid: {_safe_validation_message(exc)}") from exc
        if parsed.question_id in seen_ids:
            raise ValueError(f"Dataset line {line_number} duplicates a prior question_id.")
        seen_ids.add(parsed.question_id)
        rows.append(parsed.model_dump(mode="json"))
    if not rows:
        raise ValueError("The evaluation dataset contains no question records.")
    return rows


def load_dataset(path: Path) -> list[dict]:
    """Validate JSONL before credentials, providers, or database sessions are opened."""
    return _parse_dataset(path.read_text(encoding="utf-8"))


def load_dataset_snapshot(path: Path) -> tuple[list[dict], str]:
    """Return validated rows and the digest of the exact bytes those rows came from."""
    content = path.read_bytes()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Dataset is not valid UTF-8 (byte offset {exc.start}).") from exc
    return _parse_dataset(text), hashlib.sha256(content).hexdigest()
