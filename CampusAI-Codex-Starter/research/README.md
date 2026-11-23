# Research and evaluation workspace

This directory contains the reproducible evaluation utilities for retrieval and confidence-aware abstention. It does not contain benchmark claims or fabricated measurements. Use a manually reviewed, de-identified dataset with the schema in `datasets/question.schema.json`.

## Prepare data

Each record needs a stable question ID and text, relevant approved chunk IDs, and an expected-abstention label and historical date. Add a dataset version and optional category, company, academic-year, and document-version filters to make each corpus query reproducible; the CLI also accepts `--dataset-version` to label the entire snapshot. Keep ground-truth relevance and answer judgments separate from the model output. Do not include resumes, student identifiers, or private college material without authorization.

The CLI validates every JSONL row against strict typed fields before checking the Gemini key, creating a provider client, or opening the database. It rejects duplicate question IDs, unsupported languages, invalid time zones, malformed eligibility cases, and unknown keys with a line-specific message that does not echo the question text.

## Run evaluation

Each CLI result record includes `semantic_verifier_status` (`disabled`, `passed`, `failed`, `no_claims`, or `not_run`) so abstentions caused by a configured NLI service failure can be distinguished from ordinary model output. The runner never records private verifier exception text.

From the repository root, after installing backend requirements and configuring a database with approved documents:

```powershell
python research/evaluation/run_experiment.py --help
python research/evaluation/evaluate_results.py --help
```

The API evaluation endpoint compares `bm25` and `hybrid` retrieval and stores retrieval latency, ranking metrics and evidence-based abstention measurements. Each question must include a manually reviewed `expected_abstain` boolean; omitted labels are rejected instead of silently treated as answerable. Add `language` as `en`, `hi`, or `kn` to each question to retain the language on each record; reports and the admin dashboard show separate ranking, answer-quality, abstention, and evidence-calibration metrics per language as well as aggregate metrics. Missing language defaults to English. Do not compare groups as evidence of parity when they have too few independently reviewed examples. The report includes raw evidence-score Brier/ECE diagnostics, fixed-threshold coverage/unsafe-answer curves, and a candidate score cutoff only after 30 or more reviewed examples. The default live gate is `EVIDENCE_MINIMUM_SCORE=0.35`, a provisional heuristic, not a calibrated probability. The candidate is computed on the supplied set, is not applied automatically, and must be checked on separate held-out labels before manually setting this backend environment variable. Each confidence/temporal CLI result records the applied cutoff. The CLI runner compares Gemini-only, BM25+Gemini, and confidence/temporal hybrid systems on the same question records. Its RAG variants use the same production citation-coverage, cited-number, and optional NLI support checks; only sources actually cited in a surviving answer are recorded as citations. It records provider input/output token counts when returned by Gemini. Estimated cost remains null unless the operator supplies both current rates with `--input-cost-per-million-usd` and `--output-cost-per-million-usd`; the rates are written into each result record so the estimate is reproducible. No pricing is hard-coded. The runner may incur provider costs; inspect arguments and configure credentials before running it. Answer correctness, faithfulness, citation correctness, unsupported-claim rate, temporal accuracy, and eligibility accuracy require their corresponding human labels or instrumentation. Retrieval metrics alone do not establish answer quality.

For eligibility experiments, a question record may include a de-identified `eligibility_case` with student fields, requirements, and an explicit `source_approved` boolean. The runner applies the same deterministic eligibility engine used by the API, then compares its `predicted_eligibility` with the reviewer-provided `annotation.eligibility_actual`. Reports include exact decision accuracy and false-eligibility/false-ineligibility rates on binary ground-truth cases; manual-verification ground truth contributes to exact accuracy but not those binary error denominators. Temporal labels include current policy, historical retrieval, version identification, outdated-warning, and conflict-detection correctness. These results are null until corresponding labels exist. Never derive labels from model outputs or include identifiable student records in the dataset.

Each result records the dataset version and SHA-256 of the exact JSONL snapshot, corpus/version filters, selected Gemini/embedding/reranker/NLI model identifiers, provider configuration flags, Python/platform runtime, and the list of missing answer annotations. Model identifiers describe selected configuration; they do not prove that an optional service or model loaded successfully. If no label is supplied by `--dataset-version` or a row, the dataset version defaults to the snapshot SHA-256. Keep raw experiment data local or in an access-controlled research store.

## Cohort error diagnostics

`analyze_cohorts.py` accepts reviewed JSONL decision records with `cohort`, `predicted_positive`, and `actual_positive` JSON booleans. It reports selection rate, true/false positive rates, accuracy, and confusion counts for groups meeting the configurable minimum size (default 5). Smaller groups are suppressed. The input remains local and the script emits aggregates only. Example:

```json
{"cohort":"CSE","predicted_positive":true,"actual_positive":true}
```

Run `python research/evaluation/analyze_cohorts.py --help` for options. Include a cohort field only when its use is institutionally authorized and ethically reviewed. This is a descriptive error-analysis aid, not a legal fairness audit or a basis for ranking students. Review label provenance and error causes with human evaluators; never feed these metrics into eligibility or selection.
