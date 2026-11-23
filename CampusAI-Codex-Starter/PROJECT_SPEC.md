# CampusAI — Project Specification

## Goal
Build an advanced, research-oriented AI-powered college placement intelligence platform for a 16-week AI/GenAI internship. It helps students understand placement policies, discover eligible companies, analyze resumes, identify skill gaps, prepare for interviews and receive personalized guidance.

## Research contributions
1. Confidence-aware RAG: evidence sufficiency, faithfulness checks, citation validation, unsupported-claim detection and abstention.
2. Temporal document intelligence: versions, effective dates, historical retrieval, superseded policies and conflict detection.
3. Explainable placement recommendations: deterministic eligibility rules with student values, required values, reasons and source references.
4. Personalized skill-gap recommendations based on resume and job-role requirements.
5. Responsible AI: privacy, human oversight, fairness/error analysis and multilingual performance evaluation.

## Stack
- Frontend: Next.js App Router, TypeScript, Tailwind CSS, accessible component system.
- Backend: Python 3.11+, FastAPI, Pydantic, SQLAlchemy, Alembic.
- LLM: Google Gemini API, called only from backend.
- Embeddings: Sentence Transformers.
- Retrieval: dense + BM25 hybrid search, Reciprocal Rank Fusion, cross-encoder reranking.
- Vector store: Qdrant Cloud in deployment; local ChromaDB optional for development.
- Structured data: PostgreSQL.
- Auth: secure password hashing, JWT/session strategy, role-based authorization.
- Testing: Pytest, frontend tests and Playwright E2E.
- Hosting: Vercel frontend, Render backend and PostgreSQL, Qdrant Cloud.

## Functional modules
- Student registration, login, profile and dashboard.
- AI placement chatbot with session history and source citations.
- PDF/DOCX upload, extraction, OCR extension point, chunking, embedding and indexing.
- Confidence-aware RAG with calibrated/validated thresholds; do not equate similarity scores with probabilities.
- Temporal document versioning and policy conflict disclosure.
- Explainable company eligibility checker using deterministic rules.
- Resume parsing and transparent resume/job matching (not a proprietary ATS score).
- Skill-gap analysis and personalized learning roadmap.
- Technical, HR, aptitude and coding interview practice.
- English, Hindi and Kannada assistance with evaluation.
- Company, placement-drive and application management.
- Admin portal, document approval, notifications and audit logs.
- Database-driven analytics and research evaluation dashboard.

## Research evaluation
Compare: A) Gemini-only baseline, B) basic RAG + Gemini, C) proposed confidence-aware/temporal RAG. Use the same question set and comparable source corpus. Track Precision@K, Recall@K, MRR, nDCG, answer correctness, faithfulness, citation correctness, unsupported claim rate, abstention precision/recall, temporal accuracy, eligibility accuracy, latency and estimated cost. Use manually verified ground truth. Never fabricate results.

## Security and privacy
- Keep secrets in environment variables and hosting secret stores.
- Never expose Gemini or database credentials in frontend bundles.
- Enforce per-user data access and role-based authorization.
- Validate uploaded file type, size, and readable content before extracting document text. Antivirus scanning is not part of this deployment.
- Avoid logging resumes, tokens or sensitive personal data.
- Do not use protected characteristics to rank students or automate hiring decisions.
- Provide deletion/retention controls and human review for sensitive decisions.

## 16-week plan
1–2: requirements, literature review, architecture, repo foundation.
3–4: authentication, PostgreSQL, roles and profiles.
5–6: document ingestion, embeddings, Qdrant and versioning.
7–8: Gemini, RAG, hybrid search, reranking and citations.
9–10: confidence/temporal research features and eligibility engine.
11–12: resume, skill gaps, interview preparation and multilingual support.
13–14: admin, analytics, notifications and fairness evaluation.
15: testing, reproducible experiments, security and performance.
16: Vercel/Render deployment, report, presentation and demo.

## Implementation rules
Build incrementally. First make frontend and backend run locally. Add migrations and tests before complex AI. Use mock providers in unit tests and separate real-service integration tests. Ask before paid services or production deployment. Do not claim features are complete until tested.
