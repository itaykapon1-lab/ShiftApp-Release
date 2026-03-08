"""
Chaos Excel Generator + Parser Gauntlet
========================================

PURPOSE:
    Generate a suite of adversarial .xlsx files that stress-test the ExcelService
    (importer.py, constraint_mapper.py) to its absolute limits.

    The files are written to <project_root>/chaos_test_files/ so they can be
    manually inspected, emailed, or re-used in regression suites.

USAGE:
    # From the project root directory:
    python scripts/generate_chaos_excels.py

    The script will:
      1. Generate all .xlsx files into chaos_test_files/
      2. Feed each file into ExcelService.import_excel() through a real
         in-memory SQLite database (zero mocks).
      3. Print the parser's response (errors / warnings) for each scenario.

SCENARIOS:
    A  chaos_fake_constraints.xlsx      — Invalid / non-existent constraint types
    B  chaos_duplicate_workers.xlsx     — Duplicate Worker IDs
    C  chaos_illogical_times.xlsx       — Impossible / malformed shift times
    D  chaos_type_mismatch.xlsx         — Strings where ints/floats expected
    E  chaos_creative_destruction.xlsx  — Corner cases: empty sheets, whitespace
                                          headers, missing critical columns
"""

import os
import sys
import traceback
from io import BytesIO
from pathlib import Path

# Force UTF-8 stdout so emoji / special chars don't blow up on Windows consoles
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass  # Python < 3.7 fallback

import pandas as pd

# ---------------------------------------------------------------------------
# Bootstrap: make the project root importable regardless of where we're run from
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_DIR = PROJECT_ROOT / "chaos_test_files"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save_df_excel(filename: str, sheets: dict[str, pd.DataFrame]) -> Path:
    """Write multiple DataFrames to a single .xlsx and return the path."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / filename
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    return path


def _valid_workers() -> pd.DataFrame:
    """Return a minimal valid Workers DataFrame for use as a 'clean baseline'."""
    return pd.DataFrame([
        {
            "Worker ID": "W001", "Name": "Alice Normal", "Wage": 25.0,
            "Min Hours": 10, "Max Hours": 40,
            "Skills": "Chef:5",
            "Monday": "08:00-16:00",
            "Tuesday": "08:00-16:00",
            "Wednesday": "OFF",
            "Thursday": "OFF",
            "Friday": "OFF",
            "Saturday": "OFF",
            "Sunday": "OFF",
        },
        {
            "Worker ID": "W002", "Name": "Bob Normal", "Wage": 20.0,
            "Min Hours": 0, "Max Hours": 32,
            "Skills": "Waiter:3",
            "Monday": "10:00-18:00",
            "Tuesday": "OFF",
            "Wednesday": "10:00-18:00",
            "Thursday": "OFF",
            "Friday": "OFF",
            "Saturday": "OFF",
            "Sunday": "OFF",
        },
    ])


def _valid_shifts() -> pd.DataFrame:
    """Return a minimal valid Shifts DataFrame."""
    return pd.DataFrame([
        {
            "Day": "Monday", "Shift Name": "Morning",
            "Start Time": "08:00", "End Time": "16:00",
            "Tasks": "[Chef:3] x 1",
        },
    ])


# ===========================================================================
# SCENARIO A — The Doppelganger Constraints
# ===========================================================================

def generate_fake_constraints() -> Path:
    """
    Scenario A: chaos_fake_constraints.xlsx

    Constraints sheet contains:
      - Two rows with completely non-existent types ('Worker Invisibility',
        'max_sleep_hours') to verify the ConstraintMapper drops them gracefully.
      - One row with an intentionally bad Strictness value.
      - One VALID constraint (Mutual Exclusion) to confirm valid rows still work.
      - One row where the Type cell is empty.
    """
    constraints_df = pd.DataFrame([
        # Row 2 — valid anchor (should succeed)
        {
            "Type": "Mutual Exclusion",
            "Subject": "W001",
            "Target": "W002",
            "Strictness": "Hard",
            "Value": "",
        },
        # Row 3 — completely fabricated type
        {
            "Type": "Worker Invisibility",
            "Subject": "W001",
            "Target": "Night Shift",
            "Strictness": "Hard",
            "Value": "True",
        },
        # Row 4 — another fake type resembling a camelCase field name
        {
            "Type": "max_sleep_hours",
            "Subject": "W002",
            "Target": "",
            "Strictness": "Soft",
            "Value": "8",
        },
        # Row 5 — valid type but invalid strictness value
        {
            "Type": "Preference",
            "Subject": "W001",
            "Target": "Morning",
            "Strictness": "MAYBE",       # <- not Hard/Soft
            "Value": "Prefer",
        },
        # Row 6 — empty Type (should be flagged as warning by importer)
        {
            "Type": "",
            "Subject": "W001",
            "Target": "Morning",
            "Strictness": "Soft",
            "Value": "Prefer",
        },
    ])

    return _save_df_excel("chaos_fake_constraints.xlsx", {
        "Workers":     _valid_workers(),
        "Shifts":      _valid_shifts(),
        "Constraints": constraints_df,
    })


# ===========================================================================
# SCENARIO B — Identity Theft (Duplicate Worker IDs)
# ===========================================================================

def generate_duplicate_workers() -> Path:
    """
    Scenario B: chaos_duplicate_workers.xlsx

    Three distinct persons all claim the same Worker ID "W001".
    Verify the parser handles this without crash (upsert collision).
    """
    workers_df = pd.DataFrame([
        {
            "Worker ID": "W001", "Name": "Alice Prime", "Wage": 30.0,
            "Min Hours": 10, "Max Hours": 40,
            "Skills": "Chef:5",
            "Monday": "08:00-16:00",
            "Tuesday": "OFF", "Wednesday": "OFF",
            "Thursday": "OFF", "Friday": "OFF",
            "Saturday": "OFF", "Sunday": "OFF",
        },
        {
            # Same Worker ID, different name/wage — who wins?
            "Worker ID": "W001", "Name": "Alice Clone", "Wage": 99.0,
            "Min Hours": 0, "Max Hours": 20,
            "Skills": "Waiter:3",
            "Monday": "10:00-18:00",
            "Tuesday": "OFF", "Wednesday": "OFF",
            "Thursday": "OFF", "Friday": "OFF",
            "Saturday": "OFF", "Sunday": "OFF",
        },
        {
            # Third impostor — radically different profile
            "Worker ID": "W001", "Name": "Alice Imposter", "Wage": 5.0,
            "Min Hours": 40, "Max Hours": 10,  # MinHours > MaxHours — double chaos
            "Skills": "Ninja:99",
            "Monday": "OFF",
            "Tuesday": "OFF", "Wednesday": "OFF",
            "Thursday": "OFF", "Friday": "OFF",
            "Saturday": "OFF", "Sunday": "OFF",
        },
        # Row 5 — completely EMPTY ID
        {
            "Worker ID": "", "Name": "Ghost Worker", "Wage": 10.0,
            "Min Hours": 0, "Max Hours": 20,
            "Skills": "",
            "Monday": "08:00-16:00",
            "Tuesday": "OFF", "Wednesday": "OFF",
            "Thursday": "OFF", "Friday": "OFF",
            "Saturday": "OFF", "Sunday": "OFF",
        },
    ])

    return _save_df_excel("chaos_duplicate_workers.xlsx", {
        "Workers": workers_df,
        "Shifts":  _valid_shifts(),
    })


# ===========================================================================
# SCENARIO C — Time-Bending Shifts (Impossible/Malformed Times)
# ===========================================================================

def generate_illogical_times() -> Path:
    """
    Scenario C: chaos_illogical_times.xlsx

    A selection of pathological time values to probe every branch of the
    time validation logic in _validate_shifts_sheet().
    """
    shifts_df = pd.DataFrame([
        # Row 2 — end BEFORE start (classic inversion, FATAL)
        {
            "Day": "Monday", "Shift Name": "Inverted",
            "Start Time": "16:00", "End Time": "08:00",
            "Tasks": "[Chef:3] x 1",
        },
        # Row 3 — equal start and end (zero-duration shift, FATAL per validator)
        {
            "Day": "Tuesday", "Shift Name": "ZeroDuration",
            "Start Time": "12:00", "End Time": "12:00",
            "Tasks": "[Chef:3] x 1",
        },
        # Row 4 — non-existent hour 25:00
        {
            "Day": "Wednesday", "Shift Name": "Hour25",
            "Start Time": "25:00", "End Time": "30:00",
            "Tasks": "[Chef:3] x 1",
        },
        # Row 5 — AM/PM format (not accepted — expects HH:MM)
        {
            "Day": "Thursday", "Shift Name": "AmPmFormat",
            "Start Time": "8 AM", "End Time": "4 PM",
            "Tasks": "[Chef:3] x 1",
        },
        # Row 6 — plain word
        {
            "Day": "Friday", "Shift Name": "WordTimes",
            "Start Time": "Morning", "End Time": "Evening",
            "Tasks": "[Chef:3] x 1",
        },
        # Row 7 — decimal separator instead of colon
        {
            "Day": "Saturday", "Shift Name": "DecimalSeparator",
            "Start Time": "14.30", "End Time": "22.00",
            "Tasks": "[Chef:3] x 1",
        },
        # Row 8 — valid overnight using +24h notation (should PASS)
        {
            "Day": "Sunday", "Shift Name": "LegitOvernight",
            "Start Time": "22:00", "End Time": "30:00",  # 06:00 next day
            "Tasks": "[Chef:3] x 1",
        },
        # Row 9 — completely empty time cells
        {
            "Day": "Monday", "Shift Name": "NoTimes",
            "Start Time": None, "End Time": None,
            "Tasks": "[Chef:3] x 1",
        },
        # Row 10 — empty shift name (FATAL)
        {
            "Day": "Tuesday", "Shift Name": "",
            "Start Time": "08:00", "End Time": "16:00",
            "Tasks": "[Chef:3] x 1",
        },
        # Row 11 — unrecognised day name (WARNING)
        {
            "Day": "Funday", "Shift Name": "FunShift",
            "Start Time": "08:00", "End Time": "16:00",
            "Tasks": "[Chef:3] x 1",
        },
    ])

    return _save_df_excel("chaos_illogical_times.xlsx", {
        "Workers": _valid_workers(),
        "Shifts":  shifts_df,
    })


# ===========================================================================
# SCENARIO D — Type Sabotage (Strings Where Numbers Expected)
# ===========================================================================

def generate_type_mismatch() -> Path:
    """
    Scenario D: chaos_type_mismatch.xlsx

    Injects textual values into strictly numeric fields across all three sheets.
    Tests _parse_int_cell, float(val) guards, and Pydantic validation of
    WorkerPreferencesConfig.
    """
    workers_df = pd.DataFrame([
        # Row 2 — valid baseline
        {
            "Worker ID": "W001", "Name": "Valid Worker", "Wage": 25.0,
            "Min Hours": 0, "Max Hours": 40,
            "Skills": "Chef:5",
            "Monday": "08:00-16:00",
            "Tuesday": "OFF", "Wednesday": "OFF",
            "Thursday": "OFF", "Friday": "OFF",
            "Saturday": "OFF", "Sunday": "OFF",
        },
        # Row 3 — string in Wage
        {
            "Worker ID": "W002", "Name": "StringWage", "Wage": "High",
            "Min Hours": 0, "Max Hours": 40,
            "Skills": "Waiter:3",
            "Monday": "08:00-16:00",
            "Tuesday": "OFF", "Wednesday": "OFF",
            "Thursday": "OFF", "Friday": "OFF",
            "Saturday": "OFF", "Sunday": "OFF",
        },
        # Row 4 — string in MinHours
        {
            "Worker ID": "W003", "Name": "StringMinHours", "Wage": 20.0,
            "Min Hours": "Ten", "Max Hours": 40,
            "Skills": "Waiter:3",
            "Monday": "08:00-16:00",
            "Tuesday": "OFF", "Wednesday": "OFF",
            "Thursday": "OFF", "Friday": "OFF",
            "Saturday": "OFF", "Sunday": "OFF",
        },
        # Row 5 — string in MaxHours
        {
            "Worker ID": "W004", "Name": "StringMaxHours", "Wage": 20.0,
            "Min Hours": 0, "Max Hours": "Many",
            "Skills": "Waiter:3",
            "Monday": "08:00-16:00",
            "Tuesday": "OFF", "Wednesday": "OFF",
            "Thursday": "OFF", "Friday": "OFF",
            "Saturday": "OFF", "Sunday": "OFF",
        },
        # Row 6 — negative wage
        {
            "Worker ID": "W005", "Name": "NegativeWage", "Wage": -50.0,
            "Min Hours": 0, "Max Hours": 40,
            "Skills": "Chef:3",
            "Monday": "08:00-16:00",
            "Tuesday": "OFF", "Wednesday": "OFF",
            "Thursday": "OFF", "Friday": "OFF",
            "Saturday": "OFF", "Sunday": "OFF",
        },
    ])

    constraints_df = pd.DataFrame([
        # Worker Preferences with non-integer reward & penalty (Scenario D target)
        {
            "Type": "Worker Preferences",
            "Subject": "Reward me",     # <- should be an integer reward score
            "Target": "",
            "Strictness": "Soft",
            "Value": "True",
            "Penalty": "Zero",          # <- should be a negative integer
        },
        # Another Worker Preferences with float reward (valid in _parse_int_cell if integer)
        {
            "Type": "Worker Preferences",
            "Subject": "5.5",           # <- non-integer float
            "Target": "",
            "Strictness": "Soft",
            "Value": "True",
            "Penalty": "-10",           # <- valid
        },
        # Valid constraint alongside — ensures good rows still pass
        {
            "Type": "Mutual Exclusion",
            "Subject": "W001",
            "Target": "W002",
            "Strictness": "Hard",
            "Value": "",
            "Penalty": "",
        },
    ])

    shifts_df = pd.DataFrame([
        # Valid baseline
        {
            "Day": "Monday", "Shift Name": "Morning",
            "Start Time": "08:00", "End Time": "16:00",
            "Tasks": "[Chef:3] x 1",
        },
        # Tasks column contains a garbled value (string, not the slot-syntax)
        {
            "Day": "Tuesday", "Shift Name": "QuantifiedShift",
            "Start Time": "09:00", "End Time": "17:00",
            "Tasks": "Cook:Many",           # <- not the canonical [Skill:Lvl] x N form
        },
    ])

    return _save_df_excel("chaos_type_mismatch.xlsx", {
        "Workers":     workers_df,
        "Shifts":      shifts_df,
        "Constraints": constraints_df,
    })


# ===========================================================================
# SCENARIO E — Creative Destruction (Corner Cases)
# ===========================================================================

def generate_creative_destruction() -> Path:
    """
    Scenario E: chaos_creative_destruction.xlsx

    A workbook that weaponises otherwise overlooked edge-cases:
      1. Workers sheet is COMPLETELY EMPTY (no headers, no rows).
      2. Shifts sheet has headers but zero data rows.
      3. Constraints sheet is present but totally empty.
      4. An extra 'Fakesheet' that the parser ignores.
      5. Workers sheet (in a second workbook attempt, here reused as a single
         experiment): columns whose names have leading/trailing whitespace,
         plus a completely missing 'Monday' availability column.
    """

    # Sub-scenario E1: All three sheets present but completely empty
    empty_workers = pd.DataFrame()          # No headers, no rows
    empty_shifts  = pd.DataFrame(columns=[ # Headers only, zero rows
        "Day", "Shift Name", "Start Time", "End Time", "Tasks",
    ])
    empty_constraints = pd.DataFrame()

    # Sub-scenario E2: Workers with whitespace-padded column headers
    # (to verify that _find_column's case-insensitive strip doesn't catch only exact matches)
    whitespace_workers = pd.DataFrame([
        {
            " Worker ID ": "W001",   # Leading + trailing space in key
            " Name":       "SpaceMan",
            "Wage ":       30.0,
            " Min Hours":  0,
            "Max Hours ":  40,
            "Skills":      "Chef:5",
            # Note: DAY columns intentionally missing to see if parser handles it
        }
    ])

    # Sub-scenario E3: Shifts missing the mandatory 'Day' column entirely
    no_day_shifts = pd.DataFrame([
        {
            # 'Day' column omitted on purpose
            "Shift Name": "NoDayShift",
            "Start Time": "08:00",
            "End Time": "16:00",
            "Tasks": "[Chef:3] x 1",
        }
    ])

    # Sub-scenario E4: Constraints with a Penalty column containing NaN
    nan_penalty_constraints = pd.DataFrame([
        {
            "Type": "Avoid Consecutive Shifts",
            "Subject": "",
            "Target": "",
            "Strictness": "Soft",
            "Value": "12",
            "Penalty": float("nan"),        # <- NaN in Penalty column
        },
        {
            "Type": "Worker Preferences",
            "Subject": "10",
            "Target": "",
            "Strictness": "Soft",
            "Value": "True",
            "Penalty": float("nan"),        # <- _parse_int_cell NaN path
        },
    ])

    # We combine all sub-scenarios into ONE workbook using multiple sheets,
    # which also exercises the parser's sheet-name filtering.
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / "chaos_creative_destruction.xlsx"

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        # The parser reads only 'Workers', 'Shifts', 'Constraints' — test what happens
        # when it finds these sheets with problematic data.
        empty_workers.to_excel(writer, sheet_name="Workers", index=False)
        no_day_shifts.to_excel(writer, sheet_name="Shifts", index=False)
        nan_penalty_constraints.to_excel(writer, sheet_name="Constraints", index=False)
        # Extra sheets the parser should silently ignore
        whitespace_workers.to_excel(writer, sheet_name="Whitespace Workers", index=False)
        empty_constraints.to_excel(writer, sheet_name="Fakesheet", index=False)

    return path


# ===========================================================================
# Generator Orchestrator
# ===========================================================================

def generate_all() -> dict[str, Path]:
    """Generate all chaos files and return a mapping of name → path."""
    print("\n" + "=" * 70, flush=True)
    print("  *** CHAOS EXCEL GENERATOR ***")
    print("=" * 70)
    print(f"\nOutput directory: {OUTPUT_DIR}\n")

    generators = {
        "A — Fake Constraints":   generate_fake_constraints,
        "B — Duplicate Workers":  generate_duplicate_workers,
        "C — Illogical Times":    generate_illogical_times,
        "D — Type Mismatch":      generate_type_mismatch,
        "E — Creative Destruction": generate_creative_destruction,
    }

    results: dict[str, Path] = {}
    for label, fn in generators.items():
        try:
            path = fn()
            results[label] = path
            print(f"  [OK]  {label}")
            print(f"         -> {path}")
        except Exception as exc:
            print(f"  [FAIL] {label} -- GENERATOR FAILED: {exc}")
            traceback.print_exc()

    print(f"\n{len(results)}/{len(generators)} files generated.\n")
    return results


# ===========================================================================
# Step 3 — The Gauntlet: Feed Files Into ExcelService
# ===========================================================================

def run_gauntlet(file_paths: dict[str, Path]) -> None:
    """
    Feed each generated file into ExcelService.import_excel() using a real
    in-memory SQLite database. Print results.

    Contract assertions:
      - The call MUST NOT raise an unhandled Python exception.
      - It MUST either return a dict (success/warning) or raise
        ImportValidationException (structured 400-equivalent).
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from data.models import Base
    from services.excel_service import ExcelService, ImportValidationException

    print("\n" + "=" * 70, flush=True)
    print("  [GAUNTLET] PARSER GAUNTLET -- feeding chaos files into ExcelService")
    print("=" * 70)

    for scenario_label, file_path in file_paths.items():
        print(f"\n{'─' * 70}")
        print(f"  Scenario: {scenario_label}")
        print(f"  File:     {file_path.name}")
        print(f"{'─' * 70}")

        # Isolated in-memory SQLite DB per scenario
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        session_id = f"chaos_test_{scenario_label[:8].lower().replace(' ', '_')}"

        try:
            file_bytes = file_path.read_bytes()
            service = ExcelService(db, session_id)
            result = service.import_excel(file_bytes)

            # ── Outcome: HTTP 200-equivalent ──────────────────────────────────
            print(f"  [PASS] OUTCOME: IMPORT SUCCEEDED (no fatal errors)")
            print(f"         Workers: {result.get('workers', '?')}  |  "
                  f"Shifts: {result.get('shifts', '?')}")

            warnings = result.get("warnings", [])
            if warnings:
                print(f"  [WARN] {len(warnings)} warning(s):")
                for w in warnings:
                    print(f"         - {w}")
            else:
                print("  [INFO] No warnings returned.")

        except ImportValidationException as exc:
            # ── Outcome: structured validation failure (HTTP 400-equivalent) ──
            print(f"  [REJECT] OUTCOME: IMPORT REJECTED (ImportValidationException)")

            payload = exc.validation_result.to_dict()

            errors = payload.get("errors", [])
            if errors:
                print(f"  [ERROR] {len(errors)} validation error(s):")
                for e in errors:
                    loc = f"[{e['sheet']}"
                    if e.get("row"):
                        loc += f", row {e['row']}"
                    if e.get("field"):
                        loc += f", field '{e['field']}'"
                    loc += "]"
                    print(f"         - {loc}: {e['message']}")

            warnings = payload.get("warnings", [])
            if warnings:
                print(f"  [WARN] {len(warnings)} validation warning(s):")
                for w in warnings:
                    loc = f"[{w['sheet']}"
                    if w.get("row"):
                        loc += f", row {w['row']}"
                    if w.get("field"):
                        loc += f", field '{w['field']}'"
                    loc += "]"
                    print(f"         - {loc}: {w['message']}")

        except Exception as exc:
            # ── Outcome: UNHANDLED exception — this is a BUG ── ────────────
            print(f"  [BUG!!!] OUTCOME: UNHANDLED EXCEPTION -- THIS IS A BUG!")
            print(f"           {type(exc).__name__}: {exc}")
            traceback.print_exc()

        finally:
            db.close()
            engine.dispose()

    print(f"\n{'=' * 70}")
    print("  Gauntlet complete. Review results above.")
    print("=" * 70 + "\n")


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    generated = generate_all()

    if generated:
        run_gauntlet(generated)
    else:
        print("No files were generated — nothing to test.")
        sys.exit(1)
