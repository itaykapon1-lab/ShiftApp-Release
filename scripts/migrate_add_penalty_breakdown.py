#!/usr/bin/env python
"""
Database Migration Script: Add penalty_breakdown Column to solver_jobs

This script adds the penalty_breakdown column to support score explainability.
Safe to run multiple times - checks if column exists before adding.
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text, inspect
from app.db.session import engine, SessionLocal


def column_exists(inspector, table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    try:
        columns = [col['name'] for col in inspector.get_columns(table_name)]
        return column_name in columns
    except Exception:
        return False


def add_penalty_breakdown_column():
    """Add penalty_breakdown column to solver_jobs table."""
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    print("=" * 60)
    print("DATABASE MIGRATION: Adding penalty_breakdown Column")
    print("=" * 60)

    if 'solver_jobs' not in existing_tables:
        print("[SKIP] Table 'solver_jobs' does not exist")
        return

    db = SessionLocal()
    try:
        if not column_exists(inspector, 'solver_jobs', 'penalty_breakdown'):
            print("  Adding 'penalty_breakdown' column...")
            db.execute(text("""
                ALTER TABLE solver_jobs
                ADD COLUMN penalty_breakdown TEXT DEFAULT NULL
            """))
            db.commit()
            print("  [OK] penalty_breakdown added")
        else:
            print("  [SKIP] penalty_breakdown already exists")

        print("\n" + "=" * 60)
        print("MIGRATION COMPLETED SUCCESSFULLY")
        print("=" * 60)

    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] Migration failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    add_penalty_breakdown_column()
