"""
Test Excel Template Generator.

Moved from data/parsers.py to keep production code free of test fixtures.
Generates a comprehensive Excel template for testing complex scheduling logic.

Usage:
    python scripts/generate_test_excel.py
"""

import pandas as pd
import os
import sys


def create_complex_hotel_template(filename="Grand_Hotel_Complex_Test.xlsx"):
    """
    Generates a comprehensive Excel template for testing complex scheduling logic.

    Features included:
    1. Complex Task Syntax: [Skill A + Skill B] logic, Options (OR), and Multi-staffing (+).
    2. Availability Logic: Regular, Preferred (*), and Unwanted (!).
    3. Optional Data: Missing wages handled gracefully.
    4. Constraints: Examples of Mutual Exclusion, Co-Location, and Shift Preferences.
    """

    print("Starting complex template creation...")

    # --- 1. Path Setup (Robust) ---
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    elif '__file__' in globals():
        base_dir = os.path.dirname(os.path.abspath(__file__))
    else:
        base_dir = os.getcwd()

    full_path = os.path.join(base_dir, filename)

    # --- 2. Data Construction ---

    # A. User Guide
    guide_data = [
        {"Category": "Availability", "Concept": "Bonus (*)", "Syntax": "08:00-16:00*",
         "Explanation": "Worker strongly wants this shift (+Score)."},
        {"Category": "Availability", "Concept": "Penalty (!)", "Syntax": "08:00-16:00!",
         "Explanation": "Worker strongly avoids this shift (-Score)."},
        {"Category": "Tasks", "Concept": "Multi-Skill (AND)", "Syntax": "[Waiter:4, French:3]",
         "Explanation": "One worker needs BOTH Waiter lvl 4 AND French lvl 3."},
        {"Category": "Tasks", "Concept": "Team (PLUS)", "Syntax": "[A] + [B]",
         "Explanation": "Shift requires Worker A AND Worker B (simultaneously)."},
        {"Category": "Tasks", "Concept": "Options (OR)", "Syntax": "Option 1 OR Option 2",
         "Explanation": "Solver can choose either staffing configuration."},
    ]
    df_guide = pd.DataFrame(guide_data)

    # B. Workers (Designed to fit the specific requirements)
    workers_data = [
        # 1. The Multi-Skill Candidate (Matches Option A of the complex task)
        {
            "Worker ID": "W01", "Name": "Jean-Pierre", "Wage": 60,
            "Skills": "Waiter:5, French:5, English:3",  # Overqualified for the requirement
            "Sunday": "08:00-18:00*",  # Wants to work (*)
            "Monday": "08:00-18:00",
            "Tuesday": "OFF"
        },
        # 2. Support Staff (Host)
        {
            "Worker ID": "W02", "Name": "Alice", "Wage": 40,
            "Skills": "Host:5, Cleaner:3",
            "Sunday": "08:00-16:00",
            "Monday": "08:00-16:00",
            "Tuesday": "08:00-16:00"
        },
        # 3. Support Staff (Bartender) - NO WAGE SPECIFIED (Optional Data Test)
        {
            "Worker ID": "W03", "Name": "Bob", "Wage": None,  # <--- Testing Optional Wage
            "Skills": "Bartender:4",
            "Sunday": "10:00-18:00",
            "Monday": "OFF",
            "Tuesday": "10:00-22:00"
        },
        # 4. The "Expert" Option (Matches Option B of the complex task)
        {
            "Worker ID": "K01", "Name": "Chef Gordon", "Wage": 150,
            "Skills": "Chef:5, French:5, Leadership:5",
            "Sunday": "08:00-20:00",
            "Monday": "08:00-20:00",
            "Tuesday": "OFF"
        },
        # 5. The "Complainer" (Has Negative Preference !)
        {
            "Worker ID": "S01", "Name": "Grumpy Cat", "Wage": 30,
            "Skills": "Cleaner:5",
            "Sunday": "08:00-12:00!",  # <--- Hates working Sunday mornings (!)
            "Monday": "08:00-16:00",
            "Tuesday": "08:00-16:00"
        }
    ]
    df_workers = pd.DataFrame(workers_data)
    # Fill missing columns (wage/days) handled by Pandas, but let's ensure days exist
    days = ['Wednesday', 'Thursday', 'Friday', 'Saturday']
    for day in days:
        df_workers[day] = "OFF"

    # C. Shifts (Implementing the exact logic requested)
    # Logic:
    # Option 1: (Waiter:4 + French:3) AND (Host) AND (Bartender)
    # OR
    # Option 2: (Chef:5 + French:5)

    complex_task_str = (
        "[Waiter:4, French:3] x 1 + [Host:1] x 1 + [Bartender:1] x 1 "
        "OR "
        "[Chef:5, French:5] x 1"
    )

    shifts_data = [
        # Shift 1: The Complex Requirement
        {
            "Day": "Sunday", "Shift Name": "French VIP Event",
            "Start Time": "12:00", "End Time": "16:00",
            "Tasks": complex_task_str
        },
        # Shift 2: Simple Task (Regular Constraints)
        {
            "Day": "Monday", "Shift Name": "Morning Cleaning",
            "Start Time": "08:00", "End Time": "12:00",
            "Tasks": "[Cleaner:3] x 1"
        }
    ]
    df_shifts = pd.DataFrame(shifts_data)

    # D. Constraints (All types represented)
    constraints_data = [
        # 1. Hard Constraint: Mutual Exclusion (Jean-Pierre and Bob hate each other)
        {"Type": "Mutual Exclusion", "Subject": "Jean-Pierre", "Target": "Bob", "Value": "Ban", "Strictness": "Hard"},

        # 2. Hard Constraint: Co-Location (Gordon needs Alice to translate/help)
        {"Type": "Co-Location", "Subject": "Chef Gordon", "Target": "Alice", "Value": "Require", "Strictness": "Hard"},

        # 3. Soft Constraint: Preference (Alice specifically wants the French Event)
        {"Type": "Preference", "Subject": "Alice", "Target": "French VIP Event", "Value": "Prefer",
         "Strictness": "Soft"}
    ]
    df_constraints = pd.DataFrame(constraints_data)

    # --- 3. Save to Excel ---
    try:
        with pd.ExcelWriter(full_path, engine='xlsxwriter') as writer:
            df_guide.to_excel(writer, sheet_name='User Guide', index=False)
            df_workers.to_excel(writer, sheet_name='Workers', index=False)
            df_shifts.to_excel(writer, sheet_name='Shifts', index=False)
            df_constraints.to_excel(writer, sheet_name='Constraints', index=False)

            # Formatting
            workbook = writer.book
            wrap_fmt = workbook.add_format({'text_wrap': True, 'valign': 'top'})

            writer.sheets['Workers'].set_column('C:C', 35, wrap_fmt)  # Skills wide
            writer.sheets['Shifts'].set_column('E:E', 80, wrap_fmt)  # Tasks very wide
            writer.sheets['Constraints'].set_column('A:E', 20, wrap_fmt)

        print(f"\nSUCCESS! Complex Template created.")
        print(f"Path: {full_path}")
        print("You can now run your Excel Parser against this file.")

    except Exception as e:
        print(f"\nERROR: {e}")


if __name__ == "__main__":
    create_complex_hotel_template()
