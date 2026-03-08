"""Slow performance test for large Excel import workloads."""

import os
from io import BytesIO

import pandas as pd
import pytest

from services.excel_service import ExcelService


pytestmark = [pytest.mark.slow]


def test_excel_import_1000_rows(db_session, test_session_id):
    if os.getenv("RUN_SLOW_TESTS") != "1":
        pytest.skip("Set RUN_SLOW_TESTS=1 to run volume test")

    workers = []
    shifts = []
    for i in range(1000):
        workers.append(
            {
                "Worker ID": f"W{i}",
                "Name": f"Worker {i}",
                "Wage": 20,
                "Min Hours": 0,
                "Max Hours": 40,
                "Skills": "Chef:5",
                "Monday": "08:00-16:00",
            }
        )
        shifts.append(
            {
                "Day": "Monday",
                "Shift Name": f"Shift {i}",
                "Start Time": "08:00",
                "End Time": "16:00",
                "Tasks": "[Chef:3] x 1",
            }
        )

    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        pd.DataFrame(workers).to_excel(writer, sheet_name="Workers", index=False)
        pd.DataFrame(shifts).to_excel(writer, sheet_name="Shifts", index=False)
    out.seek(0)

    service = ExcelService(db_session, test_session_id)
    result = service.import_excel(out.read())
    assert result["workers"] >= 1000
    assert result["shifts"] >= 1000

