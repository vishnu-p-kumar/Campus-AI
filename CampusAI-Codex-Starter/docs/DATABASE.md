# Database and migrations

SQLAlchemy models are in `backend/app/models.py`; Alembic environment and revisions are under `backend/migrations`. The SQLite default is intended for development. PostgreSQL is the deployment database. Set `DATABASE_URL` before applying migrations; the application accepts `postgresql://` and normalizes it to the psycopg 3 driver.

From the repository root:

```powershell
python -m alembic -c backend/alembic.ini upgrade head
python -m alembic -c backend/alembic.ini check
```

Create a new revision after changing a model, inspect the generated file carefully, then test upgrade and downgrade against a disposable local database:

```powershell
python -m alembic -c backend/alembic.ini revision --autogenerate -m "describe change"
```

Never run schema downgrades or destructive data migrations against a production database without a reviewed backup and explicit operational approval. Render's configured build applies forward migrations before starting the service; review the revision and take a database backup before each production rollout.

The model groups cover identity/roles, student profiles, companies and source-linked requirement versions, drives/applications/outcomes, document versions/chunks, conversations/messages, resume and skill-gap summaries, interview sessions, notifications, password reset and refresh token state, audit logs, and evaluation run metadata. Resume text is parsed in memory and only analysis summaries are persisted. Avoid adding raw personal data to logs or evaluation datasets.

Local PostgreSQL and Qdrant are described in `docker-compose.dev.yml`. The compose file binds PostgreSQL to host port 5433. The root `.gitignore` excludes local SQLite databases, virtual environments, package build directories, uploads, and secrets.
