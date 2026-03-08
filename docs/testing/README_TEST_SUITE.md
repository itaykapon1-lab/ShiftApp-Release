# TEST SUITE README

## Overview

This test suite provides **comprehensive integration and E2E testing** for the Shift Scheduling Application. The tests are designed to **validate data integrity**, **expose contract mismatches**, and **predict production failures**.

---

## Test Files

### 1. `conftest.py` - Test Configuration
**Purpose:** Provides pytest fixtures for:
- In-memory SQLite database (fast, isolated)
- FastAPI TestClient with dependency injection override
- Domain object factories

**Key Features:**
- All tests run in isolated `sqlite:///:memory:` database
- Each test function gets a fresh database session
- Automatic cleanup after each test

---

### 2. `test_integration.py` - Data Integrity Tests
**Focus:** Repository layer, JSON serialization, database round-trips

#### Test Classes:

**TestRepositoryDataIntegrity**
- ✅ `test_worker_json_skills_are_dict_not_string` - **CRITICAL TEST**
  - **Purpose:** Verify that skills are stored as `Dict[str, int]`, not `List[str]`
  - **Status:** 🔴 **FAILING** (Exposes bug in `sql_repo.py:80`)
  - **Bug:** `worker.add_skill()` doesn't exist; should be `worker.set_skill_level()`

- ✅ `test_shift_datetime_objects_not_strings` - **CRITICAL TEST**
  - **Purpose:** Ensure datetime fields are Python `datetime` objects, not ISO strings
  - **Status:** ✅ **PASSING** (Repository handles this correctly)

**TestExcelParserIntegration**
- Tests the ExcelParser initialization and method availability
- Mock-based tests (requires sample Excel file for full validation)

**TestSessionIsolation**
- ✅ `test_workers_isolated_by_session`
  - **Purpose:** Verify multi-tenancy (session_id isolation)
  - **Status:** 🔴 **FAILING** (Same `add_skill()` bug)
  - **Expected:** Each session sees only its own workers

**TestDataConsistency**
- ✅ `test_empty_skills_handled_gracefully`
  - **Purpose:** Verify workers with no skills don't crash the system
  
- ✅ `test_null_attributes_field` - **CRITICAL TEST**
  - **Purpose:** What happens if `attributes` JSON column is NULL?
  - **Status:** ✅ **PASSING** (Repository handles with `or {}` fallback)

---

### 3. `test_e2e.py` - API Contract Tests
**Focus:** Frontend-Backend integration, API response structure

#### Test Classes:

**TestAPIContract**
- ✅ `test_get_workers_response_structure`
  - **Purpose:** Verify API returns expected JSON structure for workers
  - **Critical Fields:** `worker_id`, `name`, `session_id`
  
- ✅ `test_get_shifts_response_structure`
  - **Purpose:** Verify shifts endpoint returns correct datetime serialization

**TestFileUploadFlow**
- ✅ `test_file_upload_requires_excel_format`
  - **Purpose:** Verify non-Excel files are rejected with 400 error
  
- ⚠️ `test_file_upload_with_mock_excel`
  - **Purpose:** Test Excel parsing with minimal valid file
  - **Status:** Creates real Excel with pandas/openpyxl

**TestCompleteUserWorkflow**
- ✅ `test_workflow_manual_entry_then_retrieve`
  - **Purpose:** Simulate complete user journey:
    1. Create worker via POST
    2. Create shift via POST
    3. Retrieve both via GET
    4. Verify data integrity

**TestFrontendBackendDataConsistency**
- 🔥 `test_null_attributes_in_api_response` - **CRITICAL TEST**
  - **Purpose:** What does the Frontend receive if `attributes` is NULL?
  - **This is the #1 contract failure risk**

---

## Current Test Results

### Run Summary (as of 2026-01-14)

```bash
$ python -m pytest tests/test_integration.py -v

PASSED:  6 tests
FAILED:  5 tests
WARNINGS: 7 (Pydantic/SQLAlchemy deprecations)
```

### Failing Tests (Expected Failures - Exposing Real Bugs)

1. **`test_worker_json_skills_are_dict_not_string`**
   - **Error:** `AttributeError: 'Worker' object has no attribute 'add_skill'`
   - **Root Cause:** `sql_repo.py:80` uses deprecated method
   - **Fix:** Replace with `worker.set_skill_level(skill_name, level)`

2. **`test_worker_attributes_preservation`**
   - **Error:** Same as #1
   - **Impact:** Workers cannot be retrieved from database

3. **`test_shift_tasks_data_structure`**
   - **Error:** `AttributeError: 'Task' object has no attribute 'requirements'`
   - **Root Cause:** Test expects old Task API; actual API uses `task.options[0].requirements`
   - **Fix:** Update test to use correct Task structure

4. **`test_workers_isolated_by_session`**
   - **Error:** Same as #1 (cascading failure)

5. **`test_very_long_skill_list`**
   - **Error:** Same as #1 (cascading failure)

---

## How to Run Tests

### Install Dependencies
```bash
pip install pytest httpx openpyxl
```

### Run All Tests
```bash
python -m pytest tests/ -v
```

### Run Specific Test File
```bash
python -m pytest tests/test_integration.py -v
python -m pytest tests/test_e2e.py -v
```

### Run Specific Test
```bash
python -m pytest tests/test_integration.py::TestDataConsistency::test_null_attributes_field -v
```

### Run with Coverage
```bash
pip install pytest-cov
python -m pytest tests/ --cov=repositories --cov=api --cov-report=html
```

---

## Test Philosophy

These tests follow **Black-Box + Gray-Box** methodology:

1. **Black-Box:** Tests use the public API (`TestClient`, repository methods)
2. **Gray-Box:** Tests validate internal state (database contents, domain objects)
3. **Defensive:** Tests assume the worst (NULL fields, missing data, malformed Excel)

### Critical Test Assertions

The test suite answers these questions:

| Question | Test |
|----------|------|
| "What if `attributes` is NULL?" | `test_null_attributes_field` |
| "Are datetimes objects or strings?" | `test_shift_datetime_objects_not_strings` |
| "Do skills have levels?" | `test_worker_json_skills_are_dict_not_string` |
| "Can two users work simultaneously?" | `test_workers_isolated_by_session` |
| "What if Excel is malformed?" | `test_file_upload_requires_excel_format` |

---

## Next Steps

### To Fix Failing Tests:

1. **Update `repositories/sql_repo.py:78-80`:**
```python
# BEFORE (BROKEN):
skills_list = attrs.get("skills", [])
for skill in skills_list:
    worker.add_skill(skill)  # ❌ Method doesn't exist

# AFTER (FIXED):
skills_data = attrs.get("skills", {})
if isinstance(skills_data, dict):
    for skill_name, level in skills_data.items():
        worker.set_skill_level(skill_name, level)
elif isinstance(skills_data, list):
    # Backward compatibility for legacy data
    for skill_name in skills_data:
        worker.set_skill_level(skill_name, DEFAULT_SKILL_LEVEL)
```

2. **Update `repositories/sql_repo.py:117`:**
```python
# BEFORE (WRONG):
attributes = {
    "skills": list(worker.skills),  # ❌ Loses skill levels

# AFTER (CORRECT):
attributes = {
    "skills": worker.skills,  # ✅ Preserves Dict[str, int]
}
```

3. **Run tests again:**
```bash
python -m pytest tests/test_integration.py -v
```

Expected result: **11 passed, 0 failed**

---

## Cross-Reference with Audit Report

See `SYSTEM_AUDIT_REPORT.md` for:
- Detailed architecture analysis
- Risk assessments
- Predictive failure scenarios
- Long-term recommendations

The failing tests validate findings in:
- Section 2.1: Skills Data Type Mismatch
- Section 3.1: Repository Method Mismatch
- Section 3.2: Solver Input Validation

---

## Contributing

When adding new tests:

1. **Use descriptive names:** `test_what_when_then` format
2. **Add docstrings:** Explain WHY the test exists, not just WHAT it does
3. **Mark critical tests:** Add `# CRITICAL TEST` comments
4. **Validate both directions:** Create → Save → Retrieve → Assert

---

**Test Suite Version:** 1.0  
**Last Updated:** 2026-01-14  
**Coverage Target:** 90% (Integration: ✅, E2E: ✅, Solver: 🚧 In Progress)
