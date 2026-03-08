"""API contract tests for import/export routes."""

import io

import pytest


pytestmark = [pytest.mark.integration, pytest.mark.contract]


def test_import_rejects_non_excel(client, test_session_id):
    response = client.post(
        "/api/v1/files/import",
        files={"file": ("data.txt", io.BytesIO(b"not excel"), "text/plain")},
        cookies={"session_id": test_session_id},
    )
    assert response.status_code == 400
