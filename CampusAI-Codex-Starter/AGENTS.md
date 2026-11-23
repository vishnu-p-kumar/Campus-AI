# Codex instructions for CampusAI

- Read `PROJECT_SPEC.md` and `PROJECT_STATUS.md` before implementing work.
- Work in small, reviewable milestones; do not attempt the whole system in one task.
- Inspect existing files before editing; preserve working code.
- Use Next.js App Router + TypeScript for the frontend and FastAPI + Python for the backend.
- Keep secrets server-side. Never expose Gemini, database, JWT or Qdrant credentials in browser code.
- Use deterministic Python rules for placement eligibility; Gemini may explain but must not decide eligibility.
- Ground college-specific chatbot answers in approved retrieved documents; abstain when evidence is insufficient.
- Use PostgreSQL for structured data and Qdrant for deployed vector storage. Local ChromaDB may be used for development only.
- Add tests for every important feature. Run relevant tests and fix failures before completing a task.
- Never fabricate placement data, citations, benchmark results or deployment URLs.
- Ask before destructive operations, production database changes, paid service usage or deployment.
- Update `PROJECT_STATUS.md` and `README.md` after each milestone.
- At the end of each task report files changed, commands run, tests passed/failed and remaining issues.
