# CampusAI and Placement Query Bot

This repository contains two related applications:

1. **CampusAI** — a full-stack placement intelligence platform for students and placement teams.
2. **Placement Query Bot** — the FastAPI backend that provides the original placement FAQ, SQL, and out-of-scope routing flow. CampusAI imports this backend from the adjacent `placement-query-bot-deploy/` directory, and it can also run as a standalone API.

The projects are kept together because the CampusAI placement assistant uses the Placement Query Bot's routing and answer flow. CampusAI adds authenticated conversations and uses the same bot backend with approved administrator uploads, administrator-managed company information, and the signed-in candidate's notifications as additional knowledge sources.

This is a student learning project. It is not an official BNMIT service.

## Repository layout

```text
Campus-AI/
├── CampusAI-Codex-Starter/       CampusAI frontend, API, migrations, docs, tests
├── placement-query-bot-deploy/   Placement Query Bot API, data, and FAQ corpus
├── README.md                     Project overview and repository guide
└── run.md                        Step-by-step local setup and run instructions
```

## CampusAI capabilities

- Student registration, sign-in, role-based access, dashboards, and administrator-managed student profiles.
- Company profiles, placement drives, deterministic eligibility checks, applications, and outcomes.
- Administrator upload, approval, versioning, and retrieval of PDF, DOCX, and text policy documents.
- Placement Assistant using the Placement Query Bot FAQ / SQL / out-of-scope routing flow. It can answer from approved uploads, administrator-managed company and drive records, and candidate notifications with user-scoped access.
- Candidate notification lookup for unread/read status and full messages by title. Chat lookups do not mark notifications as read.
- Resume review and role skill guidance, plus interview preparation. Gemini credentials are used server-side for resume and interview features; placement answers use Groq through the Placement Query Bot.
- Research tools for evaluating retrieval and answer quality using manually reviewed data.

Simple assistant answers remain paragraphs; pointwise answers remain lists. Source panels and source markers are hidden in the chat display. See [`CampusAI-Codex-Starter/README.md`](CampusAI-Codex-Starter/README.md), [`CampusAI-Codex-Starter/PROJECT_STATUS.md`](CampusAI-Codex-Starter/PROJECT_STATUS.md), and the guides under [`CampusAI-Codex-Starter/docs/`](CampusAI-Codex-Starter/docs/).

## Placement Query Bot capabilities

- FastAPI endpoints: `GET /health`, `GET /usage`, and `POST /query`.
- Original FAQ, SQL, and out-of-scope routing, with a daily query limit.
- FAQ retrieval over the supplied placement knowledge files, with local retrieval fallback behavior when the embedding model is unavailable.
- Optional JSONBin-backed shared query counters and query logging.
- Supplied placement report data and import script.

See [`placement-query-bot-deploy/README.md`](placement-query-bot-deploy/README.md) for bot-specific details and data notes.

## Requirements

- Python 3.11 or newer (Python 3.11 is the tested target).
- Node.js 20 or newer and npm for the CampusAI web application.
- Git.
- A Groq API key to generate placement assistant answers.
- Gemini API credentials for Gemini-backed resume and interview features.

SQLite is used by default for local CampusAI development. PostgreSQL, Qdrant, Docker, ClamAV, SMTP, and JSONBin are optional integrations depending on the features being run. Provider keys are optional for starting the application, but the related AI features will not generate answers without their configuration.

## Quick start

Read [`run.md`](run.md) for full setup, configuration, and launch instructions. Clone with `git clone --recurse-submodules <repository-url>` so the Placement Query Bot directory is present. In short, install the CampusAI backend and bot dependencies into the same Python environment, copy the sample environment files, apply migrations, start FastAPI, then start the Next.js frontend. The integrated bot runs inside the CampusAI API process; its standalone API is optional.

The integrated local URLs in [`run.md`](run.md) are:

- CampusAI frontend: `http://localhost:3101`
- CampusAI API: `http://localhost:8103`
- CampusAI API documentation: `http://localhost:8103/docs`
- Standalone Placement Query Bot API (optional): `http://localhost:8000`

## Configuration and secrets

Copy `.env.example` files to the corresponding local `.env` / `.env.local` files as described in [`run.md`](run.md). Keep real credentials out of Git. The root `.gitignore` excludes environment files, local databases, uploaded files, virtual environments, dependency folders, and generated caches. Only example environment files belong in version control.

Key variables include:

| Variable | Used for |
| --- | --- |
| `GROQ_API_KEY` | Placement Query Bot and CampusAI placement answer generation |
| `GEMINI_API_KEY` | Resume review and role-skill guidance |
| `GEMINI_CHAT_API_KEY` | Interview practice |
| `DATABASE_URL` or `POSTGRES_*` | CampusAI database; SQLite is the local default |
| `QDRANT_URL`, `QDRANT_API_KEY` | Optional/deployed vector retrieval |
| `JSONBIN_BIN_ID`, `JSONBIN_API_KEY` | Optional shared bot usage counter and logging |

Never put provider credentials in a `NEXT_PUBLIC_*` variable or frontend code.

## Deployment

Deployment templates are provided in [`CampusAI-Codex-Starter/render.yaml`](CampusAI-Codex-Starter/render.yaml), [`CampusAI-Codex-Starter/frontend/vercel.json`](CampusAI-Codex-Starter/frontend/vercel.json), and [`placement-query-bot-deploy/render.yaml`](placement-query-bot-deploy/render.yaml). They require separate service accounts, secrets, and infrastructure configuration. See [`CampusAI-Codex-Starter/docs/DEPLOYMENT.md`](CampusAI-Codex-Starter/docs/DEPLOYMENT.md). These files are configuration templates; their presence does not mean that a deployment is currently active.

## Verification

From the repository root, backend checks can be run with:

```powershell
python -m pytest CampusAI-Codex-Starter/backend/tests -q
```

Frontend lint is run from `CampusAI-Codex-Starter/frontend`:

```powershell
npm.cmd run lint
```

Additional PostgreSQL, browser, and research checks are documented in the project README and research guide. Some end-to-end checks use temporary services or may invoke configured providers; consult the relevant instructions before running them.

## Project documentation

- [`run.md`](run.md) — detailed local run guide for both applications.
- [`CampusAI-Codex-Starter/README.md`](CampusAI-Codex-Starter/README.md) — CampusAI features and development notes.
- [`CampusAI-Codex-Starter/docs/ARCHITECTURE.md`](CampusAI-Codex-Starter/docs/ARCHITECTURE.md) — system architecture.
- [`CampusAI-Codex-Starter/docs/USER_GUIDE.md`](CampusAI-Codex-Starter/docs/USER_GUIDE.md) — user and administrator workflows.
- [`CampusAI-Codex-Starter/docs/DEPLOYMENT.md`](CampusAI-Codex-Starter/docs/DEPLOYMENT.md) — deployment configuration.
- [`CampusAI-Codex-Starter/PROJECT_STATUS.md`](CampusAI-Codex-Starter/PROJECT_STATUS.md) — implementation and verification status.
- [`placement-query-bot-deploy/README.md`](placement-query-bot-deploy/README.md) — standalone bot details and placement data notes.
