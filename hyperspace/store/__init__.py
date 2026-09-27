"""hyperspace.store — the product's local SQLite database (row T2.1)."""
from .store import Store, SchemaVersionError, SCHEMA_VERSION

__all__ = ["Store", "SchemaVersionError", "SCHEMA_VERSION"]
