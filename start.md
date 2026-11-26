# Start the complete project

Use this file whenever you want to run CampusAI on your computer. The complete application needs two running services: the CampusAI API and the CampusAI frontend. Placement Assist is included inside the API and does not need its own server.

These commands are for Windows PowerShell and assume you are in the project root folder (the folder containing `CampusAI-Codex-Starter` and `placement-query-bot-deploy`).

## A. First-time setup

### 1. Install the required software

Install Python 3.11, Node.js 20 or newer, and Git. Clone the repository if it is not already on your computer:

```powershell
git clone https://github.com/vishnu-p-kumar/Placement-Query.git
Set-Location Placement-Query
```

If you already have the project, open PowerShell in its root folder instead.

### 2. Install backend requirements

Create one Python environment for CampusAI and the integrated Placement Query Bot. Both requirements files must be installed in this same environment:

```powershell
py -3.11 -m venv CampusAI-Codex-Starter/.venv
CampusAI-Codex-Starter/.venv/Scripts/python.exe -m pip install --upgrade pip
CampusAI-Codex-Starter/.venv/Scripts/python.exe -m pip install -r CampusAI-Codex-Starter/backend/requirements.txt -r placement-query-bot-deploy/requirements.txt
```

### 3. Create and configure the backend `.env`

Create the local backend configuration file:

```powershell
Copy-Item CampusAI-Codex-Starter/backend/.env.example CampusAI-Codex-Starter/backend/.env
```

Edit `CampusAI-Codex-Starter/backend/.env` and add the API keys for the features you will use:

```dotenv
GROQ_API_KEY=your_groq_api_key
GEMINI_API_KEY=your_resume_and_skill_gemini_key
GEMINI_CHAT_API_KEY=your_interview_gemini_key
GEMINI_MODEL=gemini-3.5-flash-lite
GEMINI_FALLBACK_MODELS=gemini-3.1-flash-lite
```

Keep these keys private in the backend `.env`. Do not put them in frontend files or commit `.env` files. `GROQ_API_KEY` enables Placement Assist, `GEMINI_API_KEY` enables resume and skill analysis, and `GEMINI_CHAT_API_KEY` enables interview preparation. Resume and skill analysis use the model settings shown above.

The default local configuration uses SQLite; PostgreSQL and Qdrant are optional for the basic local run.

### 4. Create the frontend `.env.local` and install packages

```powershell
Copy-Item CampusAI-Codex-Starter/frontend/.env.example CampusAI-Codex-Starter/frontend/.env.local
Set-Location CampusAI-Codex-Starter/frontend
npm.cmd ci
Set-Location ..\..
```

The example frontend configuration connects to the API at `http://localhost:8103`. Keep the frontend and API on `localhost` so sign-in cookies work correctly.

### 5. Create or update the local database schema

Run database migrations from the project root:

```powershell
CampusAI-Codex-Starter/.venv/Scripts/python.exe -m alembic -c CampusAI-Codex-Starter/backend/alembic.ini upgrade head
```

## B. Start the complete project

Start the API and frontend in separate PowerShell windows. Keep both windows open while using CampusAI.

### Terminal 1: start the backend API

Open PowerShell in the project root, enter the CampusAI project directory, and run the API with its virtual environment:

```powershell
Set-Location CampusAI-Codex-Starter
$pythonPath = Join-Path $PWD ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonPath)) { $pythonPath = Join-Path $PWD ".venv311\Scripts\python.exe" }
if (-not (Test-Path $pythonPath)) { throw "CampusAI Python environment not found. Create .venv using the setup steps above." }
& $pythonPath -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8103 --reload
```

Wait until Uvicorn reports that the application has started. The API is at `http://localhost:8103`; its health check is `http://localhost:8103/health` and its readiness check is `http://localhost:8103/health/ready`.

In a second PowerShell window, verify all saved history delete routes in the running API. OpenAPI confirms registration; unauthenticated DELETE probes must return 401 (route exists, sign-in required), not 404. These probes cannot delete data because they send no credentials.

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

If port 8103 is already occupied, stop the previous CampusAI API with Ctrl+C before starting the updated one. The frontend `.env.local` should point to `http://localhost:8103`.

### Terminal 2: start the web frontend

Open a second PowerShell window in the project root and run:

```powershell
Set-Location CampusAI-Codex-Starter/frontend
npm.cmd run dev
```

Open the application at **http://localhost:3101**.

### Sign in

Use your existing account. If this is a new local database and you do not have an administrator account, open a third PowerShell window in the project root and run:

```powershell
Set-Location CampusAI-Codex-Starter
.\.venv\Scripts\python.exe -m app.cli create-user --email officer@example.edu --name "Placement Officer" --role administrator
```

Enter a password when asked, then sign in at `http://localhost:3101`. Create the administrator only once per database.

## C. Start the project on later runs

After the first-time setup is complete, you do not need to reinstall packages or recreate `.env` files each time. Start two PowerShell windows in the project root:

**Window 1 — API:**

```powershell
Set-Location CampusAI-Codex-Starter
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8103 --reload
```

**Window 2 — frontend:**

```powershell
Set-Location CampusAI-Codex-Starter/frontend
npm.cmd run dev
```

Then open `http://localhost:3101`. If you pulled new code that adds a database migration, run the migration command from section A.5 before starting the API.

## D. Placement Assist

Placement Assist is part of CampusAI. Open it after signing in; it uses the placement bot backend inside the CampusAI API. Do not start a separate bot server for normal CampusAI use. If Placement Assist says it is unavailable, check that `GROQ_API_KEY` is present in `CampusAI-Codex-Starter/backend/.env`, confirm the bot dependencies were installed into `CampusAI-Codex-Starter/.venv`, then restart the API terminal.

## E. Stop the project

In each terminal running the API or frontend, press `Ctrl+C`. Your local database and uploaded files remain on your computer.

For optional standalone bot, Docker, maintenance, and troubleshooting commands, see [run.md](run.md).
