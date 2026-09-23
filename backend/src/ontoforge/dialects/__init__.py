from .base import SqlDialect, XSD
from .databricks import DatabricksDialect
from .postgres import PostgresDialect
from .sqlite import SQLiteDialect, register_functions

# What a deployment can actually read. SQLite compiles mappings correctly and the compiler tests
# use it, but it cannot run the profiling and data-quality SQL the base class emits, so offering
# it as a warehouse would promise a source that half works.
DIALECTS: dict[str, type[SqlDialect]] = {"databricks": DatabricksDialect, "postgres": PostgresDialect}

__all__ = ["SqlDialect", "XSD", "DatabricksDialect", "PostgresDialect", "SQLiteDialect", "register_functions", "DIALECTS"]
