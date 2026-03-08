"""
Excel Data Manager Module.

This module acts as the Adapter between the raw Excel file and the Domain Models.
It implements the IDataManager protocol and handles complex parsing logic for:
- Advanced Task Syntax (AND/OR/PLUS combinations)
- Rich Availability Syntax (Time windows with Preference/Aversion flags)
- Data Normalization and Validation
"""

import re
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
from typing import List, Dict, Optional, Any

# --- Domain Imports ---
# Assuming the domain files exist as defined in previous steps
from domain.worker_model import Worker
from domain.shift_model import Shift, TimeWindow
from domain.task_model import Task, TaskOption, Requirement
from solver.constraints.static_soft import WorkerPreferencesConstraint

# --- Configuration Constants ---
PREF_SCORE_BONUS = 10    # Value for '*'
PREF_SCORE_PENALTY = -10 # Value for '!'
DEFAULT_SKILL_LEVEL = 5  # Fallback if level is missing

class ExcelDataManager:
    """
    Concrete implementation of IDataManager backed by an Excel file.
    Loads data into memory upon initialization.
    """

    def __init__(self, file_path: str, start_date: Optional[datetime] = None):
        """
        Args:
            file_path: Path to the .xlsx file.
            start_date: Reference date for 'Sunday'. Defaults to the upcoming Sunday.
        """
        self.file_path = file_path
        self.start_date = start_date or self._get_next_sunday()

        # Internal In-Memory Cache
        self._workers: Dict[str, Worker] = {}
        self._shifts: Dict[str, Shift] = {}
        self._constraints_data: List[Dict] = [] # Raw constraints for the Solver

        # Trigger Load
        self._load_data()

    def _get_next_sunday(self) -> datetime:
        """Calculates the date of the upcoming Sunday (at 00:00)."""
        today = datetime.now()
        days_ahead = (6 - today.weekday() + 7) % 7
        return (today + timedelta(days=days_ahead)).replace(hour=0, minute=0, second=0, microsecond=0)

    def _load_data(self):
        """Main orchestration method for loading Excel sheets."""
        try:
            print(f"📂 Loading data from: {self.file_path}")
            xls = pd.ExcelFile(self.file_path)

            # 1. Parse Workers
            if 'Workers' in xls.sheet_names:
                self._parse_workers(pd.read_excel(xls, 'Workers'))
            else:
                raise ValueError("Missing 'Workers' sheet in Excel file.")

            # 2. Parse Shifts
            if 'Shifts' in xls.sheet_names:
                self._parse_shifts(pd.read_excel(xls, 'Shifts'))
            else:
                raise ValueError("Missing 'Shifts' sheet in Excel file.")

            # 3. Parse Constraints (Optional but recommended)
            if 'Constraints' in xls.sheet_names:
                self._parse_constraints(pd.read_excel(xls, 'Constraints'))

            print(f"✅ Data Loaded Successfully:")
            print(f"   - Workers: {len(self._workers)}")
            print(f"   - Shifts:  {len(self._shifts)}")
            print(f"   - Constraints: {len(self._constraints_data)}")

        except FileNotFoundError:
            print(f"❌ Error: File not found at {self.file_path}")
            raise
        except Exception as e:
            print(f"❌ Critical Parsing Error: {e}")
            raise

    # =========================================================================
    # Parsing Logic: Workers
    # =========================================================================

    def _parse_workers(self, df: pd.DataFrame):
        days_map = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

        for idx, row in df.iterrows():
            try:
                # Basic ID Validation
                w_id = str(row['Worker ID']).strip()
                if not w_id or w_id.lower() == 'nan':
                    continue

                # Handle Optional Wage (NaN -> 0.0)
                wage_val = row.get('Wage')
                wage = 0.0
                if pd.notna(wage_val):
                    try:
                        wage = float(wage_val)
                    except ValueError:
                        pass # Keep 0.0 if invalid

                # Create Worker Entity
                worker = Worker(
                    name=str(row['Name']).strip(),
                    worker_id=w_id,
                    wage=wage,
                    min_hours=int(row.get('Min Hours', 0)),
                    max_hours=int(row.get('Max Hours', 40))
                )

                # Parse Skills: "Cook:5, French:3"
                skills_str = str(row.get('Skills', ''))
                if skills_str.lower() != 'nan':
                    for part in skills_str.split(','):
                        self._parse_single_skill(worker, part)

                # Parse Availability (Days columns)
                for day_idx, day_name in enumerate(days_map):
                    if day_name in df.columns:
                        val = str(row[day_name])
                        self._parse_availability_cell(worker, val, day_idx)

                self._workers[w_id] = worker

            except Exception as e:
                print(f"⚠️ Error parsing worker row {idx}: {e}")

    def _parse_single_skill(self, worker: Worker, raw_skill: str):
        """Parses 'SkillName:Level' or just 'SkillName'."""
        raw_skill = raw_skill.strip()
        if not raw_skill: return

        name = raw_skill
        level = DEFAULT_SKILL_LEVEL

        if ':' in raw_skill:
            parts = raw_skill.split(':')
            name = parts[0]
            try:
                level = int(parts[1])
            except ValueError:
                print(f"   ⚠️ Invalid skill level in '{raw_skill}' for {worker.name}. Defaulting to {level}.")

        # Normalize Name (Title Case)
        worker.set_skill_level(self._normalize_text(name), level)

    def _parse_availability_cell(self, worker: Worker, value: str, day_offset: int):
        """Parses '08:00-16:00', 'OFF', or variants with * / !"""
        if value.upper() in ['OFF', 'NAN', '', 'NONE']:
            return

        # Check for Preferences
        score = 0
        clean_value = value

        if '*' in value:
            score = PREF_SCORE_BONUS
            clean_value = value.replace('*', '')
        elif '!' in value:
            score = PREF_SCORE_PENALTY
            clean_value = value.replace('!', '')

        clean_value = clean_value.strip()

        try:
            start_str, end_str = clean_value.split('-')

            # Date Calculation
            base_date = self.start_date + timedelta(days=day_offset)
            start_dt = self._combine_dt(base_date, start_str)
            end_dt = self._combine_dt(base_date, end_str)

            # Handle Overnight (End < Start)
            if end_dt <= start_dt:
                end_dt += timedelta(days=1)

            # Add Hard Constraint (Availability)
            window = TimeWindow(start_dt, end_dt)
            worker.add_availability(window.start, window.end)

            # Add Soft Constraint (Preference) if applicable
            if score != 0:
                worker.add_preference(window, score)

        except Exception:
            print(f"   ⚠️ Invalid time format '{value}' for worker {worker.name}")

    # =========================================================================
    # Parsing Logic: Shifts & Tasks
    # =========================================================================

    def _parse_shifts(self, df: pd.DataFrame):
        days_map = {'Sunday': 0, 'Monday': 1, 'Tuesday': 2, 'Wednesday': 3,
                    'Thursday': 4, 'Friday': 5, 'Saturday': 6}

        for idx, row in df.iterrows():
            try:
                day_name = self._normalize_text(row['Day'])
                if day_name not in days_map: continue

                # Time Window
                offset = days_map[day_name]
                base_date = self.start_date + timedelta(days=offset)
                start_dt = self._combine_dt(base_date, str(row['Start Time']))
                end_dt = self._combine_dt(base_date, str(row['End Time']))

                if end_dt <= start_dt:
                    end_dt += timedelta(days=1)

                shift = Shift(str(row['Shift Name']), TimeWindow(start_dt, end_dt))

                # Task Parsing
                raw_task = str(row['Tasks'])
                if raw_task.lower() != 'nan':
                    # Create a main task container for this shift
                    task_container = Task(f"Task_{shift.shift_id}")
                    self._parse_complex_task_string(task_container, raw_task)
                    shift.add_task(task_container)

                self._shifts[shift.shift_id] = shift

            except Exception as e:
                print(f"⚠️ Error parsing shift row {idx}: {e}")

    def _parse_complex_task_string(self, task: Task, task_str: str):
        """
        Parses logic: "Option A OR Option B"
        Where Option A = "Req 1 + Req 2"
        Where Req 1 = "[Skill:Lvl] x Count"
        """
        # Step 1: Split Options (OR)
        options = task_str.split('OR')

        for opt_str in options:
            task_option = TaskOption()

            # Step 2: Split Simultaneous Requirements (+)
            reqs = opt_str.split('+')

            for req_str in reqs:
                # Step 3: Extract Content and Count using Regex
                # Pattern: "[ Content ] x Count"
                match = re.search(r"\[(.*?)\]\s*x\s*(\d+)", req_str)

                if match:
                    content_str = match.group(1).strip()
                    count = int(match.group(2))

                    # Step 4: Parse Internal Skills (AND logic)
                    required_skills_dict = {}

                    if content_str:
                        # Split "Waiter:5, French:3"
                        skill_items = content_str.split(',')
                        for item in skill_items:
                            item = item.strip()
                            if ':' in item:
                                s_name, s_lvl = item.split(':')
                                required_skills_dict[self._normalize_text(s_name)] = int(s_lvl)
                            else:
                                required_skills_dict[self._normalize_text(item)] = 1

                    # Add to Option
                    task_option.add_requirement(count, required_skills_dict)

            # Only add option if it has valid requirements
            if task_option.requirements:
                task.add_option(task_option)

    # =========================================================================
    # Parsing Logic: Constraints
    # =========================================================================

    def _parse_constraints(self, df: pd.DataFrame):
        """Loads constraints into raw list for later processing by Solver."""
        for _, row in df.iterrows():
            self._constraints_data.append(row.to_dict())

    # =========================================================================
    # Helpers
    # =========================================================================

    def _normalize_text(self, text: Any) -> str:
        """Standardizes strings (Title Case, stripped)."""
        if not isinstance(text, str): return str(text)
        return text.strip().title()

    def _combine_dt(self, date_obj: datetime, time_val: Any) -> datetime:
        """Robustly combines date and time (handles str vs datetime.time)."""
        if isinstance(time_val, str):
            # Excel might export "08:00:00" or just "08:00"
            clean = time_val.strip()
            # Simple fallback if pandas didn't convert it
            try:
                parts = clean.split(':')
                t = time(int(parts[0]), int(parts[1]))
            except:
                # Fallback for weird formats, defaulting to 00:00
                t = time(0,0)
        else:
            # It's already a time object (or datetime)
            t = time_val if isinstance(time_val, time) else time_val.time()

        return datetime.combine(date_obj.date(), t)

    # =========================================================================
    # IDataManager Protocol Implementation
    # =========================================================================

    def get_eligible_workers(self, time_window: TimeWindow, required_skills: Optional[Dict[str, int]] = None) -> List[Worker]:
        """
        Returns workers who are available AND meet skill thresholds.
        """
        eligible = []
        for worker in self._workers.values():
            # 1. Hard Constraint: Availability
            if not worker.is_available_for_shift(time_window):
                continue

            # 2. Hard Constraint: Skills (Threshold Check)
            if required_skills:
                meets_skills = True
                for s_name, min_lvl in required_skills.items():
                    # Normalize key for lookup
                    norm_name = self._normalize_text(s_name)
                    if not worker.has_skill_at_level(norm_name, min_lvl):
                        meets_skills = False
                        break

                if not meets_skills:
                    continue

            eligible.append(worker)

        return eligible

    def get_all_shifts(self) -> List[Shift]:
        return list(self._shifts.values())

    def get_all_workers(self) -> List[Worker]:
        return list(self._workers.values())

    def get_worker(self, worker_id: str) -> Optional[Worker]:
        return self._workers.get(worker_id)

    def get_shift(self, shift_id: str) -> Optional[Shift]:
        return self._shifts.get(shift_id)

    def get_statistics(self) -> Dict[str, int]:
        return {
            "workers": len(self._workers),
            "shifts": len(self._shifts),
            "constraints": len(self._constraints_data)
        }

    def build_constraint_registry(self):
        """Builds a ConstraintRegistry from the parsed constraints data."""
        from solver.constraints.registry import ConstraintRegistry
        from solver.constraints.config import ConstraintConfig
        from solver.constraints.base import ConstraintType
        from solver.constraints.dynamic import MutualExclusionConstraint, CoLocationConstraint
        from solver.constraints.static_soft import WorkerPreferencesConstraint

        
        registry = ConstraintRegistry()
        registry.add_core_constraints()
        registry.register(WorkerPreferencesConstraint())
        # Parse constraints from Excel data
        mutual_exclusions = []
        colocations = []
        
        for constraint_row in self._constraints_data:
            constraint_type = constraint_row.get('Type', '').strip()
            strictness_str = constraint_row.get('Strictness', 'Hard').strip()
            strictness = ConstraintType.HARD if strictness_str.lower() == 'hard' else ConstraintType.SOFT
            
            if constraint_type == 'Mutual Exclusion':
                subject = constraint_row.get('Subject', '').strip()
                target = constraint_row.get('Target', '').strip()
                if subject and target:
                    mutual_exclusions.append({
                        'worker_a': subject,
                        'worker_b': target,
                        'strictness': strictness
                    })
            elif constraint_type == 'Co-Location':
                subject = constraint_row.get('Subject', '').strip()
                target = constraint_row.get('Target', '').strip()
                if subject and target:
                    colocations.append({
                        'leader': subject,
                        'follower': target,
                        'strictness': strictness
                    })
        
        # Build registry using ConstraintConfig pattern
        config = ConstraintConfig(
            mutual_exclusions=mutual_exclusions,
            colocations=colocations
        )
        
        # Register dynamic constraints
        for rule in mutual_exclusions:
            constraint = MutualExclusionConstraint(
                worker_a_id=rule['worker_a'],
                worker_b_id=rule['worker_b'],
                strictness=rule['strictness']
            )
            registry.register(constraint)
        
        for rule in colocations:
            constraint = CoLocationConstraint(
                worker_a_id=rule['leader'],
                worker_b_id=rule['follower'],
                strictness=rule['strictness']
            )
            registry.register(constraint)
        
        return registry

    # Write methods are stubs in this File-Read-Only implementation
    def add_worker(self, worker: Worker) -> None: pass
    def add_shift(self, shift: Shift) -> None: pass
    def update_worker(self, worker: Worker) -> None: pass
    def refresh_indices(self) -> None: pass
