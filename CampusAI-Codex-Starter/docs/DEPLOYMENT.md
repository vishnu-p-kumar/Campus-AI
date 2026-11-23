# Free-tier deployment

This deployment profile is intended for a small demo or capstone project. It keeps the FastAPI API, Next.js interface, PostgreSQL data, authentication, placements, interviews, chat, and BM25 document retrieval. It avoids the paid Render worker, disk, and database, plus Qdrant and local embedding-model downloads.

The free profile deliberately disables all file uploads. This includes placement-document ingestion and resume upload/analysis. Do not enable uploads until the API can reach a malware scanner such as ClamAV and `UPLOAD_SCAN_REQUIRED=true` is configured. The API enforces this setting even if someone bypasses the frontend.

## Free services used

- **Render Free Web Service:** hosts the FastAPI backend. Free instances sleep after 15 minutes without traffic and wake on the next request; the first request can be slow. The local filesystem is ephemeral, so the application must not depend on local uploaded files or a local SQLite database.
- **Supabase Free:** hosts PostgreSQL. Use the Session Pooler connection string (IPv4-compatible) as Render's `DATABASE_URL`. The Free plan includes 500 MB database storage and can pause projects after a week of low activity. Keep a backup of important data; the Free plan does not provide the same backup guarantees as paid plans.
- **Vercel Hobby:** hosts the Next.js frontend. Use the `CampusAI-Codex-Starter/frontend` directory as the project root. The frontend proxies API requests to Render through a Next.js rewrite so the browser can use same-origin HttpOnly refresh cookies.
- **Google AI Studio Gemini API:** optional provider configuration for generated answers, resume review, and interview feedback. Create a key in your own Google AI Studio project and enter it only in Render's server-side environment variables. Free-tier quotas and model availability are controlled by Google and can change.

Free plans have usage limits and are not a production availability or backup guarantee. Review the providers' current terms before launch.

## 1. Create the PostgreSQL database

1. Create a Supabase account and a new Free project.
2. Save the database password securely.
3. Open **Connect** in the Supabase project and choose the **Session pooler** connection string. Do not use the direct IPv6 database hostname if your Render service cannot reach it.
4. Copy the URI and replace the password placeholder. URL-encode special characters in the password. Keep the URI private; it contains database credentials.

The connection string should look similar to:

```text
postgresql://postgres.<project-ref>:<URL-ENCODED-PASSWORD>@<session-pooler-host>:5432/postgres?sslmode=require
```

Use the exact URI Supabase displays; host, username, and port are project-specific.

## 2. Create the Vercel frontend and reserve its URL

1. Import this GitHub repository into Vercel.
2. Set **Root Directory** to `CampusAI-Codex-Starter/frontend` and keep the Next.js framework preset.
3. Add `NEXT_PUBLIC_FILE_UPLOADS_ENABLED=false` to the Production Environment Variables.
4. Deploy once to obtain your public Vercel HTTPS origin, for example `https://campus-ai-yourname.vercel.app`. The API is not connected yet; this first deployment reserves the frontend origin needed by the backend's security configuration.

## 3. Deploy the API on Render

1. In Render, choose **New → Blueprint** and connect this GitHub repository.
2. Select the repository's `CampusAI-Codex-Starter/render.yaml` blueprint. The service root is already set to `CampusAI-Codex-Starter`.
3. When prompted, add these values:
   - `DATABASE_URL`: the Supabase Session Pooler URI.
   - `CORS_ORIGINS`: the exact Vercel HTTPS origin copied in step 2 (no path and no trailing slash).
   - `PASSWORD_RESET_URL`: that Vercel origin followed by `/reset-password`.
   - `GEMINI_API_KEY`, `GEMINI_PLACEMENT_API_KEY`, and `GEMINI_CHAT_API_KEY`: your Google AI Studio key. You may use the same key in all three fields. These are server-side secrets; never add them to the frontend.
4. Keep `FILE_UPLOADS_ENABLED=false`. Do not set a ClamAV host or enable scanning in this profile.
5. Deploy. The start command applies Alembic migrations to Supabase before launching Uvicorn. Wait for the service to report healthy.
6. Copy the deployed API origin, such as `https://campusai-api.onrender.com`.

The free blueprint uses one API web service, inline document-ingestion mode, BM25 retrieval, an ephemeral `/tmp` upload directory (unused while uploads are disabled), and no Render database, worker, or persistent disk. `QDRANT_URL` and `QDRANT_API_KEY` are optional; without them, retrieval uses BM25 over approved database chunks. Do not install `backend/requirements-ai.txt` on the free API unless you intentionally want to add vector retrieval and have checked the memory limits.

## 4. Connect the Vercel frontend to Render

1. Open the Vercel project's **Settings → Environment Variables**.
2. Add `API_PROXY_URL` with the Render API origin only, for example `https://campusai-api.onrender.com` (do not add `/api/v1`).
3. Confirm `NEXT_PUBLIC_FILE_UPLOADS_ENABLED=false` is set for Production (and Preview if needed).
4. Do not set `NEXT_PUBLIC_API_BASE_URL` in production. The Next.js rewrite uses `API_PROXY_URL` server-side and sends browser API calls through the Vercel frontend origin.
5. Redeploy the Vercel project so the rewrite and public upload setting are included in the build.

For local development, the frontend still supports `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8102`.

## 5. Create the first administrator

Public registration creates student accounts only. After registering your own account on the deployed site, open **Supabase → SQL Editor** and run this statement after replacing the email with your registered email:

```sql
UPDATE public.users
SET role = 'administrator'
WHERE lower(email) = lower('your-admin-email@example.com');
```

Then sign out and sign in again so the refreshed session contains the administrator role. Keep this administrator account private. Do not expose the Supabase service-role key or database URI to the browser.

## 6. Verify the deployment

- Open `https://<your-render-service>.onrender.com/health`; it should return a JSON status of `ok`.
- Open `/health/ready`; it should report the database as connected, vector store as not configured, and file uploads as disabled.
- Register a student account and sign in. Test the dashboard, company directory, placement-drive list, chat interface, notifications, and interview practice.
- Promote the administrator account as described above. Create a company and placement drive, and test the admin dashboard and application status workflow.
- Confirm document and resume uploads return HTTP 503 with an explicit disabled message. This is expected until malware scanning is configured.
- Add a Gemini key to each relevant server-side key variable to enable provider-backed generation. Without the keys, Gemini-dependent endpoints return a clear configuration/unavailable response; deterministic eligibility and ordinary non-AI workflows continue to work.

## Known free-tier limitations

- Render Free sleeps after 15 minutes of inactivity, has limited CPU/RAM, and has no persistent disk. Keep persistent data in Supabase, not in the API filesystem. Render's own Free PostgreSQL expires after 30 days, which is why this blueprint does not provision it.
- Supabase Free projects may pause after a week of low database activity. Reactivate a paused project from its dashboard.
- With uploads disabled, the deployed version cannot ingest policy PDFs or parse resumes. Therefore document-grounded placement answers need approved chunks already present in the database, and resume-based eligibility/application prerequisites may not be satisfiable until uploads are safely enabled.
- The free profile does not run a background worker. It selects inline ingestion mode for when uploads are later enabled on a suitable host.
- Password-reset email requires an SMTP provider. Render Free blocks outbound SMTP ports 25, 465, and 587; use a provider-supported alternative port (for example 2587 only when the chosen provider documents it) or leave email delivery unconfigured. Do not claim password-reset emails work until a real delivery test succeeds.
- Gemini quotas, free access, and supported models are set by Google and may change. A valid key does not guarantee every generation model is available at a given moment.
- Free tiers are appropriate for demonstrations and evaluation, not sensitive production student records or a guaranteed always-on campus service.

## Enabling uploads later

Only change these settings after configuring a reachable ClamAV daemon and verifying it from the deployed API's network:

1. Set `FILE_UPLOADS_ENABLED=true`.
2. Set `UPLOAD_SCAN_REQUIRED=true`, `CLAMAV_HOST`, `CLAMAV_PORT` (normally `3310`), and `CLAMAV_TIMEOUT_SECONDS`.
3. Confirm `/health/ready` reports `upload_scanner: connected`.
4. Set `NEXT_PUBLIC_FILE_UPLOADS_ENABLED=true` in Vercel and redeploy the frontend.
5. Test clean and infected test files, and confirm scanning fails closed when the scanner is stopped.

Never set `FILE_UPLOADS_ENABLED=true` with no reachable scanner. The backend production guard will reject that configuration.
