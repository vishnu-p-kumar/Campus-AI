# User guide

## Students

1. Register with an email, then sign in. Public registration creates student accounts only.
2. Complete branch, graduation year, CGPA, backlog count and skills in the profile. Eligibility explanations identify missing values and the reviewed requirements behind a result.
3. Browse companies and open drives, review eligibility, and submit an application where eligible. Track application status on the dashboard.
4. Upload a resume for structured Gemini feedback, extracted sections and a skill-gap roadmap. You may also choose a resume file directly in the role comparison form. Common email and phone details are redacted before the extracted text is sent to Gemini; the raw file/text is not retained, while structured analysis fields are saved.
5. Ask questions about placement policies in chat. Answers link to approved source documents. If the retrieved evidence is weak or citations do not validate, CampusAI abstains and directs the student to the Placement Office. Historical dates can be asked explicitly, for example, “What was the CGPA rule in 2024?”
6. Use interview practice for technical, HR, aptitude, or coding prompts. Optionally add a role/company focus, answer multiple questions in one session, review feedback after each answer, finish the session, and inspect its private average score and round count. When Gemini is unavailable, the app labels its curated prompt and heuristic-feedback fallback; local prompts are general rather than employer-specific.

## Placement officers and administrators

An administrator creates staff accounts using `python -m app.cli create-user --email ... --name ... --role placement_officer|administrator` from `backend/` after migrations. Administrators manage accounts and review audit logs. Placement officers manage company requirements, drives, applications, outcomes, and policy documents.

Students receive a notification whenever placement staff change an application status. Staff can also send a direct notice from the admin portal; students can read notices in their notification center.

Upload policy documents with a category and optional company/academic-year/effective/expiry metadata. Review and approve them before students can retrieve them. Upload a new version and link the prior version where possible; superseded versions remain available to historical retrieval. Scanned PDF upload requires OCR to be enabled and Tesseract with its language data installed on the API host. Review analytics and benchmark data as descriptive evidence, not as hiring rankings.

After text extraction, the document table may show a keyword-based category suggestion and date phrases detected near effective/expiry labels. Treat these as review hints: they do not change the selected category or official dates, and staff must verify them against the source before approval. Queued document status refreshes automatically while the worker is processing.

## Privacy and account controls

Students can delete an individual saved chatbot conversation from the conversation list; this permanently removes its messages and citations. Students can also request account deletion from the profile area. Deletion erases the account, profile, applications, notifications, chat history, resume analysis, interview answers, sessions, and active authentication/reset tokens. Historical placement outcomes are retained for institution-level reporting with the student link removed; administrators see these as “Former student (account deleted)” without an email address. Contact the institution's placement administrator for retention or correction requests, including any additional retention requirements.

Provider-generated feedback can be wrong. Eligibility uses deterministic published rules, and final hiring or placement decisions remain with the institution and employers.
