import hashlib
import json

from sqlalchemy import text
from sqlalchemy.orm import Session


def lock_document_scope(db: Session, title: str, company_id: int | None, academic_year: str | None) -> None:
    """Serialize policy-chain reads and mutations for a document scope on PostgreSQL."""
    if db.get_bind().dialect.name != "postgresql":
        return
    scope = json.dumps([title, company_id, academic_year], ensure_ascii=False, separators=(",", ":"))
    key = int.from_bytes(hashlib.sha256(scope.encode("utf-8")).digest()[:8], byteorder="big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:scope_lock_key)"), {"scope_lock_key": key})
