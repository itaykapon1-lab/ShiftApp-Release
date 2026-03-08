[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/) [![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com) [![OR-Tools](https://img.shields.io/badge/OR--Tools-MILP-4285F4?logo=google&logoColor=white)](https://developers.google.com/optimization) [![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.x-D71F00)](https://www.sqlalchemy.org/) [![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/) [![Tests](https://img.shields.io/badge/tests-275%2B%20passing-brightgreen)](#-testing) [![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](#-getting-started) [![License](https://img.shields.io/badge/License-MIT-yellow)](#-license)

# ShiftApp

*Enterprise employee scheduling powered by Mixed Integer Linear Programming.*

---

## 📌 What is ShiftApp?

ShiftApp solves a real-world **NP-hard combinatorial optimization problem**: assigning workers to shifts while satisfying hard constraints and maximizing schedule quality through soft preferences.

At its core is a **MILP solver** built on [Google OR-Tools](https://developers.google.com/optimization). The engine formulates the scheduling problem using two sets of binary decision variables — **Y variables** for task option selection and **X variables** for worker-to-role assignment — linked through a coverage constraint that ensures staffing levels match the selected configuration.

The system supports **9 pluggable constraint types** (3 structural hard constraints, 6 configurable), a 3-phase **infeasibility diagnosis engine** that pinpoints exactly which constraint causes a failure, and a fully async **job execution pipeline** via `ProcessPoolExecutor` with process-isolated solver runs. Multi-tenant session isolation, canonical week date normalization, and a metadata-driven constraint registry round out the backend architecture.

The frontend is a lightweight React UI for data entry and result visualization — the engineering depth lives entirely in the backend.

---

## 💡 Why I Built This

In my university algorithms course, I became fascinated with the gap between textbook optimization theory and production systems that actually solve real problems. Shift scheduling stood out as the perfect bridge: a genuine NP-hard problem that businesses deal with daily, where the mathematical formulation is only half the battle.

The real engineering challenges turned out to be everything *around* the solver:

- **Process isolation** — OR-Tools runs in a subprocess via `ProcessPoolExecutor`, which means SQLAlchemy sessions can't cross process boundaries. I built a snapshot adapter that serializes domain objects into a read-only in-memory data manager, decoupling the solver entirely from the database layer.
- **Temporal normalization** — Schedules represent a *typical week*, not a specific calendar date. Every datetime crossing the API boundary is normalized to a canonical epoch (Monday 2024-01-01) before persistence. This prevents subtle bugs where a schedule created on a Thursday behaves differently than one created on a Monday.
- **Extensible constraint architecture** — Adding a new constraint type requires zero changes to the solver engine. The registry pattern with factory lambdas means a single `ConstraintDefinition` registration wires up Pydantic validation, API schema generation, Excel import parsing, and solver hydration automatically.
- **Rigorous testing** — 275+ tests across 5 tiers (unit, integration, contract, e2e, chaos) with zero business-logic mocking. E2E tests run the real OR-Tools solver, not a mock.

This project represents my approach to software engineering: start with the hard mathematical core, then build production-grade infrastructure around it.

---

## 🏗️ Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                         React Frontend (Vite)                        │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │ HTTP/JSON
┌────────────────────────────────▼─────────────────────────────────────┐
│  API Layer  (api/routers/)                                           │
│  Traffic cops only — no business logic                               │
│  ┌──────────┐ ┌──────────┐ ┌────────────┐ ┌──────────┐ ┌─────────┐ │
│  │ Workers  │ │ Shifts   │ │ Constraints│ │ Solver   │ │ Import/ │ │
│  │ Routes   │ │ Routes   │ │ Routes     │ │ Routes   │ │ Export  │ │
│  └──────────┘ └──────────┘ └────────────┘ └──────────┘ └─────────┘ │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │
┌────────────────────────────────▼─────────────────────────────────────┐
│  Service Layer  (services/)                                          │
│  Business logic, orchestration, transaction boundaries               │
│  ┌─────────────────┐  ┌──────────────┐  ┌─────────────────────────┐ │
│  │ SolverService   │  │ ExcelService │  │ SolverJobStore          │ │
│  │ (job lifecycle) │  │ (Facade)     │  │ (state machine)         │ │
│  └────────┬────────┘  └──────────────┘  └─────────────────────────┘ │
│           │                                                          │
│  ┌────────▼────────────────────────────────────────────────────────┐ │
│  │ SessionDataManagerAdapter                                       │ │
│  │ Serializes domain snapshot for cross-process solver isolation   │ │
│  └─────────────────────────────────────────────────────────────────┘ │
└──────────────┬───────────────────────────────┬───────────────────────┘
               │                               │
┌──────────────▼──────────────┐  ┌─────────────▼──────────────────────┐
│  Repository Layer           │  │  Solver Engine (subprocess)        │
│  (repositories/)            │  │  (solver/)                         │
│                             │  │                                    │
│  Protocol-based ABCs        │  │  OR-Tools pywraplp (CBC/SCIP)     │
│  Multi-tenant filtering     │  │  ConstraintRegistry                │
│  Canonical week normalizer  │  │  Infeasibility Diagnostics        │
└──────────────┬──────────────┘  └────────────────────────────────────┘
               │
┌──────────────▼──────────────┐
│  Domain Layer (domain/)     │
│  Pure Python dataclasses    │
│  Zero I/O, zero imports     │
│  Worker, Shift, Task,       │
│  TimeWindow                 │
└─────────────────────────────┘
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

---

## ⚙️ Solver Engine

The solver formulates shift scheduling as a **Mixed Integer Linear Program** (MILP) and solves it using Google OR-Tools' CBC solver (with SCIP fallback).

### Problem Formulation

**Objective:** Maximize total schedule quality (worker preferences + constraint satisfaction penalties).

**Decision Variables:**

| Variable | Type | Meaning |
|----------|------|---------|
| **Y**_(shift, task, option)_ | Binary | 1 if task option is selected, 0 otherwise |
| **X**_(worker, shift, task, role)_ | Binary | 1 if worker is assigned to role, 0 otherwise |

**Key Invariant:** Exactly one option must be selected per task (`Σ Y = 1`), and the number of workers assigned to each role must equal the staffing requirement of the selected option (`Σ X = Σ(count × Y)`).

### Constraint Types

| # | Constraint | Type | Technique | Source |
|---|-----------|------|-----------|--------|
| 1 | **Coverage** | Hard | Y-X variable linkage | `static_hard.py` |
| 2 | **Intra-Shift Exclusivity** | Hard | `Σ X ≤ 1` per (worker, shift) | `static_hard.py` |
| 3 | **Overlap Prevention** | Hard | Sorted time-window pairwise exclusion | `static_hard.py` |
| 4 | **Max Hours/Week** | Soft | Slack variable penalty | `static_soft.py` |
| 5 | **Avoid Consecutive Shifts** | Soft | Indicator variable penalty | `static_soft.py` |
| 6 | **Worker Preferences** | Soft | Objective coefficient injection | `static_soft.py` |
| 7 | **Task Option Priority** | Soft | Rank-weighted Y penalty | `static_soft.py` |
| 8 | **Mutual Exclusion** | Dynamic | Pairwise `X_a + X_b ≤ 1` | `dynamic.py` |
| 9 | **Co-Location** | Dynamic | Indicator + penalty pairing | `dynamic.py` |

### Slack Variable Technique (Soft Constraints)

The solver uses slack variables to convert hard limits into soft penalties. This is the core technique that makes the schedule *flexible* — the solver can exceed a limit if the overall schedule quality improves:

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

**What this does:** If a worker exceeds `max_hours`, the slack variable `S_w` absorbs the overage. The objective function then penalizes each excess hour at `penalty_per_hour`, letting the solver decide whether the trade-off is worth it.

### Coverage Constraint (Y-X Linkage)

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

### Infeasibility Diagnosis

When the solver returns `INFEASIBLE`, ShiftApp doesn't just report "failed" — it runs a **3-phase diagnostic**:

1. **Pre-Flight Checks** — Detects impossible scenarios before invoking the solver: skill gaps (shifts requiring skills no worker possesses) and availability gaps (shifts on days when no one is available).

2. **Individual Constraint Testing** — Rebuilds a fresh solver context for each hard constraint in isolation. If one constraint alone causes infeasibility, it's immediately identified with a human-readable explanation.

3. **Greedy Combination Testing** — If all constraints pass individually, constraints are stacked incrementally. The first combination that breaks feasibility reveals the conflict: *"The system worked until we added 'overlap_prevention'. It conflicts with: ['coverage']."*

---

## 🧩 Constraint Registry

Adding a new constraint requires **zero changes to the solver engine**. The registry pattern centralizes all metadata in a single `ConstraintDefinition`:

```python
# solver/constraints/definitions.py

constraint_definitions.register(
    ConstraintDefinition(
        key="max_hours_per_week",
        label="Max hours per week",
        description="Limit total weekly hours per worker.",
        constraint_type=ConstraintType.SOFT,
        constraint_kind=ConstraintKind.STATIC,
        config_model=MaxHoursPerWeekConfig,          # Pydantic validation
        implementation_cls=MaxHoursPerWeekConstraint, # Strategy class
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
- Pydantic validation on API input
- `GET /api/v1/constraints/schema` response for dynamic UI rendering
- Excel import parsing via registry lookup
- Factory-based solver hydration at solve time

---

## 🛠️ Tech Stack

### Backend (primary focus)

| Technology | Role |
|-----------|------|
| **Python 3.11+** | Core language — `match/case`, union types |
| **FastAPI** | Async REST API with automatic OpenAPI docs |
| **Google OR-Tools** | MILP solver (CBC primary, SCIP fallback) via `pywraplp` |
| **SQLAlchemy 2.x** | ORM with protocol-based repository pattern |
| **PostgreSQL / SQLite** | Production / development databases |
| **Pydantic v2** | Request validation, constraint config schemas |
| **pandas + openpyxl** | Excel import/export pipeline |
| **ProcessPoolExecutor** | Subprocess isolation for CPU-bound solver |
| **Docker + Gunicorn** | Production deployment with worker processes |
| **pytest** | 275+ tests across 5 tiers |

### Frontend

React 19, Vite 7, Tailwind CSS — lightweight UI for data entry and schedule visualization.

---

## 🚀 Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+ (for frontend)
- Docker (optional)

### Backend

```bash
git clone https://github.com/itaykapon/ShiftApp-Release.git
cd ShiftApp-Release
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

API available at `http://localhost:8000` — interactive docs at `/docs`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Dev server at `http://localhost:5173`.

### Docker

```bash
docker compose up --build
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./scheduler.db` | Database connection (`postgresql://...` for prod) |
| `SECRET_KEY` | `change-me-in-production` | Session cookie signing |
| `SOLVER_MAX_WORKERS` | `4` | Max concurrent solver processes |
| `CORS_ORIGINS` | `http://localhost:5173` | Allowed frontend origins (comma-separated) |

---

## 📁 Project Structure

```
ShiftApp/
├── api/routers/                 # FastAPI route handlers (traffic cops)
│   ├── worker_routes.py
│   ├── shift_routes.py
│   ├── constraint_routes.py
│   ├── solver_routes.py
│   └── import_export_routes.py
├── services/                    # Business logic orchestration
│   ├── solver_service.py        # Job lifecycle + ProcessPoolExecutor
│   ├── solver_job_store.py      # PENDING → RUNNING → COMPLETED state machine
│   ├── session_adapter.py       # Cross-process domain snapshot adapter
│   └── excel/                   # Facade: importer, exporter, constraint mapper
├── solver/
│   ├── solver_engine.py         # MILP formulation + infeasibility diagnosis
│   └── constraints/
│       ├── definitions.py       # ← SINGLE SOURCE OF TRUTH (registry)
│       ├── base.py              # IConstraint protocol + SolverContext
│       ├── static_hard.py       # Coverage, exclusivity, overlap prevention
│       ├── static_soft.py       # Max hours, preferences, consecutive shifts
│       └── dynamic.py           # Mutual exclusion, co-location
├── repositories/                # DB access layer + canonical week normalization
│   ├── interfaces.py            # Protocol ABCs (IWorkerRepository, IDataManager)
│   ├── sql_worker_repo.py
│   └── sql_shift_repo.py
├── domain/                      # Pure dataclasses — zero I/O
│   ├── worker_model.py
│   ├── shift_model.py
│   └── task_model.py
├── tests/                       # 275+ tests across 5 tiers
└── Dockerfile
```

---

## 🧪 Testing

**275+ tests** across 5 tiers — with **zero business-logic mocking**:

| Tier | Purpose | Mock Policy |
|------|---------|-------------|
| **Unit** | Pure domain logic | Mock I/O boundaries only |
| **Integration** | Cross-module flows | Real in-memory SQLite — no repository mocks |
| **Contract** | API schema validation | Real FastAPI test client |
| **E2E** | Full request → solver → response | Real OR-Tools solver — **never mocked** |
| **Chaos** | Concurrency and state corruption | Real solver + real DB + race conditions |

### Infrastructure Swap Pattern

E2E tests run the real solver but swap `ProcessPoolExecutor` for `ThreadPoolExecutor` to avoid subprocess overhead while keeping the full solver execution path:

```python
# tests/e2e/test_true_solve_journey.py
solver_mod.SessionLocal = test_session_factory
solver_mod.get_executor = lambda: ThreadPoolExecutor(max_workers=1)
# → Real OR-Tools solver runs in-thread with test database
```

```bash
# Run all tests
pytest

# Fast feedback (unit + integration)
pytest -m "unit or integration" -x -q

# With coverage
pytest --cov=. --cov-report=term-missing
```

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.
