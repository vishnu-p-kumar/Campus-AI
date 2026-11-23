# CampusAI — Placement Intelligence Platform

CampusAI is a full stack college placement application for students and placement teams. It combines deterministic placement eligibility, student workflows, approved policy documents, retrieval grounded chat, resume and interview preparation, and research evaluation. Provider credentials stay on the API server.

## What is implemented

- FastAPI API with SQLAlchemy models, PostgreSQL support, Alembic migrations, SQLite local mode, JWT access tokens, rotating HttpOnly refresh cookies, role checks, password reset, audit records with a dedicated audit page, separate user access-control page, administrator-only student account creation and profile editing, portable personal-data deletion with de-identified outcome retention, and a shared database-backed 20/minute auth throttle keyed by an HMAC of the client address. Optional ClamAV scanning covers document and resume uploads, with fail-closed behavior when required.
- Student profiles and dashboard; students can view their saved details while profile changes are managed by administrators. Admins can create an account using the student's email as the login username, set an initial password, and enter student ID, academic, backlog, and placement-status fields. Skills, certifications, and projects are not part of the student-add/edit form. Company requirements and version history; placement drives, applications, eligibility explanations, and placement outcomes. Student company and drive lists show only companies whose deterministic eligibility checks pass; a student must upload and successfully analyze a resume before applying. Application checks lock and reload the eligibility rule and its source policy on PostgreSQL so document review changes cannot race the eligibility decision; duplicate concurrent applications return HTTP 409.
- PDF, DOCX, and text ingestion with bounded extraction (500 pages and 5 million characters), DOCX archive validation, chunking, approval, versioning scoped to title, company, and academic year, effective dates, expiry, and historical policy retrieval. PostgreSQL transaction locks serialize version allocation and approval within each scope. Pending reviews block another upload in the same version chain, and only the current approved version can be superseded. Scanned PDF OCR is optional through PyMuPDF's Tesseract integration (`OCR_ENABLED=true`); install Tesseract plus the configured language data on the host.
- BM25 keyword retrieval; optional Sentence Transformers embeddings, Qdrant dense retrieval, reciprocal rank fusion and cross encoder reranking; grounded chat with citations and abstention when evidence is weak. Chat displays the answer and source citations without internal evidence scoring diagnostics. A student's own application list and status come only from that signed-in student's application records; company drive status comes from the structured drive record. When a question matches an approved uploaded document, the assistant expands the matched document IDs to every valid chunk and sends the complete document text to Gemini. This lets answers use details from later pages and interpret terms in the document without misclassifying them as job-title questions. Company-specific questions include structured company and drive records plus all approved documents associated by company ID, linked eligibility-source ID, or company name; the complete document is sent even when its database company ID is unset. Structured minimum eligibility fields are treated as the exact admin-entered criteria. Combined questions about a student's applications include only that student's application records and the corresponding companies' approved documents. Requested fields such as role, job description, and salary/package are answered only when present in the supplied evidence. Structured placement-drive records, including the admin-entered LPA package/compensation and location, are included as Gemini evidence; a package is not misrepresented as a separately disclosed base salary. Replies stay scoped to the requested fields. Questions requesting all listed companies or roles and explicit comparison questions retrieve a broader set of approved document chunks, and evidence matching includes document titles and filenames. Comparisons require cited evidence from both documents or both URLs; if one side is missing, the assistant uses authorized URL retrieval or abstains. Year-specific company lists require placement/company evidence for each requested year. Job-title answers distinguish position titles from practice areas. If approved document evidence is insufficient, optional URL Context is off until an administrator adds approved HTTPS URLs and enables it; `GEMINI_URL_CONTEXT_ENABLED=true` is also required server-side. Users may provide child-page URLs only on administrator-approved domains; the feature fetches only those exact URLs and does not crawl further nested links. CampusAI displays only URLs reported as successfully retrieved. Retrieved page content counts as normal model input tokens. See [Gemini URL Context](https://ai.google.dev/gemini-api/docs/url-context) and [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing). Safe no-evidence, policy-conflict, and temporal warnings support English, Hindi, and Kannada.
- Resume analysis requires a target role title; role information is optional. The complete extracted resume and target role are reviewed together by Gemini, with a compact structured result. Analysis runs outside the API event loop, uses a 20-second per-call timeout, and tries the configured free-tier model fallbacks. If AI review is unavailable or incomplete, the upload fails without saving a local-only analysis; the page exits its loading state and shows the retryable error. Students can select a resume section to see verified excerpts and role-specific suggested edits. The separate comparison form has independent role fields and reuses the analyzed resume without another upload. Resume and skill comparison results are not restored into the page after refresh. Interview preparation asks how many typed or multiple-choice questions to practice, generates questions across different topics in the selected category with difficulty increasing from easy to difficult, and returns the next question with the saved answer request. Coding practice always uses multiple-choice code-reading questions: choose the code's output or time complexity. Questions use a short, separately validated snippet with four matching answer options and try the configured free-tier model fallbacks; other categories allow typed or multiple-choice answers. Multiple-choice generation uses schema-validated JSON; correct answers score 1 and incorrect answers score 0, with a total correct count shown at completion. Typed answers are scored from 0 to 5 against a generated reference answer. All answers, scores, and feedback appear together when complete. Completed practice history opens saved questions, answers, and multiple-choice correct options. In interview Q&A, each compact exchange places the question in a light-blue bubble on the right and the direct structured answer in a light-green bubble on the left, followed by one separately labeled likely next interview question. Placement chat grounds answers in admin-approved documents and, when evidence is insufficient, can optionally use Gemini URL Context on up to 20 exact admin-authorized page URLs.
- Next.js App Router interface for student, placement officer, and administrator workflows; responsive layout and typed forms.
- Research scripts and dashboard for manually annotated retrieval/answer evaluation, raw evidence-score reliability diagnostics, abstention threshold curves, and held-out threshold candidates. Candidates are never applied automatically, and the repository contains no fabricated result values.

Feature boundaries, API behavior, and deployment notes: see [`manual.md`](manual.md), [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/DATABASE.md`](docs/DATABASE.md), [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md), [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md), [`docs/CAPSTONE_REPORT.md`](docs/CAPSTONE_REPORT.md), [`docs/DEMO_GUIDE.md`](docs/DEMO_GUIDE.md), and [`research/README.md`](research/README.md).

## Requirements and Python compatibility

- Node.js 20 or newer and npm.
- Python 3.11 or newer is the project target. Python 3.11.9 has been verified locally with the full backend/research suite and the real local document-ingestion pipeline. Render's configured Python patch release still needs deployment validation.
- PostgreSQL, Qdrant, and Gemini are optional for local development. SQLite and BM25 operate without them. Docker Compose can start local PostgreSQL and Qdrant.

## Local setup (PowerShell)

From the repository root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
Copy-Item backend/.env.example backend/.env
python -m alembic -c backend/alembic.ini upgrade head
python -m uvicorn app.main:app --app-dir backend --reload
```

Python 3.11.9 has been verified with the backend and research test suite. If `py -3.11` is unavailable, install Python 3.11 and recreate the environment. API docs are at `http://127.0.0.1:8000/docs`; health endpoints are `/health` and `/health/ready`.

Latest local verification is recorded in [`PROJECT_STATUS.md`](PROJECT_STATUS.md) and [`manual.md`](manual.md). The app passes local automated and PostgreSQL integration tests, but full production readiness is still blocked on live Gemini generation verification, OCR/antivirus host services, institution-reviewed multilingual/research data, and deployment configuration.

In a second terminal:

```powershell
Copy-Item frontend/.env.example frontend/.env.local
Set-Location frontend
npm.cmd install
npm.cmd run dev
```

For this workspace, open `http://localhost:3101`. The frontend is pinned to port 3101 and calls the backend at `http://localhost:8102` through `frontend/.env.local`. Keep `localhost` for both URLs so the browser sends the HttpOnly refresh cookie after a reload. Start the backend from the project root with `.venv311\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8102`.

### Optional PostgreSQL and Qdrant

For an existing local PostgreSQL installation, set `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` in the git-ignored `backend/.env`; leave `DATABASE_URL` unset so the settings build an escaped `postgresql+psycopg` URL from those components. An explicit `DATABASE_URL` takes precedence and is useful for Docker or isolated test databases. Keep the password only in `.env` or the process environment; never commit it. For Docker development, start services with `docker compose -f docker-compose.dev.yml up -d` and set `DATABASE_URL` to its PostgreSQL service on port 5433. Apply migrations after choosing the database. Set `QDRANT_URL=http://localhost:6333` to enable vector indexing.

GEMINI_API_KEY is used for resume reviews and skill-gap guidance. GEMINI_PLACEMENT_API_KEY is dedicated to placement assistant answers and admin-authorized URL Context. GEMINI_CHAT_API_KEY is used for interview practice. Keep all three server-side in backend/.env; never use NEXT_PUBLIC_* names for provider keys. Placement Gemini retries through distinct configured free-tier models when rate limits occur, including SDK `TooManyRequests` responses identified as HTTP 409 and standard HTTP 429 quota responses. The fallback list includes Gemini 2.5 Flash-Lite and Flash for projects with those free-tier limits available. If all configured models are rate-limited, the Google project quota must reset before another answer can be generated. For placement chat, the system searches approved complete documents for relevant evidence but sends only matching retrieved chunks, with a 24,000-character ordinary/company evidence budget and an 80,000-character exhaustive/comparison budget. If no approved document evidence is relevant, Gemini URL Context receives the question and administrator-authorized URLs; only successfully retrieved pages can be cited. This prevents unrelated document chunks from consuming the free-tier token-per-minute budget. Answers include document filename and page/section citations, with citation and numeric-claim checks before display. URL fallback additionally requires the `GEMINI_URL_CONTEXT_ENABLED=true` server-side master switch and an administrator to add exact HTTPS page URLs and enable the feature in the Knowledge Base panel. URL Context does not discover other URLs or follow nested links. Retrieved page text counts as normal Gemini input tokens ([documentation](https://ai.google.dev/gemini-api/docs/url-context), [pricing](https://ai.google.dev/gemini-api/docs/pricing)). Resume analysis removes common email and phone details before sending extracted text to Gemini; role analysis sends the full extracted resume text, AI-extracted sections, and target role to Gemini in the same upload request; comparisons with additional roles send the role and stored AI-extracted sections for required, matching, and missing skills, a learning roadmap, and section-specific resume edits; no local skill dictionary determines these results. If resume review or role comparison fails, the request returns an error instead of a locally generated result. Set QDRANT_URL and optionally QDRANT_API_KEY for Qdrant. Install the optional embedding/reranking packages with python -m pip install -r backend/requirements-ai.txt; model weights download at runtime. Configure SMTP settings to deliver password-reset email.

An optional cited-sentence NLI faithfulness verifier is documented in [`manual.md`](manual.md). It is disabled unless `FAITHFULNESS_MODEL` names a compatible model and requires institutional evaluation before use. The research runner applies the same citation, numeric-claim, and configured NLI checks to RAG answers; its model and provider paths are exercised with mocked tests, not paid calls.

Create the first privileged account from `backend/` after migrations:

```powershell
Set-Location backend
python -m app.cli create-user --email officer@example.edu --name "Placement Officer" --role administrator
```

The CLI prompts for the password and never stores a plaintext password. Public registration always creates student accounts.

## Verification

Run backend tests from the repository root:

```powershell
python -m pytest backend/tests -q
python -m alembic -c backend/alembic.ini check
```

The GitHub Actions backend workflow provisions PostgreSQL 16 and runs integration tests proving that matching document scopes serialize while unrelated scopes proceed concurrently, authentication throttling remains atomic, refresh and password-reset tokens are one-time across independent connections, simultaneous duplicate applications produce one creation plus clear conflicts, concurrent status updates serialize on the application row, and policy approval serializes against an application eligibility check. To run the seven PostgreSQL integration tests locally, configure `POSTGRES_*` in `backend/.env` and run `python scripts/run_postgres_tests.py`. The runner verifies the local database target and keeps credentials out of output. Never point concurrency tests at production; each test writes temporary uniquely named rows and cleans them up.

Run frontend checks from `frontend/`:

```powershell
npm.cmd run lint
npm.cmd run build
npm.cmd audit
npx.cmd playwright install chromium
npm.cmd run test:e2e
```

The Playwright end-to-end suite creates and migrates a unique temporary SQLite database and upload directory for each run, starts API and Next.js servers on ports 8100/3100, then removes its temporary data after both servers exit. It leaves existing project databases untouched. The suite exercises student registration, resume parsing and skill-gap analysis, English multi-round and Hindi interview practice, administrator document review, retrieval evaluation with evidence calibration diagnostics, drive creation, student eligibility/application tracking, safe chatbot abstention, conversation deletion, and citation rendering from a mocked API response. Authentication rate limiting is raised only in this disposable E2E server; dedicated backend tests cover the production throttle. Pass Playwright filters through the runner, for example `npm.cmd run test:e2e -- --grep administrator`.

Research evaluation is opt-in because the experiment runner can call Gemini and incur cost. See `research/README.md` and use only manually reviewed, non-sensitive evaluation data.

## Deployment

[`render.yaml`](render.yaml) and [`frontend/vercel.json`](frontend/vercel.json) provide deployment configuration for Render and Vercel. Production API startup verifies PostgreSQL, strong JWT, explicit HTTPS CORS/reset URLs, and required ClamAV upload scanning. Provision PostgreSQL and Qdrant Cloud, configure secrets and CORS origins, then follow [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). No deployment has been performed. Deploying or invoking paid providers requires the relevant accounts and explicit operator setup.

## Current status

This is an actively implemented capstone application. Provider-backed behavior, cloud deployment, OCR host setup, full multilingual generation quality, and Python 3.11 remain environment or integration validations; see [`PROJECT_STATUS.md`](PROJECT_STATUS.md) for verified commands and next actions.

