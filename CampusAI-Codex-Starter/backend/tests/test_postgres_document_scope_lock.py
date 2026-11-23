import os
from threading import Event, Thread

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.documents import _lock_document_scope


@pytest.mark.skipif(not os.getenv("CAMPUSAI_TEST_POSTGRES_URL"), reason="requires disposable PostgreSQL test service")
def test_postgres_document_scope_locks_serialize_only_matching_scopes():
    engine = create_engine(os.environ["CAMPUSAI_TEST_POSTGRES_URL"], pool_size=3, max_overflow=0)
    sessions = sessionmaker(bind=engine)
    first_acquired = Event()
    release_first = Event()
    second_acquired = Event()
    errors = []

    def hold_scope(title, acquired, release=None):
        try:
            with sessions.begin() as db:
                _lock_document_scope(db, title, 19, "2026-27")
                acquired.set()
                if release is not None and not release.wait(timeout=10):
                    raise TimeoutError("timed out waiting to release document scope lock")
        except Exception as exc:  # surface worker failures in the test thread
            errors.append(exc)
            acquired.set()

    first = Thread(target=hold_scope, args=("Shared scope", first_acquired, release_first), daemon=True)
    second = Thread(target=hold_scope, args=("Shared scope", second_acquired), daemon=True)
    try:
        first.start()
        assert first_acquired.wait(timeout=5), "first transaction failed to acquire its scope lock"
        second.start()
        assert not second_acquired.wait(timeout=0.5), "matching scope lock did not block the second transaction"
        release_first.set()
        assert second_acquired.wait(timeout=5), "second transaction did not proceed after the first committed"
        first.join(timeout=5)
        second.join(timeout=5)
        assert not first.is_alive() and not second.is_alive()
        assert not errors

        # A lock for a different title must remain independent while one scope is held.
        first_acquired.clear()
        release_first.clear()
        second_acquired.clear()
        first = Thread(target=hold_scope, args=("Scope A", first_acquired, release_first), daemon=True)
        second = Thread(target=hold_scope, args=("Scope B", second_acquired), daemon=True)
        first.start()
        assert first_acquired.wait(timeout=5)
        second.start()
        assert second_acquired.wait(timeout=5), "unrelated document scope was unnecessarily serialized"
        release_first.set()
        first.join(timeout=5)
        second.join(timeout=5)
        assert not first.is_alive() and not second.is_alive()
        assert not errors
    finally:
        release_first.set()
        first.join(timeout=5)
        if second.is_alive():
            second.join(timeout=5)
        engine.dispose()
