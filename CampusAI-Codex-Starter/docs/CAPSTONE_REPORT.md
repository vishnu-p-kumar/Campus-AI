# CampusAI Capstone Report Draft

This is a structured report draft based on the implemented repository. Replace bracketed author/institution fields with verified project details. Do not turn the evaluation placeholders into results until experiments have been run on an approved corpus and reviewed by humans.

## 1. Abstract

CampusAI is a web platform for college placement preparation and administration. It provides student profiles, deterministic company eligibility explanations, placement-drive workflows, resume skill analysis, interview practice, document-grounded policy chat, document approval/versioning, and administrative analytics. The research component explores hybrid lexical/dense retrieval, evidence-aware abstention, citations, and historical policy retrieval. FastAPI, SQLAlchemy, Alembic, PostgreSQL, Next.js, Gemini, Sentence Transformers, and Qdrant form the deployment-oriented stack; SQLite and BM25 provide a local path when optional infrastructure is unavailable. No measured quality or institutional outcome is claimed in this draft.

## 2. Problem statement

Students need to find current placement rules, understand company-specific criteria, prepare application materials, and practice interviews. Placement teams need a consistent way to publish approved policy material and manage drives. Unversioned documents, disconnected workflows, and unsupported generative answers can make the information difficult to find and verify. CampusAI centralizes these workflows while preserving citations and human review for institutional decisions.

## 3. Motivation

Placement rules and employer criteria can change across recruitment cycles. A useful assistant must expose its source and date context and identify when available evidence cannot answer a question. Student preparation also benefits from transparent, practice-oriented feedback and skill guidance without turning model outputs into hiring decisions.

## 4. Objectives

1. Provide role-protected student and placement-team workflows backed by a relational database.
2. Make placement eligibility deterministic and explainable from reviewed requirements.
3. Restrict institutional policy answers to approved retrieved documents and show citations.
4. Preserve policy version/effective-date metadata for historical retrieval.
5. Provide resume skill-gap guidance and interview practice with clear AI/fallback behavior.
6. Support evaluation on manually reviewed data without inventing benchmark results.
7. Prepare local and Vercel/Render/PostgreSQL/Qdrant deployment configuration.

## 5. Existing system and limitations

Describe the placement information workflow at the project institution using interviews, process documents, and citations gathered by the student. Common limitations to investigate include information split across portals or files, manual eligibility checking, and limited historical policy traceability. This section needs institution-specific evidence and references; do not present these observations as measured facts without research.

## 6. Proposed system

CampusAI combines a student portal, an administrative placement workspace, a relational API, approved policy-document retrieval, and optional AI providers. Deterministic code handles eligibility and ownership checks. The LLM generates grounded natural-language responses or practice feedback; the LLM does not decide hiring or eligibility outcomes.

## 7. System architecture

The browser uses a Next.js App Router interface and calls FastAPI under `/api/v1`. The API persists structured state using SQLAlchemy and Alembic. Uploaded policy files are stored under a configured data directory and extracted into metadata-bearing chunks. BM25 search is available locally. Configured Sentence Transformers and Qdrant add dense retrieval; RRF combines rankings and a cross encoder can rerank candidates. Gemini is called only by the backend. Vercel and Render descriptors are provided but have not been deployed.

## 8. Module descriptions

- Identity: student registration, Argon2 passwords, short-lived JWT access, rotating HttpOnly refresh cookies, password reset, staff provisioning, roles, and account deletion.
- Student placement: profiles, completion indicators, drives, applications, eligibility evidence, and placement outcomes.
- Employer management: company records, source-linked requirements, requirement version history, and drives.
- Document knowledge base: PDF/DOCX/TXT validation and extraction, chunking, approval, version links, dates, and searchable metadata.
- Policy assistant: retrieval, confidence features, citations, conversation history, temporal filters, and abstention.
- Career preparation: resume extraction/skills, job skill-gap roadmap, and multi-round interview practice/history.
- Administration: document review, users, applications, notifications, audit events, and database-backed summaries.
- Research: metrics, scripts, annotations, dataset schema, and experiment result storage.

## 9. Database design

The SQLAlchemy model set includes `users`, `student_profiles`, `companies`, `company_requirements`, `company_requirement_versions`, `placement_drives`, `applications`, `placement_records`, `documents`, `document_chunks`, `conversations`, `chat_messages`, `refresh_tokens`, `password_reset_tokens`, `audit_logs`, `resume_analyses`, `skill_gap_analyses`, `interview_sessions`, `interview_responses`, `notifications`, and `evaluation_runs`. Foreign keys express ownership and lifecycle relations. See `DATABASE.md` and the Alembic revisions for the authoritative schema.

## 10. API documentation

FastAPI generates OpenAPI from typed routes at `/openapi.json` and a browsable reference at `/docs`. Main route groups include `/auth`, `/students`, `/dashboard`, `/companies`, `/placement`, `/documents`, `/chat`, `/resumes`, `/interviews`, `/notifications`, `/admin`, and `/evaluation`. Authentication and per-resource role/ownership checks are enforced by backend dependencies; see `ARCHITECTURE.md` for the route/access map.

## 11. AI methodology

Gemini is optional and server-side. Policy generation receives the user question and retrieved source text with explicit untrusted-source boundaries and citation instructions. Interview generation and review are separate from policy retrieval. Without credentials, policy answers that need generation report provider unavailability; interview sessions use labeled curated prompts and a transparent heuristic rubric. Model-generated feedback is practice guidance, not recruiter judgment.

## 12. RAG methodology

The lexical retriever tokenizes query and chunk content and ranks using BM25 (with lightweight Hindi/Kannada policy-term expansion). Dense retrieval uses a configured Sentence Transformer and Qdrant payload metadata. RRF combines lexical and dense rankings. An optional cross encoder reranks candidates. Current retrieval filters to approved, effective documents; temporal retrieval can include superseded documents valid at the requested date. Similarity or term coverage is not a calibrated probability.

## 13. Confidence-aware RAG methodology

The current evidence gate computes transparent heuristic features from query-term coverage, distinct source count, and lexical relevance; a separate post-generation check validates citation IDs, requires every detected answer sentence to carry a valid citation, and checks numeric claims against cited text. `EVIDENCE_MINIMUM_SCORE` controls the live weak-evidence cutoff and defaults to a provisional 0.35. An optional NLI cross encoder compares each sentence with its cited evidence and causes abstention when evidence does not entail the claim or the verifier fails. The model score is not calibrated, the verifier is disabled by default, and it has only mocked contract tests here. Weak/unsupported evidence or inadequate citations causes abstention. The evidence score remains a provisional heuristic and is not a calibrated probability. A research extension should tune and validate the cutoff and NLI behavior on development data, confirm them on held-out human-labeled examples, and measure abstention precision/recall, faithfulness, unsupported claims, and subgroup/language error.

## 14. Temporal retrieval methodology

Documents carry version, effective date, expiry date, approval state, and supersession links. Historical queries can retrieve approved or superseded versions only when their effective intervals cover the requested date. Chat can infer a past year when the question clearly asks about a historical policy, adds an outdated/superseded warning, and discloses conflicting retrieved numeric policy values. Upload date alone is not treated as policy validity.

## 15. Eligibility engine methodology

The deterministic engine evaluates reviewed company requirements against available profile fields: CGPA, branch, graduation year, backlog counts, and required skills. Each criterion produces a reason and source reference. A failed rule returns ineligible; missing profile data or unreviewed/incomplete requirements requires manual verification. Gemini does not participate in the outcome.

## 16. Research methodology

Compare three variants using the same approved corpus and question set: (A) Gemini-only informational baseline clearly marked unverified, (B) BM25 retrieval plus Gemini, and (C) confidence-aware temporal hybrid retrieval plus Gemini/abstention. Keep source corpus version, model IDs, filters, language, date, and annotation protocol fixed or recorded. Use de-identified, manually adjudicated questions and relevance labels. The provided experiment script can call Gemini and incur cost; it must be run only with an approved account and budget.

## 17. Evaluation metrics

Retrieval metrics include Precision@K, Recall@K, MRR, nDCG, and latency. Answer metrics include human-rated correctness, faithfulness, citation correctness, unsupported claim rate, and temporal accuracy. Abstention metrics include precision and recall against expected-abstention labels. Record token counts and estimated provider costs only when actual instrumentation supplies them. Add eligibility accuracy and multilingual performance using reviewed ground truth; do not infer them from retrieval metrics.

## 18. Experimental setup

Record hardware/runtime, dependency versions, corpus and dataset hashes, chunking settings, embedding/reranker model IDs, Qdrant collection configuration, Gemini model, prompt version, top-K, fusion settings, threshold version, random seed where relevant, and measurement date. Separate development/tuning data from held-out evaluation data. Do not use synthetic labels as results.

## 19. Results template (intentionally blank)

| System | P@5 | R@5 | MRR | nDCG@5 | Answer correctness | Faithfulness | Citation correctness | Unsupported claim rate | Abstention P/R | Temporal accuracy | Latency | Cost |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A — Gemini-only | pending | pending | n/a | n/a | pending | pending | n/a | pending | pending | pending | pending | pending |
| B — BM25 RAG | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending |
| C — confidence/temporal hybrid | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending |

No result values are provided until the experiment is executed and annotations are reviewed.

## 20. Security and responsible AI

Secrets remain server-side. Backend routes enforce roles and ownership. Passwords are hashed; uploads are size/type/content checked and can be scanned through ClamAV before processing; raw resume text is not persisted by analysis. Authentication endpoints share an atomic database-backed request counter across API workers. Eligibility is explainable and deterministic. AI outputs are labeled as suggestions. Do not use protected characteristics to rank candidates. Production still needs institution-approved retention rules, live scanner verification, rate-limit concurrency/load validation, provider privacy review, and operational security review.

## 21. Limitations

Python 3.11.9 has been verified locally. A real placement PDF passed local extraction, embedding, in-memory Qdrant storage/retrieval, BM25/RRF, reranking, historical retrieval, and safe abstention; this does not verify Qdrant Cloud. The prior Gemini generation request failed with sanitized output and missing provider detail, so its cause and generated citations remain unverified; no retry was made. The NLI verifier has mocked contract coverage only and needs multilingual model-specific evaluation. The CLI evaluation runner preserves dataset relevance labels, and cohort diagnostics support privacy suppression, but neither has been run on institution-reviewed ground truth. No paid provider experiment or deployment has been run. Scanned-PDF OCR depends on host Tesseract, and ClamAV still needs a live service and test signature. The PostgreSQL-backed worker queue is implemented; PostgreSQL multi-worker load and Render startup remain unverified. Hindi/Kannada quality, confidence threshold calibration, retention policy, and provider privacy review need institution-specific review. Browser E2E covers the core student and admin workflows. No institutional corpus or placement data is included.

## 22. Future enhancements

Verify OCR against a scanned sample on a Tesseract-equipped host and ClamAV against a live daemon/EICAR file; validate queue and rate-limit behavior under PostgreSQL concurrency, run live Qdrant/embedding provider and provider-backed chat E2E tests, conduct native-language evaluation, calibrate confidence thresholds, add richer company-specific practice content, review accessibility, and establish a privacy-reviewed production retention/deletion workflow.

## 23. Conclusion

CampusAI implements an integrated foundation for student placement workflows, explainable eligibility, approved-document assistance, interview/resume preparation, administration, and research evaluation. Its central design constraints are source traceability, deterministic institutional decisions, human oversight, and honest reporting of unverified provider or research behavior. Final claims must reflect measured tests and manually reviewed experiments.

## References

Add only sources actually consulted and verified by the project author. Include complete bibliographic metadata and access dates where required by the institution. This draft intentionally invents no citations.

## Author details

- Student: [name and student ID]
- Institution/department: [verified institution]
- Supervisor: [name]
- Academic year: [year]
