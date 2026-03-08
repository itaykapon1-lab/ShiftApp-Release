# ShiftApp - Interview Preparation Q&A

> Comprehensive technical interview preparation covering architecture decisions, AI-assisted development, and deployment strategies.

---

## Section A: Architecture Questions

### 1. "Why is so much logic in routes.py instead of dedicated services?"

**Answer:** This is a conscious trade-off that I made. The current `routes.py` (~500 lines) does contain more logic than a pure "thin controller" pattern would suggest. However:

- The project uses a **service layer** (`solver_service.py`, `excel_service.py`) for complex business logic
- Route handlers primarily do request validation and response formatting
- For a project of this scale, extracting every operation into separate services would add indirection without significant benefit
- If this were a larger team project, I would advocate for stricter separation

**Trade-off acknowledged:** I prioritized velocity over perfect architecture in some areas, which is appropriate for a demonstration project but would need refactoring for a production team environment.

---

### 2. "How does the solver scale with 1000+ workers?"

**Answer:** The current implementation has scaling considerations at multiple levels:

**What works well:**
- OR-Tools MILP solver is highly optimized and can handle large matrices
- Background processing via `ProcessPoolExecutor` prevents blocking the API
- Database queries use indexed lookups

**Scaling limitations:**
- Memory: The constraint matrix grows as O(workers × shifts × constraints)
- Time: Solver may need minutes instead of seconds for very large problems
- Single-process solver: Would need distributed solving for massive scale

**Mitigation strategies I would implement:**
- Time limits with best-found-so-far results
- Problem decomposition (solve by department, then merge)
- Caching of constraint evaluations
- Consider CP-SAT solver which has better scaling characteristics

---

### 3. "Why metadata-driven constraints instead of hardcoding?"

**Answer:** The metadata-driven approach was a deliberate architectural decision that emerged from seeing the pain of the legacy system:

**Problems with hardcoded constraints:**
- Adding a new constraint required changes in 5+ files
- No validation schema meant runtime errors from bad data
- UI had to be manually updated for each constraint type
- Testing required mocking internal implementation details

**Benefits of the registry pattern:**
- **Single source of truth**: `definitions.py` contains everything
- **Self-documenting**: UI metadata lives with implementation
- **Extensible**: Adding a constraint is a single registration
- **Type-safe**: Pydantic models validate configuration

This pattern is inspired by Django's model fields and GraphQL schema definitions.

---

### 4. "Explain the factory pattern in your constraint registry."

**Answer:** Each constraint definition includes a `factory` callable that creates instances:

```python
ConstraintDefinition(
    key="max_hours_per_week",
    config_model=MaxHoursConfig,
    factory=lambda cfg: MaxHoursConstraint(max_hours=cfg.max_hours, penalty=cfg.penalty),
    ...
)
```

**Why factories instead of direct instantiation:**
- **Decoupling**: The registry doesn't need to know constructor signatures
- **Validation**: Config is validated before the factory is called
- **Flexibility**: Complex constraints can have custom initialization logic
- **Testing**: Easy to inject mock factories

The solver service calls `definition.factory(validated_config)` to get constraint instances.

---

### 5. "How do you prevent data leakage between sessions?"

**Answer:** Session isolation is implemented through:

1. **Session ID column**: Every database table (workers, shifts, constraints, assignments) has a `session_id` column
2. **Query filtering**: All repository methods include `WHERE session_id = ?`
3. **API middleware**: Session ID is extracted from cookies/headers and injected into the database context
4. **Cascade deletes**: Clearing a session deletes all related data

**Security considerations:**
- Session IDs are UUIDs (not guessable sequences)
- No cross-session queries are possible through the API
- Background jobs receive explicit session context

This is similar to multi-tenancy patterns in SaaS applications.

---

### 6. "Why ProcessPoolExecutor instead of Celery/Redis?"

**Answer:** This was a deliberate simplification:

**ProcessPoolExecutor advantages:**
- Zero infrastructure dependencies (no Redis, no message broker)
- Simpler deployment (single container)
- Easier debugging (standard Python processes)
- Sufficient for the expected load

**When I would switch to Celery:**
- Multiple API instances needing shared job queue
- Jobs that need retry logic with exponential backoff
- Priority queues for different job types
- Job result persistence beyond process lifetime

For a demonstration project, the added complexity of Celery wasn't justified. The architecture allows swapping the executor implementation without changing the solver service interface.

---

### 7. "How does the solver handle infeasibility?"

**Answer:** This is one of the technical highlights I'm most proud of. When the solver fails:

1. **Detection**: OR-Tools returns `INFEASIBLE` status
2. **Diagnosis**: The system runs an incremental constraint analysis
3. **Identification**: Constraints are disabled one-by-one to find which combination causes the conflict
4. **Reporting**: Returns specific constraint IDs and human-readable explanations

**Example output:**
```json
{
  "status": "infeasible",
  "diagnosis": {
    "conflicting_constraints": ["max_hours_worker_5", "required_shift_coverage_monday"],
    "suggestion": "Worker 5's max hours (20) cannot satisfy Monday coverage requirements (24 hours)"
  }
}
```

This transforms a frustrating "schedule failed" into actionable guidance.

---

### 8. "What happens if the database is down during a solve?"

**Answer:** The current implementation handles this through:

1. **Eager loading**: All data is loaded into memory before the solve starts
2. **Atomic writes**: Results are written in a transaction after solving completes
3. **Job status tracking**: Jobs have status enum (PENDING, RUNNING, COMPLETED, FAILED)

**Failure scenarios:**
- DB down at job start: Request fails with 503, no job created
- DB down during solve: Solve completes in memory, write fails, job marked FAILED
- DB down at result fetch: 503 returned, but results exist and can be retrieved later

**Improvement opportunity:** Add result caching in Redis for resilience.

---

### 9. "How would you add a new constraint type?"

**Answer:** This is designed to be a single-file operation:

```python
# In solver/constraints/definitions.py

# 1. Define the config model
class MinRestBetweenShiftsConfig(ConstraintConfigBase):
    min_hours: int = Field(8, ge=1, le=24)

# 2. Define the implementation (or reference existing)
class MinRestBetweenShiftsConstraint(BaseConstraint):
    def apply(self, model, assignments):
        # Implementation here
        pass

# 3. Register the definition
constraint_definitions.register(
    ConstraintDefinition(
        key="min_rest_between_shifts",
        label="Minimum Rest Between Shifts",
        config_model=MinRestBetweenShiftsConfig,
        implementation_cls=MinRestBetweenShiftsConstraint,
        factory=lambda cfg: MinRestBetweenShiftsConstraint(min_hours=cfg.min_hours),
        ui_fields=[
            UiFieldMeta(name="min_hours", label="Rest Hours", widget=UiFieldWidget.number)
        ]
    )
)
```

That's it. Excel import, API validation, and solver integration all work automatically.

---

### 10. "Why SQLite for development and PostgreSQL for production?"

**Answer:** This is a standard pattern for several reasons:

**Development with SQLite:**
- Zero configuration (file-based)
- Fast for small datasets
- Easy to reset (delete file)
- No external services needed

**Production with PostgreSQL:**
- Concurrent connections (SQLite has write locking)
- Proper connection pooling
- Better performance at scale
- Render.com's ephemeral filesystem makes SQLite impossible

**Compatibility ensured by:**
- SQLAlchemy ORM abstracts database differences
- Using only standard SQL features
- Database URL configurable via environment variable
- Same migrations work on both

---

## Section B: AI & Development Process

### 11. "How did you maintain control while using AI agents?"

**Answer:** My approach was to be the **architect, not the coder**:

1. **I defined the architecture first**: CLAUDE.md documents the metadata-driven pattern, forbidden legacy code, and required patterns
2. **AI executes within constraints**: The AI reads CLAUDE.md and follows the architectural decisions I made
3. **Review and refactor**: I review all generated code and refactor when needed
4. **Domain expertise stays with me**: Business logic decisions, constraint definitions, and system design are mine

The AI accelerated implementation but didn't make architectural decisions.

---

### 12. "How do you verify AI-generated code?"

**Answer:** Multi-layer verification:

1. **Read the code**: I don't accept code I don't understand
2. **Type checking**: Pydantic catches schema violations
3. **Unit tests**: Run existing test suite
4. **Manual testing**: Exercise new features through the UI
5. **Code review mentality**: Would I approve this in a PR?

**Red flags I watch for:**
- Over-engineering (adding abstractions I didn't ask for)
- Security issues (SQL injection, XSS, hardcoded secrets)
- Architecture violations (using deprecated patterns)
- Silent error swallowing

---

### 13. "What's your code review process with AI assistance?"

**Answer:** I treat AI output the same as a junior developer's PR:

1. **Does it solve the problem?** (functional correctness)
2. **Does it follow the architecture?** (check against CLAUDE.md)
3. **Is it minimal?** (reject over-engineering)
4. **Are there security issues?** (secrets, injection, validation)
5. **Will it break existing code?** (run tests)

**Specific checks for AI code:**
- Variable names make sense
- No placeholder comments like "TODO: implement"
- Error handling is appropriate (not excessive)
- No hallucinated imports or APIs

---

### 14. "How do you handle AI suggestions that violate architecture?"

**Answer:** This happened several times during development:

**Example:** AI suggested modifying `config.py` (the deprecated file):

1. **Stopped the change**: Did not apply the modification
2. **Redirected**: Explained that `definitions.py` is the correct location
3. **Updated context**: Made sure CLAUDE.md was included in the prompt
4. **Verified understanding**: Asked AI to explain why `definitions.py` is correct

The CLAUDE.md file exists specifically for this - it's the architectural contract that AI must follow.

---

### 15. "What parts did you write vs what did AI generate?"

**Answer:** Roughly:

**I wrote (or heavily directed):**
- Architecture design and CLAUDE.md documentation
- Constraint registry pattern design
- Solver algorithm selection and configuration
- Database schema design
- API endpoint structure

**AI generated (with my review):**
- Frontend React components (following my structure)
- Boilerplate code (API endpoints, CRUD operations)
- Test scaffolding
- Documentation formatting

**Collaborative:**
- Complex business logic (I described, AI drafted, I refined)
- Bug fixes (AI analyzed, I verified and approved)

---

### 16. "How did you ensure AI understood your architecture?"

**Answer:** Through explicit documentation:

1. **CLAUDE.md**: Comprehensive context file that AI reads at session start
2. **Architecture sections**: Diagrams showing correct data flow
3. **FORBIDDEN sections**: Explicit warnings about legacy code
4. **Examples**: Code snippets showing correct patterns
5. **Tech debt registry**: Known issues AI should avoid

This front-loaded effort saved hours of correcting architectural violations.

---

### 17. "What's the biggest AI mistake you caught and fixed?"

**Answer:** The AI once tried to add a new constraint type by:
- Creating a new file in `solver/constraints/`
- Adding import to `config.py` (deprecated!)
- Not registering in `definitions.py`

This would have worked but violated the metadata-driven architecture, creating tech debt.

**My fix:**
1. Deleted the new file
2. Added the constraint properly to `definitions.py`
3. Updated CLAUDE.md with clearer warnings
4. Added this as an example of what NOT to do

---

### 18. "How do you maintain consistency with multiple AI interactions?"

**Answer:** Several strategies:

1. **Persistent context file**: CLAUDE.md carries across sessions
2. **Git history**: Shows what patterns have been established
3. **Clear naming conventions**: Consistent across codebase
4. **Test suite**: Catches regressions from inconsistent changes

**What I wish I had:**
- A "style guide" section in CLAUDE.md with more examples
- More comprehensive integration tests
- Better documentation of past decisions

---

### 19. "Would you use AI differently in a team setting?"

**Answer:** Yes, several adjustments:

**Additional safeguards:**
- PR reviews by humans for all AI-generated code
- AI-generated code flagged in commit messages
- Style guide enforcement via linters
- More comprehensive test requirements

**Team patterns:**
- Shared context documents (like CLAUDE.md)
- Team agreement on AI usage boundaries
- Regular sync on AI-related learnings

**Concerns:**
- Knowledge atrophy (team doesn't understand AI-written code)
- Inconsistent AI usage across team members
- Security review for AI suggestions

---

### 20. "What are the risks of AI-assisted development?"

**Answer:** Risks I've identified:

1. **Over-reliance**: Accepting code without understanding
2. **Security blind spots**: AI may introduce vulnerabilities
3. **Architecture drift**: Gradual violation of design principles
4. **Knowledge atrophy**: Not learning from implementation details
5. **Hallucinations**: AI may reference non-existent APIs/libraries
6. **Over-engineering**: AI tends to add unnecessary abstractions

**Mitigation:**
- Always read and understand generated code
- Maintain strong architecture documentation
- Run security scans
- Write tests before asking AI to implement
- Be willing to reject and redo

---

## Section C: Render/DevOps Questions

### 21. "How do you handle persistent storage on Render's ephemeral filesystem?"

**Answer:** Render's filesystem resets on every deploy, so:

**Current approach:**
- PostgreSQL database (Render managed service)
- All persistent data in the database
- No file-based storage for user data

**File handling:**
- Uploaded Excel files are processed immediately
- Parsed data goes to database
- Original files are not stored
- Export generates files on-demand (streamed response)

**If I needed file storage:**
- S3 or Cloudflare R2 for file persistence
- Database stores metadata and S3 keys

---

### 22. "What's your database backup strategy?"

**Answer:** Currently relying on Render's managed PostgreSQL:

**Render provides:**
- Daily automated backups
- Point-in-time recovery (7 days)
- Manual backup snapshots

**What I would add for production:**
- Regular backup verification (restore tests)
- Off-site backup to S3
- Automated backup testing script
- Documented recovery runbook

**For a demo/portfolio project**, Render's built-in backups are sufficient.

---

### 23. "How do you manage environment variables securely?"

**Answer:** Multi-layer approach:

1. **No secrets in code**: All sensitive values via environment variables
2. **Render dashboard**: Production secrets set in UI, never in repo
3. **`.env` in `.gitignore`**: Local development uses `.env` file, never committed
4. **Different values per environment**: Dev uses weak secret, prod uses strong random

**Variables managed:**
- `DATABASE_URL` - PostgreSQL connection string
- `SECRET_KEY` - Session signing key
- `CORS_ORIGINS` - Allowed frontend origins
- `ENVIRONMENT` - Deployment context

---

### 24. "What monitoring do you have in production?"

**Answer:** Currently minimal (appropriate for demo):

**Available now:**
- Render's built-in metrics (CPU, memory, response times)
- Render's log viewer
- `/health` endpoint for uptime monitoring

**What I would add for production:**
- **APM**: Sentry or New Relic for error tracking
- **Metrics**: Prometheus + Grafana for custom metrics
- **Logging**: Structured JSON logs to external service
- **Alerting**: PagerDuty/Opsgenie integration
- **Uptime monitoring**: Pingdom or UptimeRobot

---

### 25. "How would you handle a spike in solver jobs?"

**Answer:** Current architecture handles moderate spikes:

**What works now:**
- Background processing doesn't block API
- Jobs are queued in ProcessPoolExecutor
- Multiple workers can run in parallel

**Scaling strategies:**
- Increase Render instance size (vertical scaling)
- Add rate limiting to prevent abuse
- Queue with priority (paid users first)
- Time limits on solver (return best-so-far)

**For true high scale:**
- Separate worker service from API
- Celery + Redis for distributed queue
- Auto-scaling worker pool
- Consider serverless functions for solver jobs

---

### 26. "What's your CI/CD pipeline?"

**Answer:** Currently using Render's native CI/CD:

**On push to main:**
1. Render detects GitHub webhook
2. Builds Docker image
3. Runs health check
4. Zero-downtime deploy

**What I would add:**
- GitHub Actions for pre-deploy checks:
  - Run test suite
  - Lint checks
  - Security scanning (Snyk, Dependabot)
- Staging environment for pre-production testing
- Manual promotion from staging to production

---

### 27. "How do you handle secrets rotation?"

**Answer:** Process for rotating secrets:

1. **Generate new secret**: Strong random value
2. **Update in Render**: Dashboard > Environment Variables
3. **Redeploy**: Automatic on variable change
4. **Verify**: Check health endpoint
5. **Invalidate old**: Sessions signed with old key become invalid

**For database credentials:**
- Render manages PostgreSQL credentials
- Automatic rotation available in managed service

**Improvement needed:** Document rotation runbook and automate where possible.

---

### 28. "What's your rollback strategy?"

**Answer:** Render provides built-in rollback:

1. **Identify issue**: Health check fails or monitoring alerts
2. **Rollback**: Render dashboard > Deploys > Rollback to previous
3. **Investigate**: Review logs from failed deploy
4. **Fix forward**: Push fix to main, redeploy

**Database considerations:**
- Rollback doesn't revert database migrations
- Need backwards-compatible migrations
- Feature flags for risky database changes

---

### 29. "How do you handle database migrations?"

**Answer:** Currently using SQLAlchemy:

**Development:**
- Schema defined in model classes
- `create_all()` for simple cases

**Production approach I would use:**
- Alembic for migration management
- Migrations committed to git
- Run migrations in deploy hook
- Backwards-compatible changes only

**Migration safety rules:**
1. Never drop columns immediately (deprecate first)
2. Add columns as nullable, then backfill, then add NOT NULL
3. Test migrations against production data copy
4. Have rollback migration ready

---

### 30. "What observability tools would you add?"

**Answer:** Three pillars of observability:

**Metrics (Prometheus + Grafana):**
- Request latency histograms
- Solver job duration
- Database query times
- Error rates by endpoint

**Logging (ELK or CloudWatch):**
- Structured JSON logs
- Correlation IDs across requests
- Log levels (INFO, WARN, ERROR)
- Search and alert capabilities

**Tracing (Jaeger or OpenTelemetry):**
- Request flow across services
- Database query tracing
- Background job tracing

**For this demo project**, Render's built-in tools are sufficient, but I understand what production requires.

---

## Quick Reference: Key Talking Points

### Architecture Strengths
- Metadata-driven constraint system
- Clear separation between domain and infrastructure
- Session-based multi-tenancy
- Intelligent infeasibility diagnostics

### AI Development Approach
- Architect first, let AI implement
- CLAUDE.md as the architectural contract
- Review all generated code
- Maintain domain expertise

### Production Readiness
- PostgreSQL for persistence
- Environment-based configuration
- Health check endpoint
- Docker containerization

### Trade-offs Acknowledged
- Some logic in routes.py (acceptable for project size)
- ProcessPoolExecutor instead of Celery (simpler, sufficient)
- Minimal monitoring (appropriate for demo)
- UI metadata incomplete for some constraints

---

*Last updated: February 2026*
