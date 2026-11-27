# BNMIT Placement Query Bot API

## Run locally

This project uses the **Groq API** (not xAI Grok). Create a `.env` file in the project root and set:

```dotenv
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=openai/gpt-oss-120b
```

Install dependencies and launch the API:

```bash
python -m pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Keep `.env` private. Configure `GROQ_API_KEY` and optionally `GROQ_MODEL` in the deployment environment. The API provides `GET /health`, `GET /usage`, and `POST /query` (`{"question":"..."}`).

The response includes `answer`, `route` (`faq`, `sql`, `other`, or `limit`), the routing score, and daily usage counts. The original FAQ retrieval, SQL data query, out-of-scope handling, shared 25-query daily limit, midnight reset, and query logging are retained. FAQ retrieval uses the local sentence-transformer/Chroma index when its model is cached and falls back to TF-IDF over the same text corpus when the model is unavailable. CampusAI shows the shared usage count and preserves its existing authenticated chat history.

## 2026 placement data

The project includes BNMIT's [official 2022–26 placement report](https://www.bnmit.org/wp-content/uploads/2026/08/Placement-Report-2022-26-1.pdf), available from its [Hiring Statistics page](https://www.bnmit.org/department-of-training-placement/hiring-statistics/). The report states that 2026 placements are still in progress.

- `resources/placements_2026.csv` contains the company-level product, service, and off-campus placement rows.
- `resources/placement_summary_2026.csv` preserves BNMIT's cohort-wide summary figures separately.
- Run `python import_2026_placements.py` to load both files into `placement_data.db`.

The report's company-level on-campus rows do not reconcile with its official single-offer summary (277 detailed on-campus placements versus 319 reported). The database keeps both records as published: use `placement_summary` for official cohort totals and `placements` for company-level details. For salary ranges, the numeric `Salary LPA` field uses the range midpoint; `Salary LPA Reported` keeps the published range.

This project now serves the placement bot backend as an API. CampusAI's existing authenticated Placement Assistant screen uses this same backend flow; this project no longer includes a separate chat interface.

---

### Related project
The full CampusAI application is in the sibling `CampusAI-Codex-Starter/` directory. Its authenticated Placement Assistant imports this API from the current directory and keeps the FAQ / SQL / out-of-scope routing flow. The repository root `run.md` explains how to launch the integrated application and this standalone API.

---

### 🧠 Features
- Groq API-powered responses
- Daily shared query limits (via JSONBin API)
- Auto reset every midnight
- FastAPI query endpoint for CampusAI and standalone deployments
- Independent bot queries; CampusAI stores conversations under the signed-in account

---

### 👨‍💻 Developer
**Vinay S** ([vins.techn@gmail.com](mailto:vins.techn@gmail.com))

> This chatbot is a **student project for learning** and is **not an official BNMIT bot**.
