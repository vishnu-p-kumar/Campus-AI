# CampusAI Demo and Presentation Guide

## Local demo setup

Use the current commands in `README.md`. Start with SQLite to keep the demonstration independent of external services. Create a student account through the UI. Create a staff account with the CLI from `backend/`; after login, add a company and drive, configure a reviewed eligibility rule, and upload/approve a policy document. Gemini, SMTP, and Qdrant can be omitted; identify the corresponding fallback behavior during the demo.

## Suggested demonstration workflow

1. Open the public landing page and show the API health status.
2. Register a student, complete the academic profile, and show profile completion.
3. As staff, create a company, source-link and review its requirements, and create an open placement drive.
4. Return as the student, view the eligibility explanation, and apply to an eligible drive. Show the application tracker.
5. As staff, upload a readable PDF/DOCX/TXT policy, review metadata, and approve it. Explain that pending or rejected documents are excluded from current chat retrieval.
6. Ask chat a question answerable from the uploaded policy; show citation title/page/version. Ask an unsupported question to show safe abstention. Ask a historical-year question only if the dataset includes correctly dated superseded versions.
7. Upload a sample resume with consent and no real contact details. Show extracted skills and a job skill-gap roadmap. Do not display another person’s resume.
8. Start technical, HR, aptitude, or coding interview practice, answer two rounds, inspect structured feedback, complete the session, and show the personal average-score history.
9. As administrator, show pending/approved documents, role/user management, analytics, audit history, and evaluation runs. Use only real records created during the demo; do not present them as institutional statistics.
10. Explain the three research variants and report that results remain pending until a manually annotated dataset is evaluated.

## Presentation outline

1. Placement information problem and verified motivation.
2. Project objectives and scope.
3. Architecture and technology choices.
4. Data model and role/ownership security.
5. Deterministic eligibility and source-linked explanations.
6. Document approval, versions, effective dates, and temporal retrieval.
7. BM25 + dense retrieval, RRF, reranking, citations, and abstention.
8. Resume skill gap and interview practice modules.
9. Research comparison design and annotation protocol.
10. Actual test results and experiment metrics (show only measured values).
11. Limitations, privacy, language evaluation, and future work.
12. Live demonstration and questions.

## Demo preparation checklist

- Seed no fake institutional statistics. If no representative corpus exists, label created data as demo data.
- Verify local API health and frontend build before presenting.
- Ensure no secrets, personal resumes, tokens, or private student data are visible in screenshots or recordings.
- If Gemini is enabled, confirm model access and usage cost limits; otherwise use the explicit local fallback paths.
- Reset demo accounts through supported account controls after the event, following the institution’s retention policy.
- Keep a recorded walkthrough that avoids exposing credentials or unreviewed data.
