from time import perf_counter
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.ai.retrieval import confidence_features, hybrid_retrieve, retrieve, should_abstain_for_evidence
from app.db import get_db
from app.models import EvaluationRun, User
from app.schemas import EvaluationRunInput
from app.security import require_roles
from app.evaluation.metrics import summarize

router = APIRouter(prefix="/evaluation", tags=["research evaluation"])


@router.post("/runs", status_code=201)
def run_retrieval_evaluation(data: EvaluationRunInput, actor: User = Depends(require_roles("placement_officer", "administrator")), db: Session = Depends(get_db)):
    records = []
    for item in data.questions:
        started = perf_counter()
        if data.system == "bm25":
            sources = retrieve(db, item.question, as_of=item.as_of, limit=5)
        else:
            sources = hybrid_retrieve(db, item.question, as_of=item.as_of, limit=5)
        elapsed = (perf_counter() - started) * 1000
        features = confidence_features(item.question, sources)
        records.append({"question_id": item.question_id, "language": item.language,
                        "relevant_chunk_ids": item.relevant_chunk_ids,
                        "retrieved_chunk_ids": [row["chunk_id"] for row in sources],
                        "confidence_features": features, "expected_abstain": item.expected_abstain,
                        "predicted_abstain": should_abstain_for_evidence(features),
                        "retrieval_latency_ms": elapsed})
    metrics = summarize(records)
    metrics["evaluation_scope"] = "retrieval and evidence-based abstention only; answer metrics require human annotations"
    record = EvaluationRun(name=data.name, system=data.system, dataset_name=data.dataset_name, status="completed", metrics=metrics, created_by=actor.id)
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"id": record.id, "name": record.name, "system": record.system, "dataset_name": record.dataset_name,
            "question_count": len(records), "metrics": metrics}
