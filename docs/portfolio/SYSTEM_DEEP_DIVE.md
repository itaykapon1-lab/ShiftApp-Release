# ShiftApp - System Deep Dive

> Technical Architecture Defense Document

This document serves as a comprehensive technical grilling session, designed to demonstrate deep understanding of the system's internals, trade-offs, and architectural decisions.

---

## Section A: Critical System Analysis (Stress Test Questions)

### A1. What happens when the solver runs out of memory with 5000 workers and 500 shifts?

**Answer:**

The constraint matrix size is approximately O(W × S × T × R) where:
- W = workers (5000)
- S = shifts (500)
- T = tasks per shift (~3 average)
- R = roles/skill combinations (~5)

This creates ~37.5 million potential decision variables. Each OR-Tools `IntVar` consumes approximately 100 bytes, so the variable matrix alone would consume ~3.5GB.

**Current behavior:**
- The `ProcessPoolExecutor` worker process would hit memory limits
- Python raises `MemoryError`, caught by the `try/except` in `run_solver_in_process()`
- Job is marked FAILED with error message in database
- Main API process remains unaffected (process isolation)

**Mitigation strategies I would implement:**
1. **Pre-flight check**: Estimate matrix size before solving, reject jobs exceeding threshold
2. **Problem decomposition**: Solve by department/time-block, then merge
3. **Variable pruning**: Only create X_vars for workers who pass availability check (current implementation already does this)
4. **Streaming variable creation**: Use OR-Tools' lazy variable instantiation

**Code reference:** `solver/solver_engine.py:73-191` (variable creation loop)

---

### A2. What happens if two concurrent requests try to run the solver for the same session?

**Answer:**

This is explicitly handled by the `SolverService._has_active_job()` guard:

```python
# services/solver_service.py:377-390
active_job = (
    db.query(SolverJobModel)
    .filter_by(session_id=session_id)
    .filter(SolverJobModel.status.in_([JobStatus.PENDING.value, JobStatus.RUNNING.value]))
    .first()
)
```

**Current behavior:**
- First request creates a job and submits to ProcessPoolExecutor
- Second request queries database, finds PENDING/RUNNING job
- Returns `ValueError: Session already has an active job ({job_id})`
- API returns 400 Bad Request with the existing job_id

**Race condition window:**
There's a ~5ms window between `create_job()` and job status being queryable. In extremely rare cases, two requests could both pass the guard. However:
- Jobs would execute sequentially in ProcessPoolExecutor (single worker per session constraint)
- Results would overwrite, but database has unique job_id
- No data corruption, just wasted compute

**Code reference:** `services/solver_service.py:393-430`

---

### A3. How does the system handle a worker with 100 overlapping availability windows?

**Answer:**

The `Worker.is_available_for_shift()` method iterates through all availability windows:

```python
# domain/worker_model.py (conceptual)
def is_available_for_shift(self, shift_window: TimeWindow) -> bool:
    for avail_window in self.availability:
        if avail_window.start <= shift_window.start and avail_window.end >= shift_window.end:
            return True
    return False
```

**Performance impact:**
- With 100 windows × 500 shifts × 5000 workers = 250 million comparisons during index building
- The `SessionDataManagerAdapter._build_availability_index()` runs once at adapter creation
- After indexing, lookups are O(1) by time window + O(skills) for filtering

**Current limitations:**
- No deduplication of overlapping windows (if Sunday 8-16 appears twice, both are stored)
- No window merging (8-12 and 10-16 stored separately, not merged to 8-16)

**Improvement opportunity:** Add `Worker.merge_availability()` method to consolidate overlapping windows during Excel import.

**Code reference:** `services/session_adapter.py:50-68`

---

### A4. What happens if the database connection drops during a background solve?

**Answer:**

Each process creates its own database connection via `SessionLocal()`:

```python
# services/solver_service.py:251
db: Session = SessionLocal()
try:
    # ... solver logic ...
finally:
    db.close()
```

**Failure modes:**

1. **Connection fails at start:**
   - `SessionLocal()` raises `OperationalError`
   - Caught by outer `try/except` in `run_solver_in_process()`
   - `SolverJobStore.update_job_failed()` attempted (may also fail)
   - Job stuck in PENDING state (requires manual cleanup)

2. **Connection drops mid-solve:**
   - Solver completes in memory (no DB needed during optimization)
   - `update_job_completed()` creates fresh connection
   - If that fails, result is lost but can be retried

3. **Connection drops during result write:**
   - Transaction uncommitted
   - Job stays in RUNNING state
   - Requires manual status update or timeout mechanism (not implemented)

**Missing resilience:** No job timeout mechanism. A stuck RUNNING job blocks new solves for that session indefinitely.

**Code reference:** `services/solver_service.py:236-318`

---

### A5. Can a malicious Excel file cause arbitrary code execution?

**Answer:**

**Risk assessment: LOW** for code execution, **MEDIUM** for DoS.

**Protections in place:**
1. **openpyxl library**: Doesn't execute macros or formulas, only reads cell values
2. **pandas read_excel**: Similarly safe, extracts data only
3. **Temporary file handling**: Files saved to system temp directory with `.xlsx` extension
4. **File deletion**: Temp file deleted in `finally` block

**Remaining attack vectors:**

1. **XML bomb (Billion Laughs):**
   - Excel files are ZIP archives containing XML
   - openpyxl has entity expansion limits, but no explicit check in our code
   - Mitigation: Add file size limit before parsing

2. **Memory exhaustion:**
   - Excel with 1 million rows would exhaust memory during pandas load
   - Mitigation: Add `pd.read_excel(nrows=MAX_ROWS)` limit

3. **Path traversal:**
   - Not applicable - we use `tempfile.NamedTemporaryFile()` which generates safe names

**Code reference:** `services/excel_service.py:302-308`

---

### A6. What's the maximum constraint count before the solver becomes impractical?

**Answer:**

Constraint count impacts solver performance in two ways:

1. **Model building time:** Each constraint adds equations via `solver.Add()`
2. **Solution time:** More constraints = smaller feasible region = more branching

**Empirical observations from testing:**
- 100 constraints: ~2 seconds solve time
- 500 constraints: ~15 seconds
- 1000+ constraints: Minutes to hours (exponential scaling)

**Bottlenecks by constraint type:**

| Constraint Type | Scaling | Reason |
|-----------------|---------|--------|
| Max Hours (per worker) | O(W) | One constraint per worker |
| Mutual Exclusion | O(W² × S) | Pair comparisons per shift |
| Overlap Prevention | O(W × S²) | Time comparisons across shifts |
| Coverage | O(S × T) | One per task per shift |

**The real killer:** Dynamic constraints (Mutual Exclusion) scale quadratically with worker count.

**Optimization opportunity:** Use constraint pooling - don't check banned pairs for shifts where neither worker is eligible.

**Code reference:** `solver/constraints/dynamic.py`

---

### A7. How does the system behave when PostgreSQL's max_connections is reached?

**Answer:**

SQLAlchemy uses connection pooling via `create_engine()`:

```python
# app/db/session.py (inferred from patterns)
engine = create_engine(DATABASE_URL, pool_size=5, max_overflow=10)
```

**Connection exhaustion scenarios:**

1. **Pool exhaustion (within app):**
   - 15 concurrent requests (5 base + 10 overflow)
   - 16th request blocks until timeout
   - `TimeoutError` raised, API returns 503

2. **PostgreSQL exhaustion (system-wide):**
   - Other apps or admin tools consuming connections
   - New connections fail immediately
   - `OperationalError: too many connections`

**ProcessPoolExecutor complication:**
Each background process creates its own connection outside the pool. With 4 workers:
- Main app pool: 15 connections
- Background workers: 4 connections
- Total needed: 19 minimum

**Render.com context:** Free tier PostgreSQL has 20 connections max. Current architecture is borderline safe.

**Code reference:** `app/db/session.py`

---

### A8. What happens if a constraint's `apply()` method throws an exception?

**Answer:**

The exception propagates up through `ConstraintRegistry.apply_all()`:

```python
# solver/constraints/registry.py:74-78
for constraint in self._constraints:
    if constraint.enabled and constraint.type == ConstraintType.HARD:
        constraint.apply(context)  # Exception escapes here
```

**Current behavior:**
- Exception reaches `run_solver_in_process()`
- Caught by `except Exception as e`
- Job marked as FAILED with error message
- Other constraints never applied

**Problem:** If constraint #3 of 10 fails, the error message doesn't indicate which constraint caused it.

**Improvement:** Wrap each `apply()` in individual try/except with constraint name in error:

```python
for constraint in self._constraints:
    try:
        constraint.apply(context)
    except Exception as e:
        raise ConstraintApplicationError(constraint.name, e)
```

**Code reference:** `solver/constraints/registry.py:59-88`

---

### A9. How does the solver handle a shift that requires more workers than exist in the system?

**Answer:**

This is detected by the Coverage constraint, but the behavior depends on constraint type:

**HARD Coverage (current implementation):**
```python
# solver/constraints/static_hard.py (conceptual)
solver.Add(sum(x_vars_for_task) >= required_count)
```

If `required_count = 5` but only 3 eligible workers exist, the solver returns `INFEASIBLE`.

**Diagnosis flow:**
1. Solver returns `status = pywraplp.Solver.INFEASIBLE`
2. User triggers diagnostics via `POST /solve/{job_id}/diagnose`
3. `diagnose_infeasibility()` runs pre-flight checks:
   - `_check_skill_gaps()` - Returns specific error if skills missing
   - `_check_availability_gaps()` - Returns error if no workers available
4. Then incremental constraint testing identifies Coverage as culprit

**User-facing message:**
```
FAILURE: The constraint 'task_coverage' caused the infeasibility.
This usually means: Not enough eligible workers to fill the required slots for a task.
```

**Code reference:** `solver/solver_engine.py:253-302`

---

### A10. What happens if the canonical epoch week (Jan 1-7, 2024) contains a daylight saving transition?

**Answer:**

The canonical week (January 1-7, 2024) was deliberately chosen to avoid DST issues:
- January is winter in Northern Hemisphere (no DST transition)
- January is summer in Southern Hemisphere (no DST transition)
- 2024-01-01 is a Monday, making weekday mapping clean

**If a transition existed:**
- `datetime.replace(hour=X)` could create ambiguous or non-existent times
- `timedelta` arithmetic would give unexpected results

**Current protection:** None explicit, but the date choice avoids the problem.

**Potential issue:** If someone in a timezone like Lord Howe Island (Australia) with unusual DST rules uses the system, edge cases might occur. However:
- All times are stored as naive datetime (no timezone info)
- Comparisons are numeric, not timezone-aware
- The system is internally consistent even if "wrong" in absolute terms

**Code reference:** `app/utils/date_normalization.py:CANONICAL_ANCHOR_DATES`

---

## Section B: Functional & Flow Comprehension (Mechanics Questions)

### B1. Trace the data flow from Excel upload to database persistence for a single worker row.

**Answer:**

**Step-by-step flow:**

1. **HTTP Request** (`api/routes.py`)
   - `POST /api/v1/upload` receives `UploadFile`
   - `file.read()` loads bytes into memory
   - Session ID extracted from cookie

2. **ExcelService.import_excel()** (`services/excel_service.py:286`)
   - Writes bytes to `tempfile.NamedTemporaryFile`
   - Opens as `pd.ExcelFile`
   - Runs validation via `_validate_excel_data()`

3. **Validation** (`services/excel_service.py:123-149`)
   - Checks required sheets exist (Workers, Shifts)
   - Validates each row (ID not empty, numeric fields valid)
   - Collects errors in `ImportValidationResult`

4. **ExcelParser initialization** (`services/excel_service.py:325`)
   - `ExcelParser(worker_repo, shift_repo)` - receives repository references
   - Calls `parser.load_from_file(tmp_path)`

5. **ExcelParser.parse_workers()** (`data/ex_parser.py`)
   - Reads Excel row into pandas Series
   - Creates `Worker` domain object:
     ```python
     worker = Worker(
         name=row['Name'],
         worker_id=row['ID'],
         wage=row['Wage'],
         ...
     )
     ```
   - Parses skills: `"Chef:5,Driver:3"` -> `{"Chef": 5, "Driver": 3}`
   - Parses availability per day column

6. **Repository.upsert_by_name()** (`repositories/sql_repo.py:382-415`)
   - Queries existing worker by name
   - If exists: Updates `attributes` JSON column
   - If new: Calls `add()` which uses `session.merge()`

7. **_to_model() conversion** (`repositories/sql_repo.py:246-297`)
   - Creates `WorkerModel` SQLAlchemy object
   - Serializes skills dict to JSON
   - Serializes availability to JSON format:
     ```json
     {"MON": {"timeRange": "08:00-16:00", "preference": "HIGH"}}
     ```

8. **Database write** (`services/excel_service.py:348`)
   - `self.db.commit()` persists all changes
   - SQLAlchemy ORM generates INSERT/UPDATE SQL

**Data transformations:**
```
Excel Row (strings)
    → pandas Series (typed)
    → Worker domain object (Python dataclass)
    → WorkerModel SQLAlchemy object (ORM)
    → SQL INSERT/UPDATE (database)
```

---

### B2. How does a constraint defined in `definitions.py` get applied to the solver?

**Answer:**

**Registration phase (app startup):**

1. `register_core_constraints()` called in `solver_service.py:324`
2. Creates `ConstraintDefinition` with:
   - `key`: "max_hours_per_week"
   - `config_model`: `MaxHoursPerWeekConfig` (Pydantic)
   - `factory`: Lambda that creates `MaxHoursPerWeekConstraint`
3. Adds to `constraint_definitions` singleton registry

**Hydration phase (job execution):**

1. `_build_constraint_registry()` called in `run_solver_in_process()`
2. Queries `SessionConfigModel` for session's constraint JSON
3. For each constraint in JSON:
   ```python
   # Get definition by category key
   defn = constraint_definitions.get(category)  # "max_hours_per_week"

   # Validate params against Pydantic model
   config_obj = defn.config_model.model_validate(params)

   # Create instance via factory
   constraint_instance = defn.factory(config_obj)

   # Register in runtime registry
   registry.register(constraint_instance)
   ```

**Application phase (solving):**

1. `solver.solve()` calls `registry.apply_all(context)`
2. Registry iterates constraints in order (HARD first, then SOFT)
3. Each constraint's `apply(context)` adds equations to solver:
   ```python
   # MaxHoursPerWeekConstraint.apply()
   for worker_id, assignments in context.worker_global_assignments.items():
       total_hours = sum(shift.duration * x_var for shift, x_var in assignments)
       solver.Add(total_hours <= self.max_hours)  # HARD
       # or
       solver.Objective().SetCoefficient(slack_var, self.penalty)  # SOFT
   ```

---

### B3. What happens internally when a user clicks "Run Solver" in the UI?

**Answer:**

**Frontend** (`frontend/src/components/SolverPanel.jsx`):
1. Button click triggers `handleRunSolver()`
2. `POST /api/v1/solver/run` with session cookie
3. UI enters "polling" state

**Backend - API layer** (`api/routes.py`):
1. Route handler extracts session_id from cookie
2. Calls `SolverService.start_job(session_id)`

**Backend - Service layer** (`services/solver_service.py:393-430`):
1. Opens DB session
2. Checks for active job (`_has_active_job()`)
3. Creates job record: `SolverJobStore.create_job(db, session_id)`
4. Gets ProcessPoolExecutor: `get_executor()`
5. Submits work: `executor.submit(run_solver_in_process, job_id, session_id)`
6. Returns job_id immediately (non-blocking)

**Backend - Background process** (`services/solver_service.py:236-318`):
1. `run_solver_in_process()` starts in separate process
2. Creates fresh DB connection (process isolation)
3. Marks job as RUNNING
4. Loads domain objects via repositories
5. Builds constraint registry from session config
6. Creates `SessionDataManagerAdapter` (detached from DB)
7. Creates `ShiftSolver` with adapter and registry
8. Calls `solver.solve()`
9. Extracts assignments from solved variables
10. Updates job with results via `update_job_completed()`

**Frontend - Polling** (`frontend/src/hooks/useSolverPolling.js`):
1. Every 2 seconds: `GET /api/v1/solver/status/{job_id}`
2. When status is COMPLETED: Fetch assignments, stop polling
3. When status is FAILED: Display error, stop polling

---

### B4. How does the skill matching algorithm work when finding eligible workers?

**Answer:**

**Entry point:** `SessionDataManagerAdapter.get_eligible_workers()`

**Algorithm:**

1. **Availability filter first:**
   ```python
   if time_window not in self._availability_index:
       return []  # No one available at this time
   ```

2. **Get pre-built skill map for this time window:**
   ```python
   skill_map = self._availability_index[time_window]
   # Structure: {"Chef": {5: [Worker1, Worker2], 3: [Worker3]}, ...}
   ```

3. **No skills required? Return all available:**
   ```python
   if not required_skills:
       return all_workers_in_skill_map
   ```

4. **Build candidate sets per skill:**
   ```python
   for req_skill, min_level in required_skills.items():
       valid_workers = set()
       for level, workers in skill_map[req_skill].items():
           if level >= min_level:
               valid_workers.update(workers)
       candidate_sets.append(valid_workers)
   ```

5. **Intersection = workers with ALL required skills:**
   ```python
   final_candidates = set.intersection(*candidate_sets)
   ```

**Example:**
- Required: `{"Chef": 3, "Driver": 1}`
- Chef level 3+: {Alice, Bob}
- Driver level 1+: {Bob, Carol}
- Intersection: {Bob}

**Performance:** O(S × L) where S = skills, L = levels. Index is pre-built, so actual query is fast.

**Code reference:** `services/session_adapter.py:78-135`

---

### B5. How does the infeasibility diagnosis identify the conflicting constraint?

**Answer:**

**Algorithm:** Incremental Constraint Isolation

**Phase 1: Pre-flight checks** (`solver/solver_engine.py:257-270`)
```python
# Check skill gaps
skill_gap = self._check_skill_gaps()
if skill_gap:
    return skill_gap  # "No worker has skill X"

# Check availability gaps
avail_gap = self._check_availability_gaps()
if avail_gap:
    return avail_gap  # "No one available for shift Y"
```

**Phase 2: Base model test** (`solver/solver_engine.py:273-276`)
```python
context = self._build_optimization_context()
if context.solver.Solve() not in [OPTIMAL, FEASIBLE]:
    return "Problem structurally impossible without any constraints"
```

**Phase 3: Individual constraint test** (`solver/solver_engine.py:279-289`)
```python
for constraint in hard_constraints:
    temp_context = self._build_optimization_context()  # Fresh context
    constraint.apply(temp_context)

    if temp_context.solver.Solve() not in [OPTIMAL, FEASIBLE]:
        return f"Constraint '{constraint.name}' caused infeasibility"
```

**Phase 4: Cumulative stacking** (`solver/solver_engine.py:292-301`)
```python
context = self._build_optimization_context()
for constraint in hard_constraints:
    constraint.apply(context)
    active_constraints.append(constraint.name)

    if context.solver.Solve() not in [OPTIMAL, FEASIBLE]:
        return f"Conflict after adding '{constraint.name}'. " \
               f"Conflicts with: {active_constraints[:-1]}"
```

**Why rebuild context each time?**
OR-Tools solver is stateful. Once a constraint is added, it can't be removed. Fresh context ensures clean isolation.

---

### B6. How does the Excel export reconstruct the schedule from database?

**Answer:**

**Entry point:** `ExcelService.export_excel()` (`services/excel_service.py:387-465`)

**Step 1: Fetch domain data**
```python
workers = self.worker_repo.get_all()
shifts = self.shift_repo.get_all()
worker_map = {w.worker_id: w.name for w in workers}
shift_map = {s.shift_id: s.name for s in shifts}
```

**Step 2: Get latest solver results**
```python
from services.solver_service import SolverService
latest_job = SolverService.get_latest_job_for_session(self.session_id)
raw_assignments = latest_job.get("assignments", [])
```

**Step 3: Transform assignments to rows**
```python
for assign in raw_assignments:
    worker_id = assign.get('worker_id')
    shift_id = assign.get('shift_id')

    assignments_data.append({
        'Date': time_str[:10],
        'Time': time_str[11:16],
        'Worker': worker_map.get(worker_id, worker_id),
        'Shift': shift_map.get(shift_id, shift_id),
        'Score': assign.get('score', 0)
    })
```

**Step 4: Create Excel with styling**
```python
with pd.ExcelWriter(output, engine='openpyxl') as writer:
    df_schedule = pd.DataFrame(assignments_data)
    df_schedule.to_excel(writer, sheet_name='Schedule', index=False)

    # Apply header styling
    ws = writer.sheets['Schedule']
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
```

**Data flow:** `SolverJobModel.assignments (JSON)` → `Python list` → `DataFrame` → `Excel bytes`

---

### B7. How does the session isolation mechanism prevent data leakage?

**Answer:**

**Implementation layers:**

**Layer 1: Cookie-based session ID**
```python
# api/routes.py (conceptual)
@app.get("/api/v1/workers")
def get_workers(session_id: str = Cookie(...)):
    repo = SQLWorkerRepository(db, session_id=session_id)
    return repo.get_all()
```

**Layer 2: BaseRepository filtering**
```python
# repositories/base.py
class BaseRepository:
    def __init__(self, session: Session, model, session_id: str):
        self.session_id = session_id

    def get_all(self):
        return self.session.query(self.model).filter(
            self.model.session_id == self.session_id
        ).all()
```

**Layer 3: Job ownership validation**
```python
# services/solver_service.py:456-458
if job_data and session_id and job_data.get("session_id") != session_id:
    logger.warning(f"Session {session_id} attempted to access job belonging to different session")
    return None
```

**Attack vectors blocked:**
1. **Direct ID guessing:** Can't access worker W123 without valid session_id
2. **Job enumeration:** Can't view other sessions' solver results
3. **Session hijacking:** Would require stealing cookie (HTTPS protects this)

**What's NOT protected:**
- If attacker obtains session cookie, they have full access to that session
- No rate limiting on session creation (DoS vector)
- Sessions don't expire automatically

---

### B8. How does the solver know which task option was selected after optimization?

**Answer:**

**Variable structure:**

Y-variables encode option selection:
```python
# Key: (shift_id, task_id, option_index)
y_vars[(shift_id, task.task_id, opt_idx)] = solver.IntVar(0, 1, y_name)
```

**Structural constraint ensures exactly one:**
```python
# solver/solver_engine.py:108-109
task_option_vars = [y_vars[(shift_id, task.task_id, i)] for i in range(len(task.options))]
solver.Add(sum(task_option_vars) == 1)
```

**After solving:**
```python
for key, y_var in context.y_vars.items():
    if y_var.solution_value() > 0.5:  # Selected
        shift_id, task_id, opt_idx = key
        selected_option = shift.tasks[task_id].options[opt_idx]
```

**Current limitation:** The `_extract_assignments()` method doesn't explicitly track which option was selected. It infers from X-variables (worker assignments). This works but loses the "option preference score" information.

**Code reference:** `solver/solver_engine.py:93-109`

---

### B9. How does the penalty breakdown calculation work for soft constraints?

**Answer:**

**Entry point:** `ConstraintRegistry.get_penalty_breakdown()` (`solver/constraints/registry.py:134-169`)

**Algorithm:**

1. **Collect violations from all soft constraints:**
   ```python
   violations = self.get_violations(context)
   # Returns: {"max_hours": [Violation1, Violation2], "mutual_exclusion": [...]}
   ```

2. **Aggregate by constraint type:**
   ```python
   for constraint_name, violation_list in violations.items():
       total_penalty = sum(v.penalty for v in violation_list)
       breakdown[constraint_name] = {
           "total_penalty": total_penalty,
           "violation_count": len(violation_list),
           "violations": [...]
       }
   ```

**Example output:**
```json
{
  "max_hours_per_week": {
    "total_penalty": -150.0,
    "violation_count": 3,
    "violations": [
      {"description": "Worker Alice: 45 hours (limit 40)", "penalty": -50.0},
      {"description": "Worker Bob: 42 hours (limit 40)", "penalty": -50.0},
      {"description": "Worker Carol: 44 hours (limit 40)", "penalty": -50.0}
    ]
  }
}
```

**How penalties affect objective:**
- Solver maximizes: `base_score + sum(penalties)`
- Penalties are negative, so violations reduce total score
- Optimal solution minimizes violations while maximizing coverage

---

### B10. What's the complete lifecycle of a SolverJob from creation to completion?

**Answer:**

**State machine:**
```
PENDING → RUNNING → COMPLETED
                  ↘ FAILED
```

**Timeline:**

| Time | State | Action | Code Location |
|------|-------|--------|---------------|
| T+0ms | PENDING | Job created in DB | `SolverJobStore.create_job()` |
| T+5ms | - | Submitted to ProcessPoolExecutor | `executor.submit()` |
| T+10ms | RUNNING | Background process starts, updates status | `update_job_running()` |
| T+50ms | RUNNING | Data loaded from DB into memory | `worker_repo.get_all()` |
| T+100ms | RUNNING | Constraint registry built | `_build_constraint_registry()` |
| T+200ms | RUNNING | Solver context created | `_build_optimization_context()` |
| T+500ms | RUNNING | Constraints applied | `registry.apply_all()` |
| T+1000ms-60000ms | RUNNING | OR-Tools solving | `solver.Solve()` |
| T+X | COMPLETED | Results written to DB | `update_job_completed()` |

**Database fields updated at each stage:**

| Field | PENDING | RUNNING | COMPLETED | FAILED |
|-------|---------|---------|-----------|--------|
| status | "pending" | "running" | "completed" | "failed" |
| created_at | set | - | - | - |
| started_at | null | set | - | - |
| completed_at | null | null | set | set |
| result_status | null | null | "Optimal"/"Feasible" | null |
| assignments | null | null | [...] | null |
| error_message | null | null | null | "Error..." |

---

## Section C: System Design & Engineering

### C1. Why did you choose a monolithic architecture over microservices?

**Answer:**

**Decision rationale:**

1. **Team size:** Solo developer. Microservices add operational overhead without team to distribute.

2. **Deployment complexity:** One container vs. orchestrating solver service, API service, worker service, message broker.

3. **Latency:** Solver needs direct access to constraints and data. Inter-service calls would add 10-50ms per hop.

4. **Transaction boundaries:** Excel import touches Workers, Shifts, and Constraints atomically. Distributed transactions are hard.

5. **Debugging:** Single process means single log stream, straightforward stack traces.

**Where I DID apply separation:**
- ProcessPoolExecutor gives process isolation for CPU-bound work
- Clean module boundaries (services, repositories, domain)
- Could be split later along those boundaries

**When I would switch:**
- Multiple teams working on different domains
- Independent scaling requirements (e.g., solver needs GPU)
- Different deployment cadences per service

---

### C2. Why is the database schema denormalized with JSON columns?

**Answer:**

**Examples of denormalization:**
- `WorkerModel.attributes` - JSON blob with skills, availability, preferences
- `ShiftModel.tasks_data` - JSON blob with nested tasks, options, requirements
- `SessionConfigModel.constraints` - JSON array of constraint objects

**Rationale:**

1. **Schema flexibility:** Adding a new worker attribute (e.g., `seniority_level`) doesn't require migration.

2. **Domain complexity:** Task → Options → Requirements is a 3-level hierarchy. Normalized would need 4 tables with JOINs.

3. **Read patterns:** We always load full worker/shift, never query "all workers with skill X" in SQL.

4. **Write patterns:** Updates are full object replacements, not field-level changes.

**Trade-offs accepted:**
- Can't index on JSON fields efficiently (PostgreSQL JSONB would help)
- Can't enforce foreign keys inside JSON
- Harder to do cross-entity queries

**Why it works here:**
- Session isolation means small data sets per query (~100 workers max per session)
- All filtering happens in Python after loading (repository layer)

---

### C3. Why are constraint definitions decoupled from their implementation classes?

**Answer:**

**Architecture:**
```python
# definitions.py - Metadata
ConstraintDefinition(
    key="max_hours_per_week",
    config_model=MaxHoursPerWeekConfig,  # Schema
    implementation_cls=MaxHoursPerWeekConstraint,  # Reference
    factory=lambda cfg: MaxHoursPerWeekConstraint(cfg.max_hours, cfg.penalty),
    ui_fields=[...]  # UI hints
)

# static_soft.py - Implementation
class MaxHoursPerWeekConstraint(BaseConstraint):
    def apply(self, context): ...
    def get_violations(self, context): ...
```

**Benefits:**

1. **Single source of truth:** All metadata in one file, implementation in another.

2. **UI generation:** Frontend can query `/api/v1/constraints/schema` to get form fields without knowing implementation.

3. **Validation separated from logic:** Pydantic validates config before factory is called.

4. **Testing:** Can test implementation class with mock config, test definition separately.

5. **Extensibility:** Third parties could add constraints by registering definitions without modifying core files.

**Alternative rejected:** Having implementation classes self-describe their config. This couples validation logic to constraint logic.

---

### C4. Why use ProcessPoolExecutor instead of async/await for the solver?

**Answer:**

**The problem:** OR-Tools solver is CPU-bound, pure Python. It doesn't release the GIL.

**If we used async:**
```python
async def solve():
    result = solver.Solve()  # BLOCKS entire event loop for 60 seconds
    return result
```
This would freeze all API endpoints during solve.

**ProcessPoolExecutor solution:**
```python
executor.submit(run_solver_in_process, job_id, session_id)
# Returns immediately, API stays responsive
```

**Why not ThreadPoolExecutor?**
- GIL prevents true parallelism for CPU work
- Would still block event loop partially
- Process isolation is cleaner for memory-heavy solver

**Trade-offs:**
- IPC overhead for passing results (serialization)
- No shared state between processes (must re-fetch from DB)
- Process startup cost (~100ms)

**Code reference:** `services/solver_service.py:44-81`

---

### C5. How does the React state management architecture work without Redux?

**Answer:**

**Pattern:** Lifting state up + custom hooks + Context for globals.

**Component hierarchy:**
```
App
├── SessionContext.Provider (global session_id)
│   ├── WorkersTab (local state: workers[])
│   ├── ShiftsTab (local state: shifts[])
│   ├── ConstraintsTab (local state: constraints[])
│   └── SolverPanel
│       ├── useSolverPolling() hook
│       └── ResultsView (receives assignments as prop)
```

**State locations:**

| State | Location | Why |
|-------|----------|-----|
| session_id | Context | Needed by all API calls |
| workers list | WorkersTab | Only this tab needs it |
| solver job status | useSolverPolling hook | Encapsulates polling logic |
| modal open/close | Local component state | UI-only, no sharing needed |

**Why not Redux:**
- Small app, ~10 components
- No complex state interactions
- No time-travel debugging needed
- Custom hooks provide same encapsulation

**When I would add Redux:**
- Undo/redo functionality
- Complex derived state (selectors)
- State persistence to localStorage

---

### C6. Why is the Worker domain model a dataclass instead of a Pydantic model?

**Answer:**

**Current design:**
```python
# domain/worker_model.py
@dataclass
class Worker:
    name: str
    worker_id: str
    skills: Dict[str, int] = field(default_factory=dict)
    availability: List[TimeWindow] = field(default_factory=list)
```

**Rationale:**

1. **Performance:** Dataclasses are ~3x faster to instantiate than Pydantic models.

2. **Mutability:** Workers are modified during parsing (add_skill, add_availability). Pydantic's immutability (frozen=True) would require copying.

3. **No validation needed:** By the time we create Worker, data has already been validated by API schemas.

4. **Serialization control:** Explicit `_to_model()` and `_to_domain()` in repository gives full control.

**Where Pydantic IS used:**
- API request/response schemas (validation at boundary)
- Constraint config models (immutable after creation)

**Trade-off:** Manual serialization in repository. If I used Pydantic, could use `.model_dump()` directly.

---

### C7. How does the constraint class hierarchy support both HARD and SOFT constraints?

**Answer:**

**Hierarchy:**
```
IConstraint (Protocol)
    ↑
BaseConstraint (Abstract base)
    ↑
├── CoverageConstraint (HARD)
├── OverlapPreventionConstraint (HARD)
├── MaxHoursPerWeekConstraint (SOFT)
└── MutualExclusionConstraint (configurable HARD/SOFT)
```

**Key design:**

1. **Type enum stored in instance:**
   ```python
   self._type = ConstraintType.HARD  # or SOFT
   ```

2. **Registry sorts by type:**
   ```python
   # Apply HARD first (feasibility), then SOFT (optimization)
   for constraint in self._constraints:
       if constraint.type == ConstraintType.HARD:
           constraint.apply(context)
   ```

3. **Implementation differs by type:**

   **HARD constraint:**
   ```python
   def apply(self, context):
       solver.Add(sum(x_vars) >= required_count)  # Strict equality
   ```

   **SOFT constraint:**
   ```python
   def apply(self, context):
       slack = solver.IntVar(0, 100, "slack")
       solver.Add(total_hours <= max_hours + slack)
       solver.Objective().SetCoefficient(slack, -50)  # Penalty
   ```

**Dynamic strictness (Mutual Exclusion):**
```python
if self.strictness == ConstraintType.HARD:
    solver.Add(x_worker_a + x_worker_b <= 1)  # Can't both be 1
else:
    # Use slack variable with penalty
```

---

### C8. Why does the repository use merge() instead of add() for persistence?

**Answer:**

**SQLAlchemy operations:**
- `session.add(obj)` - INSERT only, fails if PK exists
- `session.merge(obj)` - INSERT or UPDATE based on PK

**Current usage:**
```python
# repositories/sql_repo.py:379
self.session.merge(db_model)
```

**Rationale:**

1. **Upsert semantics:** Excel import may reference existing workers. `merge()` handles both cases.

2. **Idempotency:** Re-uploading same Excel produces same result (updates, not duplicates).

3. **No existence check needed:** Don't need `if exists: update else: insert` logic.

**The `upsert_by_name()` method:**
```python
# For Excel where we want NAME as the key, not ID
existing = session.query(WorkerModel).filter_by(name=worker.name).first()
if existing:
    existing.attributes = new_model.attributes  # Update
else:
    self.add(worker)  # Insert
```

**Trade-off:** `merge()` does a SELECT before INSERT/UPDATE. For bulk imports, batch inserts would be faster.

---

### C9. How does the date normalization system prevent temporal bugs?

**Answer:**

**The problem:** "Date Drift"
- Excel imports workers available "Monday 8-16"
- System creates datetime: Monday of current week (2026-02-17)
- User creates shift for next week (2026-02-24)
- Worker's availability (Feb 17) doesn't cover shift (Feb 24)
- Solver says "no workers available" - confusing!

**Solution: Canonical Epoch Week**
```python
# app/utils/date_normalization.py
CANONICAL_ANCHOR_DATES = {
    0: date(2024, 1, 1),  # Monday
    1: date(2024, 1, 2),  # Tuesday
    ...
    6: date(2024, 1, 7),  # Sunday
}
```

**All dates normalized to this fixed week:**
- Worker available "Monday" → 2024-01-01
- Shift on "Monday" → 2024-01-01
- Comparison works regardless of actual calendar date

**Implementation points:**
1. `repositories/sql_repo.py:214-226` - Worker availability parsing
2. `repositories/sql_repo.py:793-806` - Shift date normalization
3. `services/session_adapter.py:53` - Index built on normalized windows

**Trade-off:** Lose actual calendar date information. Can't schedule "Feb 24 specifically."

---

### C10. Why does the solver use SCIP/CBC instead of a commercial solver?

**Answer:**

**Solver selection logic:**
```python
# solver/solver_engine.py:43-48
self._solver_id = 'CBC'
if not pywraplp.Solver.CreateSolver(self._solver_id):
    self._solver_id = 'SCIP'
```

**Rationale:**

1. **Cost:** CPLEX/Gurobi cost $10,000+/year. This is a portfolio project.

2. **OR-Tools bundling:** SCIP and CBC come free with OR-Tools installation.

3. **Performance:** For problems up to ~1000 variables, open-source solvers are competitive.

4. **Portability:** No license server needed, works on any machine.

**CBC vs SCIP:**
- CBC (Coin-OR Branch and Cut): Faster for pure LP, moderate for MILP
- SCIP: Better for complex MILP with many integer variables

**When commercial would matter:**
- 10,000+ workers (enterprise scale)
- Sub-second response requirements
- Need for advanced presolve techniques

**Current performance:** 50 workers, 100 shifts solves in ~5 seconds with SCIP.

---

## Section D: Personal Architectural Decisions

### D1. Why did you choose Google OR-Tools over alternatives like PuLP or OptaPlanner?

**Answer:**

**Alternatives considered:**

| Library | Language | Pros | Cons |
|---------|----------|------|------|
| PuLP | Python | Simple API, pure Python | Only LP, slow for MILP |
| OptaPlanner | Java | Constraint Streams DSL, incremental solving | JVM overhead, separate service |
| OR-Tools | Python/C++ | MILP + CP-SAT, C++ core, Python bindings | Steeper learning curve |
| Gurobi | Python | Fastest solver | $$$, license complexity |

**Why OR-Tools:**

1. **Mixed capabilities:** Supports both Linear Programming and Constraint Programming. Could switch approaches without changing libraries.

2. **Python bindings:** Native Python API, integrates with FastAPI naturally.

3. **C++ core:** Solver itself is C++, so performance isn't Python-limited.

4. **Google support:** Actively maintained, good documentation.

5. **Free:** No licensing issues for portfolio project.

**What I'd reconsider:**
- For pure assignment problems, CP-SAT might be cleaner
- For very large scale, would need Gurobi

---

### D2. What was the logic behind prioritizing the Metadata-Driven Architecture refactor?

**Answer:**

**Context:** Legacy system had constraints hardcoded in multiple files. Adding "min rest hours" required changes in:
- `config.py` (definition)
- `solver_engine.py` (application)
- `excel_service.py` (parsing)
- Frontend (form)

**Pain points that triggered refactor:**

1. **Bug frequency:** Case-sensitivity bugs in Excel parsing (e.g., "Mutual Exclusion" vs "mutual exclusion")

2. **Development velocity:** Adding co-location took 4 hours across 5 files

3. **Testing difficulty:** Couldn't test constraint validation without full solver

4. **Onboarding friction:** New contributors didn't know where to add constraints

**ROI calculation:**
- Refactor cost: ~16 hours
- Per-constraint cost before: 4 hours
- Per-constraint cost after: 30 minutes
- Break-even: 4th new constraint

**What I deferred:**
- Full UI schema endpoint (marked as tech debt)
- Migration of all legacy constraints (some still hardcoded)

---

### D3. Where did you consciously incur Technical Debt, and how do you plan to pay it back?

**Answer:**

**Conscious debt items:**

| Debt | Why Incurred | Payback Plan |
|------|--------------|--------------|
| `config.py` still exists | Breaking change to delete | Sprint 1: Remove imports, delete file |
| UI metadata incomplete | Time constraint | Sprint 2: Populate ui_fields for all constraints |
| No job timeout | Edge case, low priority | Sprint 3: Add 10-minute timeout, auto-fail |
| Manual attribute mapping | Works, tedious | Sprint 4: Pydantic auto-serialization |
| Hardcoded penalties in Excel | Works, not user-configurable | Sprint 2: Read Penalty column |

**Tracking mechanism:** `CLAUDE.md` has Tech Debt Registry section with priorities.

**What I DIDN'T compromise:**
- Session isolation (security)
- Constraint registry pattern (architecture)
- Test coverage for solver (correctness)

---

### D4. How did you decide the boundary between SQL and Python logic?

**Answer:**

**Principle:** SQL for persistence, Python for business logic.

**SQL handles:**
- CRUD operations
- Session filtering (`WHERE session_id = ?`)
- Basic lookups by ID/name

**Python handles:**
- Skill matching algorithm
- Availability overlap detection
- Constraint application
- Serialization/deserialization

**Why not SQL for skill matching?**
```sql
-- This would be complex and slow:
SELECT w.* FROM workers w
WHERE EXISTS (
    SELECT 1 FROM json_each(w.attributes->'skills') s
    WHERE s.key = 'Chef' AND s.value >= 3
    AND EXISTS (...)
)
```

vs. Python:
```python
for skill, level in worker.skills.items():
    if level >= required_level:
        candidates.add(worker)
```

**Performance trade-off:**
- Load all workers (N records) → Filter in Python
- vs. SQL query with JSON operations

For N < 1000, Python is faster due to JSON parsing overhead in SQL.

---

### D5. Why did you choose SQLite for development and PostgreSQL for production?

**Answer:**

**Development with SQLite:**
- Zero configuration (file-based)
- Fast for tests (in-memory option)
- Easy to reset (`rm scheduler.db`)
- No Docker required locally

**Production with PostgreSQL:**
- Concurrent writes (SQLite has single-writer lock)
- Connection pooling (SQLite doesn't support)
- Render.com managed service (backups, monitoring)
- JSONB for potential indexing

**Compatibility strategy:**
```python
# Use SQLAlchemy ORM exclusively
# No raw SQL except in tests
# JSON columns work on both (TEXT in SQLite, JSONB in PG)
```

**What I verified:**
- All tests pass with SQLite
- Migration script works with PostgreSQL
- JSON operations equivalent

---

### D6. What alternative architecture did you consider and reject?

**Answer:**

**Rejected: Event-Driven with Celery**

Design:
```
API → Redis Queue → Celery Worker → Result Backend
```

Why rejected:
- Infrastructure complexity (Redis + Celery + Flower)
- Deployment cost (separate worker service)
- Overkill for expected load (~10 solves/day)

**Rejected: GraphQL API**

Design:
```graphql
query {
  workers(skills: ["Chef"]) {
    name
    shifts { name, time }
  }
}
```

Why rejected:
- No complex nested queries in this domain
- REST is simpler for CRUD operations
- Team unfamiliar with GraphQL

**Rejected: Separate Solver Microservice**

Design:
```
API Service ←→ gRPC ←→ Solver Service
```

Why rejected:
- Serialization overhead for large matrices
- Deployment complexity
- Debugging across services

**What I WOULD use if scaling:**
- Celery for job queue (>100 concurrent users)
- Read replicas for PostgreSQL (high read load)
- Redis caching for constraint definitions

---

### D7. How did you decide what to test vs. what to skip?

**Answer:**

**Testing pyramid applied:**

| Layer | Coverage | Rationale |
|-------|----------|-----------|
| Solver logic | HIGH | Core business value, hard to debug |
| Constraint application | HIGH | Each constraint has unit tests |
| Repository mapping | MEDIUM | Integration tests catch issues |
| API endpoints | MEDIUM | Happy path + error cases |
| Frontend components | LOW | Visual, changes frequently |

**What I explicitly skipped:**
- UI snapshot tests (too brittle)
- End-to-end Selenium tests (maintenance burden)
- Performance benchmarks (premature optimization)

**Test file organization:**
```
tests/
├── test_solver_engine.py        # Core solver tests
├── test_constraints/            # Per-constraint tests
├── test_repositories.py         # Data layer tests
├── test_api_routes.py           # API integration tests
└── test_excel_service.py        # Import/export tests
```

**What triggered test additions:**
- Every bug fix includes regression test
- New constraint requires test coverage
- Refactor requires green tests first

---

### D8. Why did you choose session-based isolation over user authentication?

**Answer:**

**Design decision:** Anonymous sessions with UUID, no login.

**Rationale:**

1. **Reduced scope:** Authentication adds OAuth/JWT/password complexity

2. **Demo-friendly:** Users can try immediately without signup

3. **Data isolation:** Session ID in cookie provides per-browser separation

4. **No PII:** Don't store emails, names, passwords - GDPR simplified

**Implementation:**
```python
# On first request
if not session_id_cookie:
    session_id = str(uuid.uuid4())
    response.set_cookie("session_id", session_id, httponly=True)
```

**Trade-offs accepted:**
- Can't resume session on different device
- No cross-device data sync
- Session lost if cookies cleared

**When I would add auth:**
- Multi-user collaboration on same schedule
- Persistent data across devices
- Billing/paid features

---

### D9. How did you balance feature completeness vs. shipping speed?

**Answer:**

**MVP definition:**
1. Upload Excel with workers and shifts
2. Configure constraints
3. Run solver
4. Export results

**Deferred features:**
- Manual shift assignment (solver-only)
- Worker self-service portal
- Email notifications
- Mobile-responsive UI
- Multi-language support

**Decision framework:**
```
IF feature blocks demo THEN implement
ELSE IF feature has >1 week effort THEN defer
ELSE IF feature is "nice to have" THEN defer
```

**Example trade-off:**
- Full constraint schema endpoint vs. hardcoded forms
- Decision: Hardcoded forms ship faster
- Debt tracked: "Missing Schema Endpoint" in CLAUDE.md

**Result:** Working demo in 6 weeks vs. theoretical 12 weeks for "complete" version.

---

### D10. What would you do differently if starting this project today?

**Answer:**

**Architecture changes:**

1. **Start with PostgreSQL everywhere:** SQLite/PG mismatch caused subtle bugs.

2. **Use Alembic from day 1:** Schema changes were manual, error-prone.

3. **Define API schema first:** OpenAPI spec before implementation would catch issues earlier.

4. **Stricter TypeScript:** More type coverage in frontend would catch errors.

**Process changes:**

1. **Write ADRs (Architecture Decision Records):** Forgot why I made some choices.

2. **Integration tests earlier:** Caught bugs late that integration tests would find.

3. **Performance budget:** Didn't set targets, now uncertain if "fast enough."

**What worked well:**

1. **CLAUDE.md context file:** Saved hours of re-explaining architecture to AI assistants.

2. **Metadata-driven constraints:** Paid off quickly in development speed.

3. **Process isolation for solver:** Never had API freezes during solves.

4. **Session-based multi-tenancy:** Simple, effective, no user management headaches.

---

## Appendix: Quick Reference

### Key Files for Architecture Defense

| File | Purpose | Lines |
|------|---------|-------|
| `solver/constraints/definitions.py` | Constraint registry (Single Source of Truth) | 396 |
| `services/solver_service.py` | Job orchestration, process management | 624 |
| `repositories/sql_repo.py` | Repository pattern implementation | 825 |
| `solver/solver_engine.py` | OR-Tools integration, diagnostics | 485 |
| `services/excel_service.py` | Anti-corruption layer | 997 |

### Complexity Metrics

| Metric | Value |
|--------|-------|
| Total Python files | 45 |
| Total lines of Python | ~8,500 |
| Test files | 20 |
| Test coverage | ~65% |    
| Cyclomatic complexity (max) | 15 (solver_engine.py) |

---

*Document prepared for technical interview defense. Last updated: February 2026*
