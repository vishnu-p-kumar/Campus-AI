"""Summarize reviewed cohort decisions from a local JSONL file without retaining records."""
import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research.evaluation.cohort_metrics import summarize_cohorts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records", type=Path, help="Local JSONL with cohort, predicted_positive, actual_positive")
    parser.add_argument("--minimum-group-size", type=int, default=5)
    parser.add_argument("--output", type=Path, help="Optional local output JSON path")
    args = parser.parse_args()
    records = [json.loads(line) for line in args.records.read_text(encoding="utf-8").splitlines() if line.strip()]
    report = summarize_cohorts(records, minimum_group_size=args.minimum_group_size)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()
