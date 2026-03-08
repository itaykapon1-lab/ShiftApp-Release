"""SQLAlchemy Base Declaration.

This module defines the declarative Base class used by all ORM models.
It's kept separate to avoid circular imports between models and database modules.
"""

from sqlalchemy.ext.declarative import declarative_base

# The Base class for all ORM models
Base = declarative_base()
