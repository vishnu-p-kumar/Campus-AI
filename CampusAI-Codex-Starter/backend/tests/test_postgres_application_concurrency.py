import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker


@pytest.mark.skipif(not os.getenv("CAMPUSAI_TEST_POSTGRES_URL"), reason="requires disposable PostgreSQL test service")
def test_postgres_simultaneous_application_submission_returns_one_success():
    from app.api.placement import persist_application
    from app.models import Application, Company, PlacementDrive, User

    engine = create_engine(os.environ["CAMPUSAI_TEST_POSTGRES_URL"], pool_size=16, max_overflow=0)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    email = f"{uuid4()}@example.edu"
    company_name = f"Application Race {uuid4()}"
    user_id = drive_id = company_id = None
    for model in (User, Company, PlacementDrive, Application):
        model.__table__.create(engine, checkfirst=True)
    try:
        with sessions.begin() as session:
            user = User(email=email, full_name="Application Test", password_hash="unused", role="student")
            company = Company(name=company_name)
            session.add_all([user, company])
            session.flush()
            drive = PlacementDrive(company_id=company.id, title="Race Test", role="Engineer")
            session.add(drive)
            session.flush()
            user_id, drive_id, company_id = user.id, drive.id, company.id

        def submit(_index):
            with sessions() as session:
                try:
                    row = persist_application(session, user_id, drive_id)
                    return ("created", row.id)
                except HTTPException as exc:
                    return ("conflict", exc.status_code)

        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(submit, range(32)))

        assert sum(result[0] == "created" for result in results) == 1
        assert sum(result == ("conflict", 409) for result in results) == 31
    finally:
        with engine.begin() as connection:
            if user_id is not None and drive_id is not None:
                connection.execute(delete(Application).where(Application.student_user_id == user_id,
                                                              Application.drive_id == drive_id))
            if drive_id is not None:
                connection.execute(delete(PlacementDrive).where(PlacementDrive.id == drive_id))
            if company_id is not None:
                connection.execute(delete(Company).where(Company.id == company_id))
            if user_id is not None:
                connection.execute(delete(User).where(User.id == user_id))
        engine.dispose()


@pytest.mark.skipif(not os.getenv("CAMPUSAI_TEST_POSTGRES_URL"), reason="requires disposable PostgreSQL test service")
def test_postgres_application_status_updates_serialize_and_reload():
    from app.api.placement import lock_application_for_update
    from app.models import Application, Company, PlacementDrive, User

    engine = create_engine(os.environ["CAMPUSAI_TEST_POSTGRES_URL"], pool_size=3, max_overflow=0)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    email = f"{uuid4()}@example.edu"
    company_name = f"Status Race {uuid4()}"
    user_id = company_id = drive_id = application_id = None
    for model in (User, Company, PlacementDrive, Application):
        model.__table__.create(engine, checkfirst=True)
    first_locked = Event()
    release_first = Event()
    second_started = Event()
    second_acquired = Event()
    errors = []
    try:
        with sessions.begin() as session:
            user = User(email=email, full_name="Status Test", password_hash="unused", role="student")
            company = Company(name=company_name)
            session.add_all([user, company])
            session.flush()
            drive = PlacementDrive(company_id=company.id, title="Status Race", role="Engineer")
            session.add(drive)
            session.flush()
            application = Application(student_user_id=user.id, drive_id=drive.id, status="applied")
            session.add(application)
            session.flush()
            user_id, company_id, drive_id, application_id = user.id, company.id, drive.id, application.id

        def change_first():
            try:
                with sessions.begin() as session:
                    row = lock_application_for_update(session, application_id)
                    row.status = "screening"
                    first_locked.set()
                    if not release_first.wait(timeout=10):
                        raise TimeoutError("timed out waiting to release the application row lock")
            except Exception as exc:
                errors.append(exc)
                first_locked.set()

        def read_second():
            second_started.set()
            try:
                with sessions.begin() as session:
                    row = lock_application_for_update(session, application_id)
                    second_acquired.set()
                    return row.status
            except Exception as exc:
                errors.append(exc)
                second_acquired.set()
                return None

        first = Thread(target=change_first, daemon=True)
        first.start()
        assert first_locked.wait(timeout=5)
        with ThreadPoolExecutor(max_workers=1) as pool:
            second_future = pool.submit(read_second)
            assert second_started.wait(timeout=5)
            assert not second_acquired.wait(timeout=0.5), "the second status update bypassed the application row lock"
            release_first.set()
            assert second_acquired.wait(timeout=5)
            assert second_future.result(timeout=5) == "screening"
        first.join(timeout=5)
        assert not first.is_alive()
        assert not errors
    finally:
        release_first.set()
        with engine.begin() as connection:
            if application_id is not None:
                connection.execute(delete(Application).where(Application.id == application_id))
            if drive_id is not None:
                connection.execute(delete(PlacementDrive).where(PlacementDrive.id == drive_id))
            if company_id is not None:
                connection.execute(delete(Company).where(Company.id == company_id))
            if user_id is not None:
                connection.execute(delete(User).where(User.id == user_id))
        engine.dispose()
