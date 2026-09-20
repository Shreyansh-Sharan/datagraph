from .base import SqlDialect, XSD
from .databricks import DatabricksDialect
from .postgres import PostgresDialect
from .sqlite import SQLiteDialect, register_functions

DIALECTS: dict[str, type[SqlDialect]] = {
    "databricks": DatabricksDialect, "postgres": PostgresDialect, "sqlite": SQLiteDialect}

__all__ = ["SqlDialect", "XSD", "DatabricksDialect", "PostgresDialect", "SQLiteDialect", "register_functions", "DIALECTS"]
