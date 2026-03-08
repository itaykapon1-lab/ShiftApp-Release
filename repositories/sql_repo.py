"""Backwards-compatibility shim.

This module re-exports SQLWorkerRepository and SQLShiftRepository from their
canonical locations. New code should import directly from the focused modules:

    from repositories.sql_worker_repo import SQLWorkerRepository
    from repositories.sql_shift_repo import SQLShiftRepository
"""

from repositories.sql_worker_repo import SQLWorkerRepository
from repositories.sql_shift_repo import SQLShiftRepository

__all__ = ["SQLWorkerRepository", "SQLShiftRepository"]
