"""App fixture helpers."""

from fastapi.testclient import TestClient

from app.main import app
from app.db.session import get_db


def create_test_client(db_session):
    """Create a TestClient with database dependency override."""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)

