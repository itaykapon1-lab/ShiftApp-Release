[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/) [![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com) [![OR-Tools](https://img.shields.io/badge/OR--Tools-MILP-4285F4?logo=google&logoColor=white)](https://developers.google.com/optimization) [![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.x-D71F00)](https://www.sqlalchemy.org/) [![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/) [![Tests](https://img.shields.io/badge/tests-170%2B%20passing-brightgreen)](#-testing) [![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](#-getting-started) [![License](https://img.shields.io/badge/License-MIT-yellow)](#-license)

# ShiftApp

**An automated employee scheduling system that uses Mixed Integer Linear Programming (MILP) to generate optimal weekly rosters by balancing employer constraints with employee preferences.**

At its core, ShiftApp solves the tedious and complex task of shift scheduling. You input your workers, define the required shifts (and the skills needed for them), and set the rules. The system formulates the scenario as a combinatorial optimization problem and runs a mathematical solver to find the absolute best schedule—minimizing rule violations while maximizing worker satisfaction.

Under the hood, it features a robust constraint-satisfaction engine using binary decision variables, hard/soft constraint decomposition via slack variables, and a 4-stage incremental relaxation algorithm that automatically diagnoses mathematical infeasibility. The constraint system is fully extensible through a metadata-driven registry (enforcing the Open-Closed Principle), meaning new business rules can be added without modifying the core solver engine.

---

## Why This Project Exists

This project started with a personal realization: the theoretical computer science concepts I was learning in university class (specifically, NP-hard combinatorial problems) had an immediate, real-world application right in front of me. 

The opportunity arose when my brother, a shift manager, continuously complained about the agonizing, hours-long process of manually scheduling his employees every week. Trying to balance availability, skills, company rules, and fairness manually was a nightmare. I decided to take the algorithms out of the textbook and build a production-grade system to solve his exact problem. And the rest is history.

While scheduling is a textbook NP-hard problem (reducible from Set Cover), the gap between theory and a production system is enormous. This project bridges that gap through several key architectural pillars:

- **The mathematical core** - A MILP formulation with two sets of binary decision variables (Y for task option selection, X for worker-to-role assignment) linked through a coverage constraint that ensures staffing requirements match the selected configuration.
- **The diagnostic engine** - When the solver returns `INFEASIBLE` (e.g., you need 5 managers but only have 4), a 4-stage incremental relaxation algorithm pinpoints exactly which constraint causes the failure, running asynchronously as a background process.
- **The extensibility architecture** - The constraint registry uses Strategy + Factory patterns so that adding a new constraint type (Pydantic config, solver implementation, API schema, Excel parser, UI metadata) requires a single registration call. The solver engine is closed for modification, open for extension.
- **The isolation boundary** - OR-Tools runs in a subprocess via `ProcessPoolExecutor`. Since SQLAlchemy sessions cannot cross process boundaries, a snapshot adapter serializes the entire domain state into a read-only in-memory data manager, achieving full solver-database decoupling.

- **The frontend** - provides a rich, interactive React UI (including a custom-built interactive onboarding tour) for data entry and result visualization but the heavy engineering depth lives entirely in the backend.
---

## Solver Engine

The solver formulates shift scheduling as a **Mixed Integer Linear Program (MILP)** and solves it using Google OR-Tools' `pywraplp` interface with the **CBC** solver (SCIP fallback).

### Mathematical Formulation

#### Sets

| Symbol | Definition |
|--------|-----------|
| **W** | Set of all workers |
| **S** | Set of all shifts |
| **T_s** | Set of tasks within shift *s* |
| **O_t** | Set of staffing options for task *t* (exactly one must be selected) |
| **R_o** | Set of (role, count) requirements defined by option *o* |
| **E_r** | Set of workers eligible for role *r* (skill + availability filter) |

#### Decision Variables

| Variable | Domain | Semantics |
|----------|--------|-----------|
| **Y**_(s,t,o)_ | {0, 1} | 1 if staffing option *o* is selected for task *t* in shift *s* |
| **X**_(w,s,t,r)_ | {0, 1} | 1 if worker *w* is assigned to role *r* in task *t* during shift *s* |

Variables are constructed by `VariableBuilder` (`solver/variable_builder.py`), which also builds two secondary indexes consumed by constraints:

| Index | Key | Value | Used By |
|-------|-----|-------|---------|
| `worker_shift_assignments` | (worker_id, shift_id) | [X variables] | Intra-shift constraints (exclusivity) |
| `worker_global_assignments` | worker_id | [(Shift, X variable)] | Inter-shift constraints (max hours, consecutive) |

A **circuit breaker** aborts variable construction if the total count exceeds `MAX_SOLVER_VARIABLES` (50,000) to prevent OOM on pathologically large inputs.

#### Structural Constraint (Option Selection)

Exactly one staffing option must be selected per task — this is enforced **before** the constraint registry runs:

```
∀ s ∈ S, t ∈ T_s:   Σ_{o ∈ O_t} Y_(s,t,o) = 1
```

#### Objective Function

The solver **maximizes** total schedule quality:

```
maximize   Σ (preference rewards)  −  Σ (soft constraint penalties)

         = Σ_{w,s,t,r} reward(w,s) · X_(w,s,t,r)
         − Σ_{w} penalty_per_hour · SlackHours_w
         − Σ_{pairs} penalty · ViolationIndicator
         − Σ_{s,t,o} priority_penalty(rank_o) · Y_(s,t,o)
```

Each soft constraint injects its own penalty terms into the objective — the solver balances schedule feasibility against quality trade-offs.

### Constraint Types

| # | Constraint | Type | Technique | Source |
|---|-----------|------|-----------|--------|
| 1 | **Coverage** | Hard | Y-X variable linkage | `static_hard.py` |
| 2 | **Intra-Shift Exclusivity** | Hard | `Sum(X) <= 1` per (worker, shift) | `static_hard.py` |
| 3 | **Overlap Prevention** | Hard | Sorted time-window pairwise exclusion | `static_hard.py` |
| 4 | **Max Hours/Week** | Soft | Continuous slack variable (`NumVar`) penalty | `static_soft.py` |
| 5 | **Avoid Consecutive Shifts** | Soft | Boolean indicator variable (`BoolVar`) penalty | `static_soft.py` |
| 6 | **Worker Preferences** | Soft | Direct objective coefficient injection on X | `static_soft.py` |
| 7 | **Task Option Priority** | Soft | Rank-weighted Y penalty | `static_soft.py` |
| 8 | **Mutual Exclusion** | Dynamic | Pairwise `X_a + X_b <= 1` (hard) or indicator penalty (soft) | `dynamic.py` |
| 9 | **Co-Location** | Dynamic | `X_a == X_b` (hard) or difference indicator penalty (soft) | `dynamic.py` |

Constraints are applied in **two phases** by the `ConstraintRegistry` (`solver/constraints/registry.py`):
1. **Phase 1 — Hard constraints**: Applied first to define the feasible region via `solver.Add()`.
2. **Phase 2 — Soft constraints**: Applied second to inject penalty/reward coefficients via `solver.Objective().SetCoefficient()`.


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
|  Protocol-based ABCs        |  |  solver_engine.py  — MILP formulation   |
|  Multi-tenant filtering     |  |  variable_builder.py — Y/X construction |
|  Canonical week normalizer  |  |  diagnostics_engine.py — 4-stage diag.  |
|  Session guard (FK enforce) |  |  constraints/ — Registry (2-phase OCP)  |
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
| **pytest** | 490+ tests — unit, integration, E2E, chaos |

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
├── .github/workflows/              # CI pipeline
├── alembic/                        # Database migrations (7 versions)
│   └── versions/
├── api/                            # HTTP layer (traffic cops only)
│   ├── routers/
│   │   ├── worker_routes.py
│   │   ├── shift_routes.py
│   │   ├── constraint_routes.py
│   │   ├── solver_routes.py
│   │   ├── import_export_routes.py
│   │   ├── session_routes.py
│   │   └── helpers.py
│   ├── deps.py                     # Dependency injection (DB session, repos)
│   └── routes.py                   # Central router aggregation
├── app/                            # FastAPI application core
│   ├── core/
│   │   ├── config.py               # Pydantic Settings — all env vars, validation
│   │   ├── constants.py            # Solver defaults, penalty values, limits
│   │   ├── rate_limiter.py         # SlowAPI + optional Redis backend
│   │   ├── security_headers.py     # HSTS, X-Frame-Options, CSP
│   │   ├── exception_handlers.py   # Global error handling (dev vs. prod)
│   │   └── exceptions.py           # Custom exception hierarchy
│   ├── db/session.py               # Engine creation, connection pooling
│   ├── schemas/                    # Pydantic request/response models
│   ├── utils/
│   │   ├── date_normalization.py   # Canonical epoch helpers
│   │   └── result_formatter.py     # Solver output presentation
│   └── main.py                     # FastAPI app, lifespan, middleware stack
├── data/                           # ORM models & data-layer utilities
│   ├── models.py                   # SQLAlchemy ORM definitions
│   ├── data_manager.py             # In-memory domain object manager
│   ├── structures.py               # Shared data structures
│   └── unit_of_work.py             # Transaction boundary management
├── domain/                         # Pure dataclasses — zero I/O, zero dependencies
│   ├── worker_model.py
│   ├── shift_model.py
│   ├── task_model.py
│   └── time_utils.py               # TimeWindow — canonical temporal primitive
├── repositories/                   # DB access layer + canonical week normalization
│   ├── interfaces.py               # Protocol ABCs (IWorkerRepository, IDataManager)
│   ├── base.py                     # BaseRepository with shared CRUD logic
│   ├── sql_worker_repo.py
│   ├── sql_shift_repo.py
│   ├── sql_repo.py                 # Aggregate repository (worker + shift access)
│   ├── memory_repo.py              # In-memory fallback (test support)
│   └── _session_guard.py           # Multi-tenancy FK enforcement
├── services/                       # Business logic orchestration
│   ├── solver_service.py           # Async job lifecycle + ProcessPoolExecutor
│   ├── solver_job_store.py         # PENDING → RUNNING → COMPLETED state machine
│   ├── diagnostic_service.py       # Async infeasibility diagnosis orchestration
│   ├── session_adapter.py          # Cross-process domain snapshot adapter
│   ├── excel_service.py            # Facade over the excel/ sub-package
│   └── excel/                      # Excel import/export pipeline
│       ├── importer.py             # Workbook → domain objects
│       ├── exporter.py             # Solver results → workbook
│       ├── state_exporter.py       # Full application state → workbook
│       ├── constraint_mapper.py    # Excel constraints → API schema
│       └── workbook_validator.py   # Structural validation
├── solver/                         # MILP engine (OR-Tools pywraplp)
│   ├── solver_engine.py            # MILP formulation, solve loop, result extraction
│   ├── variable_builder.py         # Y/X variable construction + secondary indexes
│   ├── diagnostics_engine.py       # 4-stage infeasibility diagnosis
│   └── constraints/
│       ├── definitions.py          # ← SINGLE SOURCE OF TRUTH (registry + OCP)
│       ├── base.py                 # IConstraint protocol + SolverContext
│       ├── config.py               # Pydantic config models per constraint
│       ├── registry.py             # ConstraintRegistry (2-phase: hard then soft)
│       ├── static_hard.py          # Coverage, exclusivity, overlap prevention
│       ├── static_soft.py          # Max hours, preferences, consecutive shifts
│       └── dynamic.py              # Mutual exclusion, co-location
├── tests/                          # Test suite (unit, integration, E2E, chaos)
├── frontend/                       # React 19 + Vite 7 + Tailwind CSS
│   ├── src/
│   │   ├── api/                    # HTTP client + endpoint definitions
│   │   ├── components/             # UI components (common, modals, tabs, constraints)
│   │   ├── help/                   # Guided tour engine + contextual help system
│   │   ├── hooks/                  # Custom React hooks (poller, CRUD, solver lifecycle)
│   │   └── utils/                  # Display formatting, constants
│   ├── Dockerfile                  # Frontend container (nginx-based)
│   └── nginx.conf                  # SPA rewrite rules + static asset serving
├── Caddyfile                       # Reverse proxy configuration
├── render.yaml                     # Render.com deployment (API + DB + Redis)
├── Dockerfile                      # Multi-stage, non-root, health check
└── docker-compose.yml              # Local dev stack (FastAPI + PostgreSQL)
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
