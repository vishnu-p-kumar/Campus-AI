# Deployment preparation

The repository includes Render service/database configuration in `render.yaml` and a Next.js deployment descriptor in `frontend/vercel.json`. These files prepare the application; no cloud resources have been provisioned and no deployment has been made.

## Render API

1. Create a Render PostgreSQL database and the API and ingestion worker services from `render.yaml`. Both services install `backend/requirements-ai.txt`; the worker receives the same Qdrant URL, key, collection, and embedding model as the API so ingestion writes vectors into the collection queried by chat.
2. Confirm the configured Python runtime is available on the selected plan. `render.yaml` targets Python 3.11.10, which has not been verified by this workspace's Python 3.10.0 runtime.
3. Review the forward Alembic migration in the build command and take a backup before production upgrades.
4. Provide CORS_ORIGINS as explicit HTTPS Vercel origin(s), and PASSWORD_RESET_URL as the public HTTPS reset page. Production API startup rejects SQLite, wildcard/non-HTTPS CORS, an insecure reset URL, weak JWT secrets, and missing required ClamAV configuration. Set GEMINI_API_KEY for resume/skill analysis and GEMINI_CHAT_API_KEY for chat/interviews in server-side secret settings, plus QDRANT_URL and QDRANT_API_KEY. Set SMTP variables if password-reset delivery is needed.
5. Ensure persistent disk paths match `UPLOAD_DIRECTORY`, HTTPS is enabled, and health checks use `/health/ready`.
6. Keep `UPLOAD_SCAN_REQUIRED=true` and set `CLAMAV_HOST` to a reachable private ClamAV daemon before accepting document or resume uploads. Uploads return 503 until scanning is available and 400 when infected. Configure `CLAMAV_PORT` and `CLAMAV_TIMEOUT_SECONDS` to match the daemon.
7. The API uses `DOCUMENT_INGESTION_MODE=queued`; the Render worker polls the shared PostgreSQL queue and processes uploads independently. Upload bytes stay in the database job until successful or terminal processing, so services do not require a shared filesystem. Approval is enabled after extraction completes. A failed terminal job currently requires a new upload.

## Vercel frontend

Create a Vercel project from this repository and set its **Root Directory** to `frontend`, following [Vercel's monorepo setup](https://vercel.com/docs/monorepos). Vercel then detects Next.js, installs from `frontend/package-lock.json`, and builds the app from its actual project root; [`frontend/vercel.json`](../frontend/vercel.json) declares the framework. Set `NEXT_PUBLIC_API_BASE_URL` to the deployed API origin and rebuild. This value is public configuration, so never put secrets in `NEXT_PUBLIC_*`. Add the final HTTPS frontend origin to Render's `CORS_ORIGINS` and `PASSWORD_RESET_URL`. If frontend and API use different sites, confirm refresh-cookie `SameSite`/`Secure` and browser third-party-cookie behavior for the chosen domains; same-site subdomains are preferred.

## Qdrant Cloud

Create the collection through the application by uploading/approving a document after providing the cloud URL and API key. The API and ingestion worker use the same collection and embedding model from `render.yaml`. The first embedding/reranker calls download configured model weights, so size both services for package build time, model storage, and runtime memory. BM25 remains the fallback if vector indexing fails. Embedding inference runs synchronously inside the ingestion worker and reranker inference runs in the API; monitor worker and API memory/logs.

## Before launch

- Use a unique high-entropy `JWT_SECRET_KEY` and secret manager; set `ENVIRONMENT=production`.
- Restrict CORS, validate the production browser cookie flow, configure SMTP, and establish backups and retention policies. Production login, registration, refresh, and logout calls require an allowed `Origin` header; the refresh cookie uses `SameSite=None` for cross-origin frontend hosting.
- Validate the PostgreSQL-backed authentication limiter's throughput and concurrent behavior at expected production traffic.
- Run tests, migrations against PostgreSQL, frontend build and a browser smoke test in the deployment environment.
- Conduct a security review, validate ClamAV scanning with clean and EICAR test files, configure OCR if required, and run native-speaker evaluation for Hindi and Kannada.
- Apply all Alembic migrations before deploying API and worker services. The database-backed auth limiter supports PostgreSQL and SQLite and shares counters across workers; auth endpoints return 503 if this security control cannot reach the database. The ingestion worker requires PostgreSQL row locking and must share the API database.
- Do not deploy or activate paid providers until the account owner has reviewed the costs and configuration.

For local malware-scanner development, `docker compose -f docker-compose.dev.yml --profile security up clamav` exposes the optional ClamAV daemon on port 3310. Set `CLAMAV_HOST=localhost` and `UPLOAD_SCAN_REQUIRED=true`; allow the daemon to load signature databases before testing uploads. First startup may take several minutes and needs network access to update signatures.
