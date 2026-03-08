"""Small builders for Excel test payloads."""

from io import BytesIO

import pandas as pd


def build_minimal_valid_excel() -> bytes:
    """Return a minimal valid workbook in bytes."""
    out = BytesIO()

    workers = pd.DataFrame(
        [
            {
                "Worker ID": "W001",
                "Name": "Alice",
                "Wage": 20,
                "Min Hours": 0,
                "Max Hours": 40,
                "Skills": "Chef:5",
                "Monday": "08:00-16:00",
            }
        ]
    )
    shifts = pd.DataFrame(
        [
            {
                "Day": "Monday",
                "Shift Name": "Morning",
                "Start Time": "08:00",
                "End Time": "16:00",
                "Tasks": "[Chef:3] x 1",
            }
        ]
    )

    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        workers.to_excel(writer, sheet_name="Workers", index=False)
        shifts.to_excel(writer, sheet_name="Shifts", index=False)

    out.seek(0)
    return out.read()

