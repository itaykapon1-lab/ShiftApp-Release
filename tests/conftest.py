"""Shared pytest fixtures for database, app client, repositories, and IDs."""

import uuid

import pytest
from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from app.db.session import get_db
from api.routes import router as api_router
from api.routes_constraints_schema import router as constraints_schema_router
from repositories.sql_repo import SQLWorkerRepository, SQLShiftRepository
from tests.fixtures.db_fixtures import create_isolated_engine, destroy_isolated_engine
import data.models  # noqa: F401  — ensure all ORM models register on Base


@pytest.fixture(scope="function")
def db_engine():
    engine = create_isolated_engine()
    yield engine
    destroy_isolated_engine(engine)


@pytest.fixture(scope="function")
def db_session(db_engine):
    factory = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def id_factory():
    def _make(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:8]}"

    return _make


@pytest.fixture(scope="function")
def session_id_factory():
    def _make(_prefix: str = "test-session") -> str:
        # Must remain UUIDv4 because api.deps.get_session_id validates UUID format.
        return str(uuid.uuid4())

    return _make


@pytest.fixture(scope="function")
def test_session_id(session_id_factory):
    return session_id_factory()


@pytest.fixture(scope="function")
def client(db_session):
    app = FastAPI()
    app.include_router(api_router)
    app.include_router(constraints_schema_router, prefix="/api/v1")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        from fastapi.testclient import TestClient

        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def worker_repo(db_session, test_session_id):
    return SQLWorkerRepository(db_session, session_id=test_session_id)


@pytest.fixture(scope="function")
def shift_repo(db_session, test_session_id):
    return SQLShiftRepository(db_session, session_id=test_session_id)


@pytest.fixture(scope="function")
def sample_worker_data(id_factory):
    return {
        "worker_id": id_factory("worker"),
        "name": "John Doe",
        "attributes": {
            "skills": {"Chef": 5, "Waiter": 3},
            "availability": {
                "MON": {"timeRange": "08:00-16:00", "preference": "HIGH"},
                "TUE": {"timeRange": "08:00-16:00", "preference": "NEUTRAL"},
            },
            "wage": 25.0,
            "min_hours": 0,
            "max_hours": 40,
        },
    }


@pytest.fixture(scope="function")
def sample_shift_data(id_factory):
    return {
        "shift_id": id_factory("shift"),
        "name": "Morning Shift",
        "start_time": "2026-01-20T08:00:00",
        "end_time": "2026-01-20T16:00:00",
        "tasks_data": {
            "tasks": [
                {
                    "task_id": id_factory("task"),
                    "name": "Kitchen Service",
                    "options": [
                        {
                            "preference_score": 0,
                            "requirements": [
                                {"count": 1, "required_skills": {"Chef": 3}}
                            ],
                        }
                    ],
                }
            ]
        },
    }
