# CampusAI — Placement Intelligence Platform

CampusAI is a full stack college placement application for students and placement teams. It combines deterministic placement eligibility, student workflows, approved policy documents, retrieval grounded chat, resume and interview preparation, and research evaluation. Provider credentials stay on the API server.

The CampusAI Placement Assistant uses the FAQ / SQL / out-of-scope routing backend from `../placement-query-bot-deploy`. CampusAI keeps authenticated chat history and shows the bot's shared daily query meter. The standalone FastAPI deployment exposes `/health`, `/usage`, and `/query`; configure `GROQ_API_KEY` and optionally `JSONBIN_BIN_ID` / `JSONBIN_API_KEY` for query generation and the shared cross-instance daily counter. The placement bot no longer ships a separate Streamlit interface.

## What is implemented

- FastAPI API with SQLAlchemy models, PostgreSQL support, Alembic migrations, SQLite local mode, JWT access tokens, rotating HttpOnly refresh cookies, role checks, password reset, audit records with a dedicated audit page, separate user access-control page, administrator-only student account creation and profile editing, portable personal-data deletion with de-identified outcome retention, and a shared database-backed 20/minute auth throttle keyed by an HMAC of the client address. Optional ClamAV scanning covers document and resume uploads, with fail-closed behavior when required.
- Student profiles and dashboard; students can view their saved details while profile changes are managed by administrators. Admins can create an account using the student's email as the login username, set an initial password, and enter student ID, academic, backlog, and placement-status fields. Skills, certifications, and projects are not part of the student-add/edit form. Company requirements and version history; placement drives, applications, eligibility explanations, and placement outcomes. Student company and drive lists show only companies whose deterministic eligibility checks pass; students attach a separate PDF, DOCX, or TXT resume to each application; successful applications immediately show Applied, and all submitted applications appear in student activity. Resume analysis is optional and does not determine eligibility. Application checks lock and reload the eligibility rule and its source policy on PostgreSQL so document review changes cannot race the eligibility decision; duplicate concurrent applications return HTTP 409.
- PDF, DOCX, and text ingestion with bounded extraction (500 pages and 5 million characters), DOCX archive validation, chunking, approval, versioning scoped to title, company, and academic year, effective dates, expiry, and historical policy retrieval. PostgreSQL transaction locks serialize version allocation and approval within each scope. Pending reviews block another upload in the same version chain, and only the current approved version can be superseded. Scanned PDF OCR is optional through PyMuPDF's Tesseract integration (`OCR_ENABLED=true`); install Tesseract plus the configured language data on the host.
- Placement assistant queries keep the placement-query-bot FAQ / SQL / out-of-scope flow. Approved admin uploads are retrieved from the existing CampusAI document/chunk store and answered through the bot's Groq FAQ path with document citations. Faculty directory uploads are searchable across common terms such as faculty, professor, lecturer, and instructor. Company profile, eligibility, role, and open-drive details come from the admin-managed company records. Notification questions return only the signed-in candidate's messages (or, for staff, a specifically identified candidate), including read/unread status and full message text by title; chatbot lookups do not mark messages read or send private notification text to the optional query log. Simple answers remain plain paragraphs, while answers with multiple facts remain lists; only explicit headings receive heading styling. Citation/source panels and source markers are hidden in chat. Gemini is not used for placement answers; remaining Gemini integrations support resume review and interview preparation.
- Resume analysis uploads the resume alone and returns a structured review. Skill Gap Matching is a separate action that compares that saved review with a role and stores the role result independently. Analysis runs outside the API event loop, uses a 30-second per-call timeout, and tries only the configured primary and fallback models. If AI review is unavailable or incomplete, the upload fails without saving a local-only analysis; the page exits its loading state and shows the retryable error. Students can select a resume section to see verified excerpts and role-specific suggested edits. The comparison form has independent role fields and reuses the analyzed resume without another upload. Resume reviews and role skill comparisons are stored separately in the signed-in student account. The latest resume review restores after refresh, and View saved results lists all resume analyses and role comparisons separately so each role can be reopened or individually deleted. Deleting a resume review keeps its independent skill comparisons, and the Back to saved results button returns from an opened history item. If a new analysis fails, the previous successful result remains visible with the error until a later generation succeeds. Interview preparation asks how many questions to practice, generates questions across different topics in the selected category with difficulty increasing from easy to difficult, and returns the next question with the saved answer request. Aptitude and coding practice always use multiple-choice questions; typed answers remain available for Technical and HR practice. Coding practice uses short code-reading questions: choose the code's output or time complexity. Questions use a short, separately validated snippet with four matching answer options and try the configured model fallbacks. Multiple-choice generation uses schema-validated JSON; correct answers score 1 and incorrect answers score 0, with a total correct count shown at completion. Typed answers are scored from 0 to 5 against a generated reference answer. All answers, scores, and feedback appear together when complete. Completed practice history opens saved questions, answers, and multiple-choice correct options. In interview Q&A, each compact exchange places the question in a light-blue bubble on the right and the direct structured answer in a light-green bubble on the left, followed by one separately labeled likely next interview question. Placement chat uses the placement-query-bot FAQ / SQL / out-of-scope routing. Gemini is used for resume and interview features only.
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
python -m pip install -r backend/requirements.txt -r ../placement-query-bot-deploy/requirements.txt
Copy-Item backend/.env.example backend/.env
python -m alembic -c backend/alembic.ini upgrade head
python -m uvicorn app.main:app --app-dir backend --reload
```

Python 3.11.9 has been verified with the backend and research test suite. If `py -3.11` is unavailable, install Python 3.11 and recreate the environment. API docs are at `http://127.0.0.1:8000/docs`; health endpoints are `/health` and `/health/ready`.

Latest local verification is recorded in [`PROJECT_STATUS.md`](PROJECT_STATUS.md) and [`manual.md`](manual.md). On 2026-11-25, the backend suite passed 181 tests with 7 PostgreSQL integration tests skipped because `CAMPUSAI_TEST_POSTGRES_URL` was not configured. Synthetic API checks passed for the non-Gemini workflows listed in the status file. A small live synthetic resume request through the current API code returned HTTP 200 with resume sections and integrated role skills; the separate skill comparison returned HTTP 503 from both configured Gemini models. Direct resume and skill functions succeeded in the same retest, confirming Gemini generation is intermittent rather than consistently available. Production readiness also depends on reliable provider generation, host OCR/antivirus services, institution-reviewed multilingual/research data, and deployment configuration.

In a second terminal:

```powershell
Copy-Item frontend/.env.example frontend/.env.local
Set-Location frontend
npm.cmd install
npm.cmd run dev
```

For this workspace, open `http://localhost:3101`. The frontend is pinned to port 3101 and calls the backend at `http://localhost:8103` through `frontend/.env.local`. Keep `localhost` for both URLs so the browser sends the HttpOnly refresh cookie after a reload. Add `http://localhost:3101` to the backend `CORS_ORIGINS` setting so browser requests and refresh cookies are accepted. Start the backend from the project root with `.venv311\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8103`.

Backend settings load from the absolute `backend/.env` path, so Gemini and other server-side configuration is found even when the API is launched from the repository root. Use the CampusAI virtual environment and the commands in the repository-root `start.md` or `run.md` guide.

### Optional PostgreSQL and Qdrant

For an existing local PostgreSQL installation, set `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` in the git-ignored `backend/.env`; leave `DATABASE_URL` unset so the settings build an escaped `postgresql+psycopg` URL from those components. An explicit `DATABASE_URL` takes precedence and is useful for Docker or isolated test databases. Keep the password only in `.env` or the process environment; never commit it. For Docker development, start services with `docker compose -f docker-compose.dev.yml up -d` and set `DATABASE_URL` to its PostgreSQL service on port 5433. Apply migrations after choosing the database. Set `QDRANT_URL=http://localhost:6333` to enable vector indexing.

GEMINI_API_KEY is used for resume reviews and skill-gap guidance. GEMINI_CHAT_API_KEY is used for interview practice. Keep both server-side in backend/.env; never use NEXT_PUBLIC_* names for provider keys. Gemini retries through configured current-generation fallbacks for quota, rate-limit, and provider-availability errors, including SDK `TooManyRequests` responses identified as HTTP 409 and standard HTTP 429 responses. All Gemini-backed APIs use `gemini-3.5-flash-lite` first and only `gemini-3.1-flash-lite` as fallback; each key/project must still have generation access and available quota for those models. Resume analysis removes common email and phone details before sending extracted text to Gemini; role analysis sends the full extracted resume text, AI-extracted sections, and target role to Gemini in the same upload request; comparisons with additional roles send the role and stored AI-extracted sections for required, matching, and missing skills, a learning roadmap, and section-specific resume edits; no local skill dictionary determines these results. If resume review or role comparison fails, the request returns an error instead of a locally generated result. Set QDRANT_URL and optionally QDRANT_API_KEY for Qdrant. Install the optional embedding/reranking packages with python -m pip install -r backend/requirements-ai.txt; model weights download at runtime. Configure SMTP settings to deliver password-reset email.

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


### Latest local audit (2026-11-23)

Backend tests: 238 passed, 7 skipped. Frontend ESLint and production build passed. Alembic reported no schema drift. The local frontend is running at http://127.0.0.1:3101 and the API at http://127.0.0.1:8103. The API health endpoint returns HTTP 200. Readiness currently returns HTTP 503 because the configured Qdrant service is unavailable; the database is connected. See PROJECT_STATUS.md for details.

Student details lets students maintain their technical skills, soft skills, certifications, and projects. Synthetic provider checks generated a placement answer and interview MCQ, while resume analysis and role-skill guidance hit Gemini 503/504 and then quota/rate-limit errors; see PROJECT_STATUS.md for the exact scope and current provider limitation.

The Placement Assist usage screenshots show the placement and interview traffic in one AI Studio project log; separate configured API keys can still share project-level model limits. Resume and skill-gap 504s belong to the separate resume key path. The configured model fallbacks now match the models shown as available in the screenshots: Gemini 3.1 Flash-Lite followed by Gemini 3.8 Flash. “Back to dashboard” from student details uses client-side navigation to keep the student session active.

If Next.js reports a missing `./<chunk>.js` from `.next/server/webpack-runtime.js`, stop concurrent frontend dev/build processes, remove only the generated `frontend/.next` cache, then run `npm run dev` (or build and start production, but do not run both modes against the same `.next` directory). The current local frontend dev server returns HTTP 200 for `/` and `/login`.

For local login, open `http://127.0.0.1:3101`; `frontend/.env.local` points the API to `http://127.0.0.1:8103`. Keep the frontend and API on the same loopback hostname so the refresh cookie remains same-site across student and administrator sign-in.

Placement assistant responses keep the answer's natural shape: prose renders as plain paragraphs and pointwise answers render as aligned lists. Markdown bold markers and inline source markers are removed, and source panels are hidden in chat for new and historical assistant messages.

### Frontend/backend integration audit (2026-11-23)

Frontend API call paths were cross-checked against FastAPI OpenAPI with no missing endpoints found. Backend tests: 236 passed, 7 skipped. Frontend ESLint passed, and browser end-to-end tests passed (14/14), covering authentication/session refresh, student dashboards and staff-managed profile updates, interview practice, resume error handling, placement/admin workflows, eligibility, and chat citations/abstention. Live Gemini calls were not part of these tests. The local API database is connected; readiness reports unavailable Qdrant at this time. See PROJECT_STATUS.md for detailed run notes.

### Gemini resume connection diagnosis (2026-11-26)

The current resume-analysis failure was caused by the API process lacking outbound HTTPS to `generativelanguage.googleapis.com:443`. Both configured resume models failed locally with a network connection error before receiving a provider response. Restarting the API with outbound access resolved the connection; one small synthetic resume review then succeeded with the approved primary and fallback models. The API now returns a specific network-access message if this occurs again. See PROJECT_STATUS.md.

- Application resumes are stored privately with application records and can be downloaded by the applicant and placement staff. Academic eligibility remains a deterministic check against the student profile and published company criteria.


- Interview practice history can be viewed and deleted one session at a time by the signed-in student; deleting a session also removes its saved answers.


- Interview multiple-choice generation falls back to curated, validated question banks when Gemini models are unavailable. The active question row indicates when a curated question is in use.


- Interview Preparation opens with Aptitude selected and Multiple choice selected. Aptitude and Coding require multiple-choice answers; typed responses can be selected for Technical and HR categories.

- Placement Assist keeps semantically retrieved chunks when expanding approved documents, measures follow-up evidence against the current question, and abstains or uses admin-approved URL sources when evidence is weak. Company-specific detail questions may use the matching admin-entered company and drive record. General answer coverage still depends on the approved document corpus and a manually verified evaluation set.

- Placement Assist does not treat a model's “I could not verify” response as an answer or attach citations just because an approved URL was fetched. Its no-evidence message points students to the approved documents and the relevant section without assuming their file is unapproved.
- Placement Assist confidence matching normalizes application/apply wording and ignores common question framing. Citation coverage treats semicolon-separated clauses as one sentence so a citation at the end remains attached.
- In the current local Python environments, `sentence-transformers` is not installed, so Qdrant semantic queries fail and Placement Assist falls back to BM25 lexical retrieval. Exact wording checks can still work, but broader paraphrases have less retrieval coverage.

