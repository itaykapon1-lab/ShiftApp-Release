"""Integration tests verifying all security controls work together on the real app.

Uses the real app from app.main with lifespan dependencies patched to no-ops
(Alembic migrations, stale job reaper, constraint registration) and DB
overridden to in-memory SQLite.
"""

from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.rate_limiter import limiter as global_limiter
from tests.fixtures.db_fixtures import create_isolated_engine, destroy_isolated_engine

import data.models  # noqa: F401


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def _real_app_infra():
    """Module-scoped: spin up the real app once for all tests in this file.

    Patches Alembic migrations, stale job reaper, constraint registration,
    and DB to in-memory SQLite.
    """
    engine = create_isolated_engine()
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    with (
        patch("app.main.command") as mock_cmd,
        patch("services.solver_service.reap_stale_jobs"),
        patch("app.main.register_core_constraints"),
    ):
        mock_cmd.upgrade = MagicMock()

        from app.main import app
        from app.db.session import get_db

        def override_get_db():
            db = factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db

        try:
            with TestClient(app) as client:
                yield client
        finally:
            app.dependency_overrides.clear()
            destroy_isolated_engine(engine)


@pytest.fixture
def real_app_client(_real_app_infra):
    """Function-scoped alias so tests get a clean name."""
    return _real_app_infra


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSecurityHeadersOnRealApp:
    def test_health_endpoint_has_security_headers(self, real_app_client):
        resp = real_app_client.get("/health")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    def test_api_endpoint_has_security_headers_on_404(self, real_app_client):
        resp = real_app_client.get("/api/v1/status/nonexistent")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    def test_root_endpoint_has_security_headers(self, real_app_client):
        resp = real_app_client.get("/")
        assert resp.status_code == 200
        assert resp.headers["X-Content-Type-Options"] == "nosniff"

    def test_production_500_includes_security_headers(self, real_app_client):
        from app.core.config import settings

        original_environment = settings.environment
        settings.environment = "production"
        try:
            with patch("services.solver_service.SolverService.start_job", side_effect=RuntimeError("boom")):
                resp = real_app_client.post("/api/v1/solve")
            assert resp.status_code == 500
            assert resp.headers["X-Content-Type-Options"] == "nosniff"
            assert resp.headers["X-Frame-Options"] == "DENY"
            assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
            assert resp.headers["Strict-Transport-Security"] == "max-age=63072000; includeSubDomains"
        finally:
            settings.environment = original_environment


class TestRateLimitOnRealApp:
    def test_solve_rate_limit_returns_429(self, real_app_client):
        """4th POST /solve within a minute should return 429.

        Temporarily re-enables the global limiter (disabled in conftest)
        and resets its state to ensure a clean rate-limit window.
        """
        global_limiter.reset()
        global_limiter.enabled = True
        try:
            with patch("services.solver_service.SolverService.start_job", return_value="job-123"):
                for _ in range(3):
                    real_app_client.post("/api/v1/solve")

                resp = real_app_client.post("/api/v1/solve")
                assert resp.status_code == 429
        finally:
            global_limiter.enabled = False
            global_limiter.reset()


class TestCorsOnRealApp:
    def test_cors_blocks_patch_on_real_app(self, real_app_client):
        resp = real_app_client.options(
            "/api/v1/solve",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "PATCH",
            },
        )
        allowed = resp.headers.get("Access-Control-Allow-Methods", "")
        assert "PATCH" not in allowed

    def test_cors_allows_post_on_real_app(self, real_app_client):
        resp = real_app_client.options(
            "/api/v1/solve",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
        allowed = resp.headers.get("Access-Control-Allow-Methods", "")
        assert "POST" in allowed
