[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/) [![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com) [![OR-Tools](https://img.shields.io/badge/OR--Tools-MILP-4285F4?logo=google&logoColor=white)](https://developers.google.com/optimization) [![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.x-D71F00)](https://www.sqlalchemy.org/) [![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/) [![Tests](https://img.shields.io/badge/tests-460%2B%20passing-brightgreen)](#-testing) [![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](#-getting-started) [![License](https://img.shields.io/badge/License-MIT-yellow)](#-license)

# ShiftApp

**A production-grade constraint-satisfaction scheduling engine that solves an NP-hard combinatorial optimization problem using Mixed Integer Linear Programming.**

ShiftApp assigns workers to shifts by formulating the problem as a MILP with binary decision variables, hard/soft constraint decomposition via slack variables, and a 4-stage incremental relaxation algorithm that diagnoses mathematical infeasibility. The constraint system is fully extensible through a metadata-driven registry that enforces the Open-Closed Principle — new constraint types require zero modifications to the solver engine.

---

## Why This Project Exists

Shift scheduling is a textbook NP-hard problem (reducible from Set Cover), but the gap between an algorithms textbook and a production system is enormous. This project bridges that gap:

- **The mathematical core** — A MILP formulation with two sets of binary decision variables (Y for task option selection, X for worker-to-role assignment) linked through a coverage constraint that ensures staffing requirements match the selected configuration.
- **The diagnostic engine** — When the solver returns `INFEASIBLE`, a 4-stage incremental relaxation algorithm pinpoints exactly which constraint (or combination of constraints) causes the failure, running asynchronously as a background process.
- **The extensibility architecture** — The constraint registry uses Strategy + Factory patterns so that adding a new constraint type (Pydantic config, solver implementation, API schema, Excel parser, UI metadata) requires a single registration call. The solver engine is closed for modification, open for extension.
- **The isolation boundary** — OR-Tools runs in a subprocess via `ProcessPoolExecutor`. Since SQLAlchemy sessions cannot cross process boundaries, a snapshot adapter serializes the entire domain state into a read-only in-memory data manager, achieving full solver-database decoupling.

The frontend is a lightweight React UI for data entry and result visualization — the engineering depth lives entirely in the backend.

---

## Solver Engine

The solver formulates shift scheduling as a **Mixed Integer Linear Program** and solves it using Google OR-Tools' CBC solver (with SCIP fallback).

### Problem Formulation

**Objective:** Maximize total schedule quality (worker preference scores minus constraint violation penalties).

**Decision Variables:**

| Variable | Type | Meaning |
|----------|------|---------|
| **Y**_(shift, task, option)_ | Binary | 1 if task option is selected for a shift, 0 otherwise |
| **X**_(worker, shift, task, role)_ | Binary | 1 if worker is assigned to a role in a task, 0 otherwise |

**Key Invariant:** Exactly one option must be selected per task (`Sum(Y) = 1`), and the number of workers assigned to each role must equal the staffing requirement of the selected option (`Sum(X) = Sum(count * Y)`).

### Constraint Types

| # | Constraint | Type | Technique | Source |
|---|-----------|------|-----------|--------|
| 1 | **Coverage** | Hard | Y-X variable linkage | `static_hard.py` |
| 2 | **Intra-Shift Exclusivity** | Hard | `Sum(X) <= 1` per (worker, shift) | `static_hard.py` |
| 3 | **Overlap Prevention** | Hard | Sorted time-window pairwise exclusion | `static_hard.py` |
| 4 | **Max Hours/Week** | Soft | Slack variable penalty | `static_soft.py` |
| 5 | **Avoid Consecutive Shifts** | Soft | Indicator variable penalty | `static_soft.py` |
| 6 | **Worker Preferences** | Soft | Objective coefficient injection | `static_soft.py` |
| 7 | **Task Option Priority** | Soft | Rank-weighted Y penalty | `static_soft.py` |
| 8 | **Mutual Exclusion** | Dynamic | Pairwise `X_a + X_b <= 1` | `dynamic.py` |
| 9 | **Co-Location** | Dynamic | Indicator + penalty pairing | `dynamic.py` |

### Slack Variable Technique (Soft Constraints)

Soft constraints use slack variables to convert hard limits into objective function penalties. This is the core technique that makes schedules *flexible* — the solver can exceed a limit if the overall schedule quality improves:

```python
# solver/constraints/static_soft.py — MaxHoursPerWeekConstraint.apply()

for worker in context.workers:
    total_hours_expr = 0
    for shift, x_var in context.worker_global_assignments[worker.worker_id]:
        total_hours_expr += shift.time_window.duration_hours * x_var

    if self.type == ConstraintType.HARD:
        # HARD: strictly forbid exceeding max_hours
        context.solver.Add(total_hours_expr <= self.max_hours)
    else:
        # SOFT: slack variable absorbs the overage, penalized in objective
        slack_var = context.solver.NumVar(0.0, context.solver.infinity(), slack_name)
        context.solver.Add(total_hours_expr - self.max_hours <= slack_var)
        context.solver.Objective().SetCoefficient(slack_var, self.penalty_per_hour)
```

If a worker exceeds `max_hours`, the slack variable `S_w` absorbs the overage. The objective function penalizes each excess hour at `penalty_per_hour`, letting the solver decide whether the trade-off is worth it.

### Coverage Constraint (Y-X Variable Linkage)

This is the constraint that connects *what configuration was chosen* (Y) with *who is assigned* (X):

```python
# solver/constraints/static_hard.py — CoverageConstraint.apply()

# For each role in each task:
# Sum(workers assigned to role) == Sum(option_Y * required_count)
for role_sig, req_info in role_requirements_map.items():
    assigned_workers_vars = x_vars_by_role[(shift.shift_id, task.task_id, role_sig)]

    required_count_expression = 0
    for opt_idx, count in req_info:
        y_var = context.y_vars.get((shift.shift_id, task.task_id, opt_idx))
        if y_var is not None:
            required_count_expression += count * y_var

    context.solver.Add(sum(assigned_workers_vars) == required_count_expression)
```

---

## Infeasibility Diagnosis Engine

When the solver returns `INFEASIBLE`, ShiftApp runs an **asynchronous 4-stage incremental relaxation algorithm** as a background process. The job completes immediately with its solve result; diagnostics populate asynchronously.

### Stage 1 — Pre-Flight Checks

Detects impossible scenarios **before** invoking the solver:
- **Skill gaps** — shifts requiring skills that no worker in the pool possesses
- **Availability gaps** — shifts on days when zero workers are available

These are O(W * S) checks that catch trivially infeasible inputs without solver overhead.

### Stage 2 — Base Model Feasibility

Builds a minimal model with only the coverage constraint (the structural backbone). If this base model is infeasible, the input data itself is contradictory — no combination of constraints can fix it.

### Stage 3 — Individual Constraint Isolation

Rebuilds a fresh solver context for **each hard constraint in isolation** against the base model. If one constraint alone causes infeasibility, it is immediately identified with a human-readable explanation:

> *"The constraint 'overlap_prevention' makes the problem infeasible on its own."*

### Stage 4 — Greedy Combination Stacking

If all constraints pass individually, constraints are stacked incrementally. The first combination that breaks feasibility reveals the conflict:

> *"The system was feasible until 'overlap_prevention' was added. It conflicts with: ['coverage', 'intra_shift_exclusivity']."*

This incremental relaxation approach guarantees that the **minimal conflict set** is identified, giving users actionable feedback instead of a generic "infeasible" error.

---

## Constraint Registry Architecture

Adding a new constraint requires **zero changes to the solver engine**. This is achieved through a metadata-driven registry that strictly enforces the **Open-Closed Principle**:

```python
# solver/constraints/definitions.py — SINGLE SOURCE OF TRUTH

constraint_definitions.register(
    ConstraintDefinition(
        key="max_hours_per_week",
        label="Max hours per week",
        description="Limit total weekly hours per worker.",
        constraint_type=ConstraintType.SOFT,
        constraint_kind=ConstraintKind.STATIC,
        config_model=MaxHoursPerWeekConfig,          # Pydantic validation
        implementation_cls=MaxHoursPerWeekConstraint, # Strategy pattern
        factory=lambda cfg: MaxHoursPerWeekConstraint(
            max_hours=cfg.max_hours,
            penalty_per_hour=cfg.penalty,
            strictness=cfg.strictness,
        ),
        ui_fields=[                                   # Auto-generated UI schema
            UiFieldMeta(name="max_hours", label="Max hours per week", ...),
            UiFieldMeta(name="strictness", label="Strictness", ...),
            UiFieldMeta(name="penalty", label="Penalty per hour over limit", ...),
        ],
    )
)
```

**What this single registration provides automatically:**
- **Pydantic validation** on API input (`config_model`)
- **API schema generation** via `GET /api/v1/constraints/schema` for dynamic UI rendering
- **Excel import parsing** via registry lookup in `constraint_mapper.py`
- **Factory-based solver hydration** at solve time — the solver never instantiates constraints directly

**Design patterns at work:**
- **Strategy** — Each constraint implements `IConstraint.apply(context)`, pluggable without modifying the solver
- **Factory** — Lambda-based instantiation decouples the solver from constructor signatures
- **Registry** — Single source of truth eliminates scattered constraint metadata
- **Open-Closed Principle** — The solver engine, API layer, and Excel parser are all closed for modification when adding new constraints

---

## Async Job Pipeline

Solver jobs execute through an asynchronous state machine with full process isolation:

```
PENDING → RUNNING → COMPLETED (with optional background diagnostics)
                  → FAILED (with error details)
```

- **Process isolation** — `ProcessPoolExecutor` runs OR-Tools in a subprocess. SQLAlchemy sessions cannot cross process boundaries, so a `SessionDataManagerAdapter` serializes the domain snapshot into a read-only in-memory data manager.
- **Stale job recovery** — On startup, a reaper sweeps for jobs stuck in `RUNNING` (from prior crashes) and transitions them to `FAILED`.
- **Configurable parallelism** — `SOLVER_MAX_WORKERS` controls concurrent solver processes.
- **Background diagnostics** — When a solve returns infeasible, the diagnostic engine runs asynchronously. The job completes immediately; diagnostics populate later.

---

## Architecture

### System Overview

```
+---------------------------------------------------------------------------+
|                          React Frontend (Vite)                             |
+--------------------------------------+------------------------------------+
                                       | HTTP/JSON
+--------------------------------------v------------------------------------+
|  API Layer  (api/routers/)                                                |
|  Traffic cops only -- no business logic                                   |
|  +----------+ +----------+ +------------+ +----------+ +---------+        |
|  | Workers  | | Shifts   | | Constraints| | Solver   | | Import/ |        |
|  | Routes   | | Routes   | | Routes     | | Routes   | | Export  |        |
|  +----------+ +----------+ +------------+ +----------+ +---------+        |
+--------------------------------------+------------------------------------+
                                       |
+--------------------------------------v------------------------------------+
|  Service Layer  (services/)                                               |
|  Business logic, orchestration, transaction boundaries                    |
|  +-----------------+  +--------------+  +---------------------------+     |
|  | SolverService   |  | ExcelService |  | SolverJobStore            |     |
|  | (job lifecycle) |  | (Facade)     |  | (state machine)           |     |
|  +--------+--------+  +--------------+  +---------------------------+     |
|           |                                                               |
|  +--------v-------------------------------------------------------------+ |
|  | SessionDataManagerAdapter                                             | |
|  | Serializes domain snapshot for cross-process solver isolation         | |
|  +-----------------------------------------------------------------------+|
+--------------+-------------------------------+----------------------------+
               |                               |
+--------------v--------------+  +-------------v----------------------------+
|  Repository Layer           |  |  Solver Engine (subprocess)              |
|  (repositories/)            |  |  (solver/)                              |
|                             |  |                                         |
|  Protocol-based ABCs        |  |  OR-Tools MILP (CBC/SCIP)              |
|  Multi-tenant filtering     |  |  ConstraintRegistry (2-phase)          |
|  Canonical week normalizer  |  |  Infeasibility Diagnostics             |
+--------------+--------------+  +-----------------------------------------+
               |
+--------------v--------------+
|  Domain Layer (domain/)     |
|  Pure Python dataclasses    |
|  Zero I/O, zero imports     |
|  Worker, Shift, Task,       |
|  TimeWindow                 |
+-----------------------------+
```

### Layer Responsibilities

| Layer | Files | Responsibility |
|-------|-------|----------------|
| **API** | `api/routers/*_routes.py` | HTTP parsing, Pydantic validation, delegation — **no business logic** |
| **Service** | `services/solver_service.py`, `services/excel/` | Orchestration, transactions, process management |
| **Repository** | `repositories/sql_worker_repo.py`, `sql_shift_repo.py` | DB access, canonical week normalization, multi-tenant filtering |
| **Domain** | `domain/worker_model.py`, `shift_model.py`, `task_model.py` | Pure dataclasses — no SQLAlchemy, no FastAPI, no I/O |

### Design Patterns

| Pattern | Implementation | Purpose |
|---------|---------------|---------|
| **Registry** | `solver/constraints/definitions.py` | Single source of truth for all constraint metadata, factories, and UI hints |
| **Factory** | Lambda-based instantiation in `ConstraintDefinition` | Decouples solver from constraint constructor signatures |
| **Strategy** | `IConstraint` protocol in `base.py` | Pluggable constraint algorithms without modifying the solver |
| **Adapter** | `SessionDataManagerAdapter` | Cross-process solver isolation via serialized domain snapshots |
| **Facade** | `services/excel/` package | Decomposes Excel import/export into focused single-responsibility classes |
| **Repository** | Protocol ABCs + `SQLWorkerRepository` / `SQLShiftRepository` | DB abstraction with built-in multi-tenancy via `session_id` |
| **State Machine** | `SolverJobStore` | PENDING -> RUNNING -> COMPLETED/FAILED with atomic transitions |

### Canonical Week Invariant

Schedules represent a *typical week*, not a specific calendar date. Every datetime crossing the API boundary is normalized to a canonical epoch (**Monday 2024-01-01**) before persistence. This prevents subtle bugs where a schedule created on a Thursday behaves differently than one created on a Monday.

- `_to_model()` normalizes on write
- `_to_domain()` denormalizes on read
- All temporal operations use `domain/time_utils.py:TimeWindow`

---

## Tech Stack

### Backend

| Technology | Role |
|-----------|------|
| **Python 3.11+** | Core language — `match/case`, union types, `ProcessPoolExecutor` |
| **FastAPI** | Async REST API with automatic OpenAPI documentation |
| **Google OR-Tools** | MILP solver (CBC primary, SCIP fallback) via `pywraplp` |
| **SQLAlchemy 2.x** | ORM with protocol-based repository pattern |
| **PostgreSQL / SQLite** | Production / development databases |
| **Pydantic v2** | Request validation, constraint config schemas, settings management |
| **pandas + openpyxl** | Excel import/export pipeline |
| **Docker + Gunicorn** | Production deployment with Uvicorn workers |
| **Redis** | Shared rate-limit counters across Gunicorn workers |
| **pytest** | 460+ tests across 5 tiers |

### Frontend

React 19, Vite 7, Tailwind CSS — lightweight UI for data entry and schedule visualization.

---

## Getting Started

### Prerequisites

| Requirement | Version | Check |
|------------|---------|-------|
| Python | 3.11+ | `python --version` |
| pip | latest | `pip --version` |
| Node.js | 18+ (frontend only) | `node --version` |
| Docker | optional | `docker --version` |

### Option A: Run Backend + Frontend Locally

**1. Clone the repository:**

```bash
git clone https://github.com/itaykapon/ShiftApp-Release.git
cd ShiftApp-Release
```

**2. Create a virtual environment and install dependencies:**

```bash
python -m venv .venv

# On macOS/Linux:
source .venv/bin/activate

# On Windows:
.venv\Scripts\activate

pip install -r requirements.txt
```

**3. Set up environment variables:**

```bash
cp .env.example .env
# The defaults work for local development — no changes needed
```

**4. Start the backend server:**

```bash
uvicorn app.main:app --reload
```

The API is now running at `http://localhost:8000`. Interactive Swagger docs at `http://localhost:8000/docs`.

**5. (Optional) Start the frontend:**

```bash
cd frontend
npm install
npm run dev
```

The React dev server runs at `http://localhost:5173` and proxies API requests to the backend.

### Option B: Run with Docker

```bash
docker compose up --build
```

This starts the FastAPI backend + PostgreSQL database. The API is available at `http://localhost:8000`.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./scheduler.db` | Database connection string (`postgresql://...` for production) |
| `SECRET_KEY` | `dev-secret-key-...` | Signs session cookies (auto-generated on Render) |
| `SOLVER_MAX_WORKERS` | `4` | Max concurrent solver subprocesses |
| `CORS_ORIGINS` | `http://localhost:5173` | Allowed frontend origins (comma-separated) |
| `ENVIRONMENT` | `development` | Set to `production` for HSTS and secure cookies |
| `REDIS_URL` | `None` | Redis connection for shared rate-limit counters |
| `LOG_LEVEL` | `INFO` | Root log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

---

## Project Structure

```
ShiftApp/
├── api/routers/                 # FastAPI route handlers (traffic cops only)
│   ├── worker_routes.py
│   ├── shift_routes.py
│   ├── constraint_routes.py
│   ├── solver_routes.py
│   └── import_export_routes.py
├── services/                    # Business logic orchestration
│   ├── solver_service.py        # Async job lifecycle + ProcessPoolExecutor
│   ├── solver_job_store.py      # PENDING -> RUNNING -> COMPLETED state machine
│   ├── session_adapter.py       # Cross-process domain snapshot adapter
│   └── excel/                   # Facade: importer, exporter, constraint mapper
├── solver/
│   ├── solver_engine.py         # MILP formulation + infeasibility diagnosis
│   └── constraints/
│       ├── definitions.py       # <- SINGLE SOURCE OF TRUTH (registry + OCP)
│       ├── base.py              # IConstraint protocol + SolverContext
│       ├── registry.py          # ConstraintRegistry (2-phase: hard then soft)
│       ├── static_hard.py       # Coverage, exclusivity, overlap prevention
│       ├── static_soft.py       # Max hours, preferences, consecutive shifts
│       └── dynamic.py           # Mutual exclusion, co-location
├── repositories/                # DB access layer + canonical week normalization
│   ├── interfaces.py            # Protocol ABCs (IWorkerRepository, IDataManager)
│   ├── sql_worker_repo.py
│   └── sql_shift_repo.py
├── domain/                      # Pure dataclasses — zero I/O, zero dependencies
│   ├── worker_model.py
│   ├── shift_model.py
│   ├── task_model.py
│   └── time_utils.py            # TimeWindow — canonical temporal primitive
├── app/
│   ├── core/config.py           # Pydantic Settings — all env vars, validation
│   ├── db/session.py            # Engine creation, connection pooling
│   └── main.py                  # FastAPI app, lifespan, middleware stack
├── tests/                       # 460+ tests across 5 tiers
│   ├── unit/                    # Pure logic tests (no DB, no I/O)
│   ├── integration/             # Cross-module tests with real in-memory SQLite
│   ├── e2e/                     # Full request -> solver -> response journeys
│   ├── chaos/                   # Concurrency, rollback, corruption tests
│   └── performance/             # Solver timeout, efficiency, volume tests
├── render.yaml                  # Render.com deployment (API + DB + Redis)
├── Dockerfile                   # Multi-stage, non-root, health check
└── docker-compose.yml           # Local dev stack (FastAPI + PostgreSQL)
```

---

## Testing

**460+ tests** across 5 tiers — with **zero business-logic mocking**:

| Tier | Purpose | Mock Policy |
|------|---------|-------------|
| **Unit** | Pure domain logic, constraint math | Mock I/O boundaries only |
| **Integration** | Cross-module flows, DB operations | Real in-memory SQLite — no repository mocks |
| **Contract** | API schema validation, HTTP status codes | Real FastAPI test client |
| **E2E** | Full request -> solver -> response | Real OR-Tools solver — **never mocked** |
| **Chaos** | Concurrency, state corruption, race conditions | Real solver + real DB |

### Infrastructure Swap Pattern

E2E tests run the real solver but swap `ProcessPoolExecutor` for `ThreadPoolExecutor` to avoid subprocess overhead while keeping the full solver execution path:

```python
# tests/e2e/test_true_solve_journey.py
solver_mod.SessionLocal = test_session_factory
solver_mod.get_executor = lambda: ThreadPoolExecutor(max_workers=1)
# Real OR-Tools solver runs in-thread with test database
```

### Running Tests

```bash
# Full suite (460+ tests)
pytest

# Fast feedback (unit + integration only)
pytest -m "unit or integration" -x -q

# With coverage
pytest --cov=. --cov-report=term-missing

# Specific tiers
pytest -m e2e         # End-to-end journeys
pytest -m chaos       # Concurrency and corruption
pytest -m performance # Solver efficiency
```

---

## Deployment

Deployed on **Render.com** with the following production topology:

| Service | Type | Configuration |
|---------|------|---------------|
| **shiftapp-api** | Web Service | Gunicorn (4 workers) + Uvicorn, Python 3.11, 120s timeout |
| **shiftapp-ui** | Static Site | Vite build, SPA rewrite rules |
| **shiftapp-db** | PostgreSQL 16 | Managed instance, connection pooling |
| **shiftapp-rate-limit** | Redis | Shared rate-limit counters across workers |

Production startup is **fail-fast** by design: if the database is unreachable or migrations fail, the application crashes immediately rather than accepting requests in a degraded state.

---

## License

MIT License — see [LICENSE](LICENSE) for details.
