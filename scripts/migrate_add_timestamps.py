#!/usr/bin/env python
"""
Database Migration Script: Add Timestamp Columns

This script adds the missing created_at and updated_at columns to existing tables.
It uses ALTER TABLE to preserve existing data.

Usage:
    python scripts/migrate_add_timestamps.py

Safe to run multiple times - checks if columns exist before adding.
"""

import sys
import os
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text, inspect
from app.db.session import engine, SessionLocal

# Tables that need timestamp columns
TABLES_TO_MIGRATE = ['workers', 'shifts', 'session_configs']

def column_exists(inspector, table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def add_timestamp_columns():
    """Add created_at and updated_at columns to tables if they don't exist."""
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    print("=" * 60)
    print("DATABASE MIGRATION: Adding Timestamp Columns")
    print("=" * 60)

    db = SessionLocal()
    try:
        for table_name in TABLES_TO_MIGRATE:
            if table_name not in existing_tables:
                print(f"[SKIP] Table '{table_name}' does not exist")
                continue

            print(f"\n[TABLE] {table_name}")

            # Check and add created_at
            if not column_exists(inspector, table_name, 'created_at'):
                print(f"  Adding 'created_at' column...")
                db.execute(text(f"""
                    ALTER TABLE {table_name}
                    ADD COLUMN created_at DATETIME DEFAULT NULL
                """))
                print(f"  [OK] created_at added")
            else:
                print(f"  [SKIP] created_at already exists")

            # Check and add updated_at
            if not column_exists(inspector, table_name, 'updated_at'):
                print(f"  Adding 'updated_at' column...")
                db.execute(text(f"""
                    ALTER TABLE {table_name}
                    ADD COLUMN updated_at DATETIME DEFAULT NULL
                """))
                print(f"  [OK] updated_at added")
            else:
                print(f"  [SKIP] updated_at already exists")

        db.commit()
        print("\n" + "=" * 60)
        print("MIGRATION COMPLETED SUCCESSFULLY")
        print("=" * 60)

    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] Migration failed: {e}")
        raise
    finally:
        db.close()


def verify_schema():
    """Verify all expected columns exist after migration."""
    inspector = inspect(engine)

    print("\n" + "=" * 60)
    print("SCHEMA VERIFICATION")
    print("=" * 60)

    all_ok = True
    for table_name in TABLES_TO_MIGRATE:
        columns = [col['name'] for col in inspector.get_columns(table_name)]

        has_created = 'created_at' in columns
        has_updated = 'updated_at' in columns

        status = "OK" if (has_created and has_updated) else "MISSING COLUMNS"
        print(f"  {table_name}: {status}")

        if not has_created:
            print(f"    [MISSING] created_at")
            all_ok = False
        if not has_updated:
            print(f"    [MISSING] updated_at")
            all_ok = False

    return all_ok


if __name__ == "__main__":
    add_timestamp_columns()
    success = verify_schema()

    if success:
        print("\nAll tables have required timestamp columns.")
        sys.exit(0)
    else:
        print("\n[WARNING] Some columns are still missing!")
        sys.exit(1)
