# Architecture and module boundaries

## Runtime

The browser runs the Next.js App Router frontend. The frontend calls the versioned FastAPI API. SQLAlchemy stores users, profiles, requirements and their versions, drives and applications, documents/chunks, chat, interview/resume analysis, audit events, evaluations, notifications, and placement outcomes. Alembic owns schema changes. SQLite is the default local store; PostgreSQL is configured with `DATABASE_URL` for deployments. `EVIDENCE_MINIMUM_SCORE` controls the heuristic chat abstention cutoff; its 0.35 default is provisional and should only be changed after held-out evaluation on manually reviewed institutional questions.

The document workflow scans uploads, then either stores source files in `UPLOAD_DIRECTORY` and extracts inline, or stores source bytes and a job atomically in PostgreSQL when `DOCUMENT_INGESTION_MODE=queued`. The worker claims queued/expired jobs with PostgreSQL row locks and leases, extracts PDF/DOCX/text, retries transient failures, and clears the source payload on terminal completion. Extraction chunks along paragraph and sentence boundaries, retains recognizable uppercase/numbered section headings, and uses bounded whitespace splitting for long unpunctuated passages; this is structure-aware chunking rather than a learned semantic segmenter. Chunk section metadata is persisted and shown in citations. Inline ingestion flushes chunk rows before constructing vector payloads so each Qdrant point refers to its authoritative database chunk ID. A deterministic keyword classifier and labelled-date scanner produce staff-visible category/date suggestions; they never override metadata supplied by staff and the match score is not a probability. Document version chains are scoped by trimmed title, company, and academic year; PostgreSQL transaction-scoped advisory locks serialize allocation and approval for each scope across API workers. A pending review blocks the next version, and approval validates that only the current approved version can be superseded. Documents remain pending until a placement officer/admin approves them. BM25 uses database chunks. When configured, Sentence Transformers produce embeddings for Qdrant; dense and BM25 rankings are fused by reciprocal rank fusion and optionally reranked by a cross encoder. Retrieval only exposes approved current documents for current questions; historical questions can include superseded versions constrained by effective and expiry dates. Chat validates citation references, associates sentence citations with retrieved sources, checks numeric answer values against cited text, and abstains when a numeric value is unsupported. Conflicting active CGPA/backlog values produce a deterministic cited abstention. An optional NLI cross encoder can compare each cited sentence against its cited evidence and fail closed; it is disabled by default and requires a compatible model and institution-specific validation. Neither this model score nor the heuristic evidence score establishes semantic accuracy without labelled evaluation. Short follow-ups are expanded with the conversation's prior user question for retrieval; prior turns are marked untrusted and are never counted as policy evidence. Gemini is only called on the API server.

Eligibility is evaluated with Python rules and reviewed, source-linked requirements. The linked source document must still be approved at the time of checking; superseded or rejected sources force manual verification. The LLM does not determine eligibility. Missing student data or unreviewed requirements are reported for manual review. Resume and skill suggestions support the student and are not hiring decisions.

## API map

The interactive OpenAPI reference at `/docs` is authoritative. Routes use `/api/v1` by default.

| Area | Routes | Access |
|---|---|---|
| Authentication | `/auth/register`, `/login`, `/refresh`, `/logout`, `/me`, `/password-reset/*` | Public endpoints are throttled; role checks after login |
| Student | `/students/me`, `/students/`, `/dashboard/` | Students access their own profile; staff can list students |
| Companies and drives | `/companies/`, `/placement-drives/`, `/placement-drives/applications`, `/placement-drives/eligible-students` | Read access to students; changes and roster access to placement staff |
| Documents | `/documents/`, `/upload`, `/{id}/approve`, `/{id}/reject` | Placement officer/admin |
| Chat | `/chat/`, `/chat/conversations*` | Authenticated; conversation ownership enforced |
| Resume/interview | `/resumes/*`, `/interviews/*` | Authenticated student-owned workflows |
| Notifications | `/notifications/*` | Authenticated user-owned records |
| Administration | `/admin/users`, `/analytics` (including persisted chat-message usage), `/audit-logs`, `/applications`, `/placement-records`, `/evaluation-runs` | Admin only for access control/audit; staff for placement analytics |
| Research evaluation | `/evaluation/runs` | Placement officer/admin |
| System | `/health`, `/health/ready` | Public health; database, configured vector-store, and upload-scanner readiness |

## Provider behavior and boundaries

- No Gemini key: chat returns a provider-unavailable API error when adequate evidence needs generation; unsupported questions still safely abstain. Interview practice uses clearly local, curated prompts and heuristic feedback.
- No Qdrant/model dependencies: retrieval uses BM25. The `requirements-ai.txt` install is optional and model files download from the model provider when first used.
- No SMTP: password reset request keeps an enumeration-safe response, but the UI reports email delivery is not configured; an operator must configure SMTP.
- Scanned PDF OCR is an opt-in extraction path using PyMuPDF and host-installed Tesseract (`OCR_ENABLED`, `OCR_LANGUAGES`, `OCR_DPI`). It remains unverified against a real Tesseract installation here. Queued ingestion is implemented with a separate Render worker; PostgreSQL multi-worker load and Render startup remain unverified.
- Authentication endpoints use an atomic PostgreSQL/SQLite fixed-window counter keyed by an HMAC of the client address. This shares the 20 requests/minute limit across API workers using the same database, stores no raw address, and fails closed with 503 if the limiter database operation fails. Other database dialects are not supported for this limiter.
- The upload scanner accepts only ClamAV `stream: OK` replies, rejects detections, and fails closed on timeout, connection error, or invalid reply whenever a host is configured. Production Render configuration requires scanning and does not accept uploads until `CLAMAV_HOST` is set.
- Gemini receives the user question, conversation history and retrieved passages as JSON data marked untrusted in the prompt. Provider errors are converted to a generic 503 at the API boundary. Mocked tests cover this contract; live Gemini output and provider-side prompt handling still require credentialed integration and safety evaluation.
- Dense Qdrant retrieval applies category, company, academic-year, version and approval filters, plus effective/expiry date filters for historical queries. SQL rechecks the returned chunk IDs and date window before fusion, so the vector index is not trusted as the source of document truth.
- Hindi/Kannada keyword expansion is provided for some placement-policy terms. It does not guarantee fluent translated generation or parity; this needs native-speaker evaluation.

## Security notes

Passwords use Argon2. Access JWTs are held in frontend memory and refresh tokens are stored as HttpOnly cookies. Role checks run on API routes. Password-reset tokens are single use and rate-limited; account and conversation data is user-scoped. Uploads are size/type/content checked, use generated storage names, and can be scanned through ClamAV INSTREAM before processing. Audit records avoid storing resume contents and tokens. Production requires a strong JWT secret, HTTPS, `UPLOAD_SCAN_REQUIRED=true` with a reachable ClamAV daemon, and narrow `CORS_ORIGINS`.
