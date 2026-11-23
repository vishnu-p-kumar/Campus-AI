# CampusAI Manual Setup and Release Checklist

## Is the project fully complete and verified?

No. The application has working student, placement, admin, document, chat, resume, interview, and evaluation flows, and its local automated checks pass. It is **not fully verified for production**.

Latest checks in this workspace (2026-11-20):

- Backend and research tests: **178 passed, 7 skipped** on Python 3.11.9 (one Qdrant compatibility warning). All seven PostgreSQL-specific tests passed separately against local PostgreSQL 19.
- Frontend lint and isolated production build: passed on Node.js v24.16.0. Browser E2E: **7 passed** using an isolated temporary SQLite database. The offline npm advisory cache reported 0 vulnerabilities; registry-backed audit could not be verified in this environment.
- Sentence Transformers 5.7.0 produced real 384-dimensional embeddings; the configured cross-encoder produced finite scores and ranked a relevant synthetic chunk first.
- Live public placement-PDF upload, extraction, 1,415 real embedding vectors in local in-memory Qdrant, dense search, BM25/RRF, cross-encoder reranking, historical retrieval, and unsupported-query abstention passed. Temporary vectors and database rows were cleaned up. No Gemini generation was made in this run.
- Exactly one live Gemini generation was attempted earlier. Its provider status was not saved, so the failure cannot be conclusively attributed. Current Google guidance says Gemini 2.5 Flash access is limited to prior users and recommends `gemini-3.5-flash-lite` as its transition model. The application default and local `GEMINI_MODEL` were changed to that model. No generation retry was made; live generated citations remain unverified.
- Follow-up read-only checks verified that Google currently lists `gemini-3.5-flash-lite` as stable and the installed `google-genai 3.6.1` request call matches the official Python SDK example. The read-only model lookup still returns only a generic SDK `RuntimeError`, so API-key/project permission, quota, billing, and endpoint access are not confirmed. [Official model list](https://ai.google.dev/gemini-api/docs/models), [official Python SDK docs](https://googleapis.github.io/python-genai/).
- Python 3.11.9 compatibility has been tested locally. This does not verify deployment on Render's configured Python patch release.
- Login was rechecked from the actual browser form against the running PostgreSQL-backed API; a unique temporary account was removed afterward. Network failures now show a readable connection message, covered by E2E, and credentials stay out of the URL. Use [http://127.0.0.1:3101/login](http://127.0.0.1:3101/login), enter the account email, and use port 3101 (port 3000 is not the running app).
- Student and administrator accounts use the same sign-in page: [Student sign in](http://127.0.0.1:3101/login) and [Administrator sign in](http://127.0.0.1:3101/login). After sign-in students go to [the student dashboard](http://127.0.0.1:3101/dashboard); administrators and placement officers go to [the admin dashboard](http://127.0.0.1:3101/admin). The requested administrator account was created in PostgreSQL and a live login check returned the administrator role. The password is stored only as an Argon2 hash and is deliberately omitted from this manual.
- Registration, password reset, and administrator creation now accept passwords of 6–128 characters, matching the requested minimum. The account creation button has a larger, explicitly white label; disabled buttons retain stronger text contrast.
- Latest RAG audit used a generated synthetic PDF (clearly marked as test content), real cached Sentence Transformer and cross-encoder weights, and local in-memory Qdrant. Upload/extraction, embedding, dense + BM25 retrieval, RRF, reranking, historical lookup, and unsupported-question abstention passed without Gemini. A real scanned PDF still fails extraction because Tesseract is unavailable; this fallback is reported as an upload error rather than silently indexing empty text.

Alembic reports no schema drift against local PostgreSQL 19. Readiness now checks PostgreSQL plus configured Qdrant and ClamAV. Runtime verification of the updated backend on port 8101 returned `/health` HTTP 200 and `/health/ready` HTTP 503 with PostgreSQL connected, Qdrant unavailable, and the optional scanner unconfigured. A direct Qdrant Cloud read from this Windows session failed with socket access denied; the existing backend on port 8003 needs restarting to load the updated readiness check. The live Gemini failure means generated grounded responses, citations, and live safe abstention are not verified; the latest read-only model-catalog check returned only a generic SDK `RuntimeError` without a status or reason, and this audit did not retry generation. Tesseract, `clamd`, and `clamscan` are absent. Docker Desktop is installed, but Windows denied access to start its ClamAV prerequisite service, so no scanner container, real scanned-PDF OCR, or antivirus test file was run. SMTP, Render, and Vercel are not configured or deployed. The browser citation test uses a mocked API response. Review `PROJECT_STATUS.md` for remaining checks.

The Gemini, JWT, Qdrant, and local PostgreSQL values supplied for this session are configured in the git-ignored `backend/.env`; they are not included in this manual or committed files. Since these credentials were pasted into a conversation, rotate them before production use. Do not put secrets in frontend variables or commit `.env`.

## 1. Install local prerequisites

Install Python 3.11, Node.js 20 or newer, and npm. Python 3.11.9 was used for the latest local test run. Docker Desktop is optional for local PostgreSQL, Qdrant, and ClamAV. Open PowerShell in the repository directory containing `PROJECT_SPEC.md` and `backend/`.

Create and activate a Python environment, then install the API dependencies:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
```

If PowerShell blocks environment activation, use the Python executable directly at `.venv\Scripts\python.exe` for each backend command.

Install frontend packages from the lockfile:

```powershell
Set-Location frontend
npm.cmd ci
Copy-Item .env.example .env.local
Set-Location ..
Copy-Item backend/.env.example backend/.env
```

Keep `.env`, `.env.local`, API keys, database URLs, and generated secrets out of source control. `.gitignore` already excludes environment files.

## 2. Configure local services

### SQLite, BM25, and local interview fallbacks

The copied `backend/.env.example` is enough to start in development with SQLite and lexical retrieval. Gemini, Qdrant, and SMTP values can remain empty. OCR is disabled by default. Chat and interview fallbacks remain available without Gemini.

Apply migrations from the repository root:

```powershell
python -m alembic -c backend/alembic.ini upgrade head
```

Start the API in one PowerShell window:

```powershell
python -m uvicorn app.main:app --app-dir backend --reload
```

Start Next.js in another window:

```powershell
Set-Location frontend
npm.cmd run dev
```

Open `http://localhost:3000`. The API health endpoints are `http://127.0.0.1:8000/health` and `/health/ready`.

### Optional PostgreSQL and Qdrant

With Docker Desktop running, from the repository root:

```powershell
docker compose -f docker-compose.dev.yml up -d postgres qdrant
```

For your existing local PostgreSQL server, set `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` in the git-ignored `backend/.env`. The backend constructs an escaped `postgresql+psycopg` SQLAlchemy URL from these variables, overriding the SQLite default. Keep the password out of source control, frontend variables, and command output. Alembic has been applied to the local `campusai` database and its schema check passed. Run `python scripts/run_postgres_tests.py` to repeat the seven integration tests; this runner accepts only local PostgreSQL hosts, validates the target database, and does not print credentials. For the Docker profile instead, set `DATABASE_URL` to the Compose PostgreSQL URL shown in `README.md`.

Dense retrieval also needs the optional AI packages and model weights:

```powershell
python -m pip install -r backend/requirements-ai.txt
```

The first model load can download weights and take time. Without a Qdrant URL or available dense model, the application falls back to BM25.

### Optional semantic faithfulness check

The chat API can check cited answer sentences with an NLI cross-encoder. It is disabled by default. To enable it, install `backend/requirements-ai.txt`, select a multilingual NLI model whose published label map includes entailment, neutral, and contradiction, then set `FAITHFULNESS_MODEL` to its model ID or local model path. Set `FAITHFULNESS_MIN_ENTAILMENT` between 0 and 1 (default 0.70). This is a model score, not a calibrated probability. The model downloads on first use if it is not cached. A model load, label-map, or inference error makes the chatbot abstain. Review the model license, language coverage, host memory, and institutional data policy before enabling it. Model weights and institution-specific semantic evaluation are not bundled.

### Confidence cutoff

`EVIDENCE_MINIMUM_SCORE` (default `0.35`) controls the heuristic evidence gate used by live chat, retrieval evaluation, and the confidence/temporal research variant. This default is provisional and is not a calibrated probability. Before changing it, collect at least 30 independently reviewed questions, inspect the reported coverage/unsafe-answer curve and candidate cutoff, tune on development labels, and confirm the chosen value on a separate held-out set. Then set the validated value in the backend environment (Render secret/environment settings in production) and rerun the same checks. Research records preserve the applied threshold. Do not treat a candidate computed on the evaluation set as validated.

### Optional Gemini, email, scanning, and OCR

Use separate server-side keys in backend/.env: GEMINI_API_KEY for resume review and role skill guidance, GEMINI_PLACEMENT_API_KEY for the placement assistant, and GEMINI_CHAT_API_KEY for interview practice. GEMINI_API_KEY is required for resume review; if it is missing or review fails, the upload returns an error and no local-only resume analysis is saved. Placement chat searches admin-approved documents by content and filename, then sends complete retrieved chunks with their stored filename and page/section metadata to Gemini. It checks citation and numeric support before showing the answer. When approved documents do not contain enough evidence, the fallback can use Gemini URL Context on up to 20 exact HTTPS URLs entered by an administrator in Admin > Knowledge Base. Set `GEMINI_URL_CONTEXT_ENABLED=true` in the backend environment and enable URL lookup in the admin panel. Gemini reads the supplied URLs; it does not search the web or follow links from those pages. The response cites only URLs whose retrieval metadata reports success and that exactly match the approved URL list. Retrieved page content counts toward the normal model input token quota; check current [URL Context documentation](https://ai.google.dev/gemini-api/docs/url-context) and [pricing](https://ai.google.dev/gemini-api/docs/pricing). If URL Context is disabled or cannot verify evidence, the assistant abstains. Interview preparation supports typed answers and Gemini-generated multiple-choice questions based on the entered role/specification; the separate Ask questions and doubts panel sends the question and optional role context to Gemini. Common email and phone details are redacted before resume text is sent for review. Uploading a resume with role details performs resume review and role matching in one Gemini request; the complete resume text is temporary and is not saved. Later role comparisons use the saved structured resume sections and Gemini. Required/matching/missing skills, roadmap items, and section-specific edits all come from that service; if it fails or returns an inconsistent skill comparison, the API returns an error rather than a local result. Only add resume claims supported by real experience. The shared model default is GEMINI_MODEL=gemini-3.5-flash-lite; override it only with a model available to the corresponding Google AI project. Never put either key in a NEXT_PUBLIC_* variable. Check the selected model's rate limits and pricing before live use. See Google's [current model guidance](https://ai.google.dev/gemini-api/docs/models) and [pricing](https://ai.google.dev/gemini-api/docs/pricing).

Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM_EMAIL`, and any required SMTP credentials to deliver password-reset email. Without SMTP, the API indicates that email delivery is not configured.

For local ClamAV scanning on Windows, Docker Desktop is the configured project setup: from the repository root run `docker compose -f docker-compose.dev.yml --profile security up -d clamav`, then set `CLAMAV_HOST=localhost` and `UPLOAD_SCAN_REQUIRED=true`. Wait for signatures to finish updating before testing uploads. The local PostgreSQL, Qdrant, and ClamAV ports bind to loopback only. This workspace has the Compose configuration, but no ClamAV container was running during verification. For native Windows service/package options, consult the [ClamAV Windows FAQ](https://docs.clamav.net/faq/faq-win32.html) and [official installation guide](https://docs.clamav.net/manual/Installing.html); configure clamd to accept the application's TCP connection at `127.0.0.1:3310`. Production requires a reachable scanner; uploads intentionally fail closed if required scanning is unavailable.

For Windows OCR, install the [Tesseract Windows build](https://github.com/UB-Mannheim/tesseract/wiki), add the directory containing `tesseract.exe` to `PATH`, and install the `eng`, `hin`, and `kan` language data required by your documents (see the [official Tesseract installation guide](https://github.com/tesseract-ocr/tessdoc/blob/main/Installation.md)). Set `OCR_ENABLED=true`, `OCR_LANGUAGES=eng+hin+kan`, and `OCR_DPI=300` in `backend/.env`. Missing-Tesseract fallback is tested; OCR of a real scanned PDF remains unverified because Tesseract is absent here.

## 3. Create the first administrator and initial placement data

Public registration creates student accounts only. After migrations, create the first administrator from the repository root:

```powershell
Set-Location backend
python -m app.cli create-user --email officer@example.edu --name "Placement Officer" --role administrator
Set-Location ..
```

Choose a unique password when prompted. Sign in as the placement administrator and perform the following setup in the admin page:

1. Upload current official placement policy documents in PDF, DOCX, or UTF-8 TXT format.
2. Review and approve each document after ingestion finishes. Only approved source documents support answers and eligibility rules.
3. Add companies and eligibility requirements, linking each requirement to its approved source document.
4. Publish placement drives with correct roles, locations, deadlines, and package data.
5. Register student test accounts, enter academic profiles, and verify eligibility/application workflows.
6. Use institution-approved, de-identified questions and source chunk IDs for research evaluation. Do not use real student resumes or identifiers in evaluation datasets.

## 4. Configure a real deployment manually

The repository contains Render and Vercel configuration, but creating accounts/resources, configuring secrets, and deploying are manual steps. No deployment has been made.

### Render API, worker, and PostgreSQL

1. Create a Render account and provision the PostgreSQL database plus API and ingestion worker described in `render.yaml`.
2. Confirm Render can build the configured Python 3.11.10 runtime. It has not been tested from this workspace.
3. Provide the following Render environment values using Render's secret/environment settings:
   - `CORS_ORIGINS`: exact HTTPS origin(s) of the deployed frontend, comma-separated if needed.
   - `PASSWORD_RESET_URL`: public HTTPS URL of the frontend reset-password page.
   - GEMINI_API_KEY: optional resume and skill-review provider key.
   - GEMINI_PLACEMENT_API_KEY: dedicated key for the placement assistant; set it before using document-grounded answers.
   - GEMINI_CHAT_API_KEY: optional interview provider key.
   - Authorized website URLs are managed in the administrator Knowledge Base panel and are stored in the CampusAI database.
   - GEMINI_URL_CONTEXT_ENABLED: server-side opt-in for reading the exact URLs managed in Admin > Knowledge Base.
   - `FAITHFULNESS_MODEL`: optional model for cited-sentence support checks; leave empty to retain deterministic citation and numeric checks only.
   - `QDRANT_URL` and `QDRANT_API_KEY`: Qdrant Cloud endpoint and key, shared by API and worker.
   - `CLAMAV_HOST`: private/reachable scanner hostname. Production requires `UPLOAD_SCAN_REQUIRED=true`; the manifest already sets this.
   - SMTP values if email delivery is required.
4. Keep the generated strong `JWT_SECRET_KEY`, PostgreSQL connection string, and provider keys private. Do not copy production secrets into this file or frontend variables.
5. Keep the configured persistent upload disk and `/health/ready` health check. The worker and API must use the same PostgreSQL database and Qdrant collection.
6. Confirm the build applies all Alembic migrations. Back up production data before applying migrations.
7. Configure and monitor a reachable ClamAV service before allowing uploads. Production rejects missing scanner configuration and fails closed when scanning is unavailable.

### Qdrant Cloud and Gemini

Create a Qdrant Cloud account/cluster, then set its URL and API key in both Render services. The collection is created by the application when the first document is indexed. Verify both API and worker use the same collection and embedding model. Model downloads and memory requirements need live deployment validation.

Create/configure a Gemini API key only if you intend to use generated chat and interview feedback. Check provider terms, access restrictions, and cost limits before enabling live calls. The app has not been tested against a live Gemini account in this workspace.

### Vercel frontend

1. Import the repository into Vercel and set the project root directory to `frontend/`. The Next.js framework descriptor is `frontend/vercel.json`.
2. Set `NEXT_PUBLIC_API_BASE_URL` to the deployed API origin and rebuild. It is public configuration, not a place for credentials.
3. Ensure `CORS_ORIGINS` on Render exactly matches the deployed Vercel origin, including `https://` and any custom domain.
4. Test the browser refresh-cookie flow on the chosen domains. Cross-site cookies require Secure/SameSite behavior; same-site subdomains are preferred.

## 5. Run checks before accepting users

From the repository root:

```powershell
python -m pytest backend/tests research/tests -q
python -m alembic -c backend/alembic.ini check
```

From `frontend/`:

```powershell
npm.cmd run lint
npm.cmd run build
npm.cmd audit
npx.cmd playwright install chromium
npm.cmd run test:e2e
```

Run the seven PostgreSQL-only concurrency tests with `python scripts/run_postgres_tests.py`. The runner reads the local connection settings without printing credentials, rejects non-local hosts and production mode, and verifies the target database before running. The tests create uniquely named temporary rows and clean them up; still use a development database, never production. Coverage includes atomic authentication operations, application races, status transitions, document-scope locking, and policy approval racing with application eligibility.

After deployment, manually verify:

- API `/health/ready` checks the database and any configured vector-store and upload-scanner dependencies; it returns 503 when a configured service is unreachable. The local backend must be restarted to load the latest readiness check.
- A student can register, sign in, complete a profile, view a drive, check deterministic eligibility, apply, and see application status.
- An administrator can sign in, upload/approve a policy, add a company requirement referencing it, and publish a drive.
- A student can query an approved policy and see citations, then ask an unsupported question and receive an abstention.
- Resume upload, parsing, skill gaps, English/Hindi/Kannada interview fallbacks, notifications, account deletion, and password reset behave as expected.
- Upload scanning blocks infected files and returns a clear unavailable response if the scanner is down.
- Qdrant indexing and retrieval work in the deployed worker/API logs; BM25 fallback remains available.
- Current and historical policy questions show the correct version/date warnings.

Use test accounts and non-sensitive sample documents for smoke checks. Review institutional retention rules, privacy notices, and authorized handling before using real student information. Have Hindi and Kannada content reviewed by fluent speakers before institutional use.

## Manual actions still outstanding

- To reproduce the Python 3.11.9 verification, use `.venv311\Scripts\python.exe`; deployment on the configured Render runtime still needs validation.
- Load-test the PostgreSQL ingestion queue with multiple worker processes and process interruption.
- Diagnose the single failed Gemini request using provider diagnostics and retry only when authorized; confirm response usage/cost settings before additional calls. Qdrant, Sentence Transformer embeddings, retrieval, and temporal retrieval have passed the synthetic live check.
- Configure SMTP, production ClamAV, and Tesseract/OCR if required; run a real scan and scanned-PDF check. No Tesseract/ClamAV host executables or running ClamAV container were present during verification.
- Create Render/Vercel resources, configure secrets/domains, deploy, and run production smoke tests.
- Review real institutional source material, manually labelled research data, privacy/retention policy, and native-speaker translations.
- Re-run registry-backed `npm audit` from a network that can reach the npm audit service before release. The offline cache reports zero advisories, but this does not refresh registry data.

## Latest local login check (2026-11-20)

Open CampusAI at [http://localhost:3101](http://localhost:3101). The frontend stays on port 3101 and connects to the backend at `http://localhost:8102` so the browser retains its same-host refresh cookie; `frontend/.env.local` and local CORS are configured for these fixed ports. Run the frontend with `cd frontend; npm.cmd run dev`. From the project root, run the backend with `.venv311\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8102`. The frontend displays “Backend API connected” when `/health` on port 8102 responds. If it shows unavailable, check that the backend process is running on 8102 and refresh. Enter the account email and password; do not share passwords, access tokens, or cookies.

To repeat the browser-to-API login check against the configured local database, run from `frontend/`:

```powershell
npm.cmd run smoke:local-login
```

It launches a headless browser on the IPv4 frontend origin, creates a uniquely named temporary student, logs in through the browser, and deletes the account. It prints only pass/fail statuses. If configuring different local ports, set `CAMPUSAI_LOCAL_WEB_URL` and `CAMPUSAI_LOCAL_API_URL` before running it. Use this only with a development database.

Most recent full backend/research verification: 170 passed, 7 skipped; PostgreSQL 19 integration tests 7 passed; frontend lint and isolated production build passed; E2E workflows 7 passed. Resume and document extraction errors return sanitized messages without private fragments or local paths. Production, API evaluation, and research experiments now use the same abstention rule for partial evidence. Gemini diagnostics safely classify allow-listed API error reasons; the replacement model setting is configured, but provider generation remains unverified. See `PROJECT_STATUS.md` for remaining service and deployment checks.

Do not treat the application as production-ready until these checks are completed and documented in `PROJECT_STATUS.md`.
