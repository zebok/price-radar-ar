"""Motor analítico SQL embebido sobre el Lakehouse Parquet usando DuckDB."""

from .duckdb_runner import (
    create_lakehouse_connection,
    run_executive_report,
    run_sql_file,
    run_sql_query,
)

__all__ = [
    "create_lakehouse_connection",
    "run_executive_report",
    "run_sql_file",
    "run_sql_query",
]
