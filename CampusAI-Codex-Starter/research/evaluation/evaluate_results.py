"""Summarize retrieval runs and manually annotated answers without inventing labels."""
import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from research.evaluation.metrics import summarize


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path, help="JSONL result file produced by run_experiment.py")
    parser.add_argument("--output", type=Path, default=Path("research/reports/evaluation_summary.json"))
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.results.read_text(encoding="utf-8").splitlines() if line.strip()]
    systems = sorted({row["system"] for row in rows})
    report = {"source_results": str(args.results), "question_count": len(rows), "systems": {system: summarize([row for row in rows if row["system"] == system], args.k) for system in systems},
              "note": "Answer metrics are null until manually reviewed annotations are added to each record."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
