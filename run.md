# Run the complete CampusAI project

This repository contains the CampusAI web application and the Placement Query Bot backend it uses for Placement Assist. For the normal application, run the CampusAI API and frontend. The bot is loaded by that API in the same Python environment; it does not need a separate server.

Commands below use Windows PowerShell. Run each numbered terminal section in its own PowerShell window where noted. Do not put API keys in frontend environment files or commit `.env` files.

## 1. Prerequisites and checkout

Install:

- Git
- Python 3.11
- Node.js 20 or newer (npm is included)

Clone the repository and enter its root directory:

```powershell
git clone https://github.com/vishnu-p-kumar/Placement-Query.git
Set-Location Placement-Query
```

`Campus-AI` is an older URL for this same repository and redirects to `Placement-Query`.

## 2. Create the backend environment

From the repository root, create one virtual environment for CampusAI and its integrated placement assistant. Install both requirement files into that same environment:

```powershell
py -3.11 -m venv CampusAI-Codex-Starter/.venv
CampusAI-Codex-Starter/.venv/Scripts/python.exe -m pip install --upgrade pip
CampusAI-Codex-Starter/.venv/Scripts/python.exe -m pip install -r CampusAI-Codex-Starter/backend/requirements.txt -r placement-query-bot-deploy/requirements.txt
```

The placement bot dependencies are required even though you run only the CampusAI API. Optional semantic embedding and reranking packages can be installed with:

```powershell
CampusAI-Codex-Starter/.venv/Scripts/python.exe -m pip install -r CampusAI-Codex-Starter/backend/requirements-ai.txt
```

## 3. Configure backend settings

Create the backend settings file:

```powershell
Copy-Item CampusAI-Codex-Starter/backend/.env.example CampusAI-Codex-Starter/backend/.env
```

Open `CampusAI-Codex-Starter/backend/.env` and set the provider keys for features you want to use:

```dotenv
GROQ_API_KEY=your_groq_api_key
GEMINI_API_KEY=your_resume_and_skill_gemini_key
GEMINI_CHAT_API_KEY=your_interview_gemini_key
GEMINI_MODEL=gemini-3.5-flash-lite
GEMINI_FALLBACK_MODELS=gemini-3.1-flash-lite
```

Placement Assist uses `GROQ_API_KEY`. Resume analysis and skill guidance use `GEMINI_API_KEY`; interview preparation uses `GEMINI_CHAT_API_KEY`. Gemini keys stay on the backend. Use real keys in your local `.env` only; never commit them or add them to `frontend/.env.local`.

For local development, the example configuration uses SQLite, so PostgreSQL and Qdrant are not needed to start the project. Without a Qdrant service, retrieval can use the configured local lexical fallback. To use PostgreSQL or Qdrant, configure their connection settings in the backend `.env` and start those services as described under Optional Docker services.

## 4. Apply database migrations

From the repository root:

```powershell
CampusAI-Codex-Starter/.venv/Scripts/python.exe -m alembic -c CampusAI-Codex-Starter/backend/alembic.ini upgrade head
```

Run migrations again after pulling code that adds a database migration.

## 5. Start the CampusAI API

Open **Terminal 1** at the repository root, enter the CampusAI project directory, and run the API with the CampusAI virtual environment:

```powershell
Set-Location CampusAI-Codex-Starter
$pythonPath = Join-Path $PWD ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonPath)) { $pythonPath = Join-Path $PWD ".venv311\Scripts\python.exe" }
if (-not (Test-Path $pythonPath)) { throw "CampusAI Python environment not found. Create .venv using the setup steps above." }
& $pythonPath -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8103 --reload
```

Keep this terminal open. The API and its integrated Placement Query Bot are available at:

- API: `http://localhost:8103`
- API docs: `http://localhost:8103/docs`
- Liveness check: `http://localhost:8103/health`
- Dependency readiness check: `http://localhost:8103/health/ready`

The readiness response may identify optional services, such as Qdrant or upload scanning, that are not configured locally.

After the API starts, verify that the running process has all three delete routes. OpenAPI confirms registration; unauthenticated DELETE probes must return 401 (the routes exist but require sign-in), not 404. These probes cannot delete data because they send no credentials.

```powershell
$schema = Invoke-RestMethod http://127.0.0.1:8103/openapi.json
$requiredRoutes = @("/api/v1/resumes/history", "/api/v1/resumes/history/{analysis_id}", "/api/v1/resumes/skill-gap/history/{gap_id}")
foreach ($path in $requiredRoutes) {
    $route = $schema.paths.PSObject.Properties | Where-Object Name -eq $path
    if (-not $route -or "delete" -notin $route.Value.PSObject.Properties.Name) { throw "DELETE $path is missing from the OpenAPI served at http://127.0.0.1:8103. Stop the API and start the updated CampusAI backend from this workspace." }
}
foreach ($path in @("/api/v1/resumes/history", "/api/v1/resumes/history/0", "/api/v1/resumes/skill-gap/history/0")) {
    try { Invoke-WebRequest -Uri "http://127.0.0.1:8103$path" -Method Delete -ErrorAction Stop | Out-Null; throw "DELETE $path unexpectedly succeeded without authentication." }
    catch { if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 401) { continue }; throw "DELETE $path returned $($_.Exception.Message), expected 401. The API instance or proxy is not serving the updated route." }
}
"All saved result DELETE routes are present and protected by authentication."
```

If port 8103 is already occupied, stop the old CampusAI API terminal with Ctrl+C before starting this one. Confirm the frontend `.env.local` still points to `http://localhost:8103`.

## 6. Install and start the CampusAI frontend

Open **Terminal 2** at the repository root. Create the frontend environment file and install the locked npm dependencies:

```powershell
Copy-Item CampusAI-Codex-Starter/frontend/.env.example CampusAI-Codex-Starter/frontend/.env.local
Set-Location CampusAI-Codex-Starter/frontend
npm.cmd ci
npm.cmd run dev
```

Keep this terminal open and visit `http://localhost:3101`. The frontend environment example points to the API at `http://localhost:8103`. Use `localhost` for both addresses so the authentication refresh cookie remains same-site.

## 7. Create an administrator account

Open **Terminal 3** at the repository root and run:

```powershell
Set-Location CampusAI-Codex-Starter
.\.venv\Scripts\python.exe -m app.cli create-user --email officer@example.edu --name "Placement Officer" --role administrator
```

Enter a password when prompted, then sign in at `http://localhost:3101`. Replace the example email and name with the account details you want. The supported roles are `administrator` and `placement_officer`.

## 8. Use Placement Assist

Sign in to CampusAI and open Placement Assist. It calls the Placement Query Bot backend inside the CampusAI API process, using the same Python environment created in step 2. Make sure `GROQ_API_KEY` is set in `CampusAI-Codex-Starter/backend/.env` and restart Terminal 1 after changing environment settings.

Do not launch the standalone bot server for the integrated CampusAI chat. The standalone server below is only for running and checking the bot API independently.

## Optional: run the standalone Placement Query Bot API

Use this only when you want to call the bot without the CampusAI frontend. Open another PowerShell window at the repository root:

```powershell
py -3.11 -m venv placement-query-bot-deploy/.venv
placement-query-bot-deploy/.venv/Scripts/python.exe -m pip install --upgrade pip
placement-query-bot-deploy/.venv/Scripts/python.exe -m pip install -r placement-query-bot-deploy/requirements.txt
Copy-Item placement-query-bot-deploy/.env.example placement-query-bot-deploy/.env
```

Set `GROQ_API_KEY` in `placement-query-bot-deploy/.env`, then start the server:

```powershell
Set-Location placement-query-bot-deploy
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Standalone endpoints:

- Health: `http://localhost:8000/health`
- Usage: `http://localhost:8000/usage`
- API docs: `http://localhost:8000/docs`
- Query endpoint: `POST http://localhost:8000/query` with JSON such as `{"question":"What placement training is available?"}`

## Optional: start PostgreSQL and Qdrant with Docker

Docker Desktop is required. From `CampusAI-Codex-Starter`, start the development services:

```powershell
Set-Location CampusAI-Codex-Starter
docker compose -f docker-compose.dev.yml up -d
```

Configure the matching PostgreSQL `DATABASE_URL` and Qdrant settings in `backend/.env`, then apply migrations from the repository root using step 4. Local SQLite is simpler for a first run and does not require these services.

From the repository root, stop the containers:

```powershell
Set-Location ..
docker compose -f CampusAI-Codex-Starter/docker-compose.dev.yml down
```

Use `docker compose ... down -v` only when you intend to delete the local database and vector-store volumes, including their data.

## Common maintenance commands

Run backend tests from the repository root:

```powershell
CampusAI-Codex-Starter/.venv/Scripts/python.exe -m pytest CampusAI-Codex-Starter/backend/tests -q
```

Check frontend lint and make a production build:

```powershell
Set-Location CampusAI-Codex-Starter/frontend
npm.cmd run lint
npm.cmd run build
```

To serve that production build locally, stop the development server first, then run:

```powershell
npm.cmd start
```

## Stop the project

Press `Ctrl+C` in each terminal running Uvicorn or Next.js. Stop optional Docker services with the command above.

## Troubleshooting

- **Placement assistant says it is unavailable:** confirm `GROQ_API_KEY` is set in `CampusAI-Codex-Starter/backend/.env`; install both backend and bot requirements into the CampusAI `.venv`; restart the API and inspect its terminal for a sanitized dependency or configuration error.
- **Backend fails to start:** activate/use the CampusAI `.venv`, confirm the commands were run from the repository root, and apply database migrations.
- **Frontend cannot reach the API or sign-in is lost after refresh:** use `localhost` for both frontend and API, confirm the API is running on port `8103`, and check `NEXT_PUBLIC_API_BASE_URL` in `frontend/.env.local` and `CORS_ORIGINS` in `backend/.env`.
- **Resume analysis says the backend could not connect to Gemini:** allow outbound HTTPS from the backend host to `generativelanguage.googleapis.com:443`. A browser connection is not required; the request comes from FastAPI. Check the API terminal for sanitized `network_connectivity` diagnostics. Keep the configured resume models as `gemini-3.5-flash-lite` followed by `gemini-3.1-flash-lite`.
- **Resume analysis or interview generation is unavailable for another reason:** check the appropriate server-side Gemini key, provider availability and rate limits, then restart the API after editing `.env`. Do not add unapproved models to the fallback list.
- **Readiness is not ready:** open `/health/ready` and inspect the API terminal. `/health` only checks that the process is responding; readiness also checks configured dependencies.
- **Next.js reports a missing generated chunk:** stop any other Next.js process using this project, remove the generated `CampusAI-Codex-Starter/frontend/.next` directory, then run `npm.cmd run dev` again.

For architecture, deployment and current verification notes, see [README.md](README.md), [CampusAI-Codex-Starter/README.md](CampusAI-Codex-Starter/README.md), and [CampusAI-Codex-Starter/PROJECT_STATUS.md](CampusAI-Codex-Starter/PROJECT_STATUS.md).
