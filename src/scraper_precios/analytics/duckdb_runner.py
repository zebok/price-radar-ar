"""Runner analítico SQL nativo sobre Parquet con DuckDB (sin servidor, sin pyarrow, $0 costo).

Consulta directamente los archivos Apache Parquet particionados tipo Hive usando
`read_parquet(..., hive_partitioning=true, union_by_name=true)` y expone vistas
estándar (`silver_products`, `active_silver_products`, `gold_*`) para ejecutar
los scripts en `sql/*.sql`.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from ..storage.parquet import list_silver_partitions

SQL_DIR = Path(__file__).resolve().parents[3] / "sql"


def _serialize_val(val: Any) -> Any:
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    if isinstance(val, Decimal):
        return float(val)
    return val


def _sql_quote(path: Path | str) -> str:
    return str(path).replace("'", "''")


def _find_latest_gold_file(base_dir: Path, table_name: str) -> Path | None:
    gold_dir = base_dir / "gold"
    if not gold_dir.exists():
        return None
    for d in sorted(gold_dir.glob("dt=*"), reverse=True):
        pq = d / f"{table_name}.parquet"
        if pq.exists():
            return pq
    return None


def _create_empty_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE OR REPLACE VIEW silver_products AS
        SELECT
            CAST(NULL AS VARCHAR) AS store,
            CAST(NULL AS VARCHAR) AS product_id,
            CAST(NULL AS VARCHAR) AS ean_clean,
            CAST(NULL AS VARCHAR) AS name,
            CAST(NULL AS VARCHAR) AS name_clean,
            CAST(NULL AS VARCHAR) AS brand_clean,
            CAST(NULL AS VARCHAR) AS category,
            CAST(NULL AS VARCHAR) AS macro_category,
            CAST(NULL AS DOUBLE)  AS price,
            CAST(NULL AS DOUBLE)  AS list_price,
            CAST(NULL AS DOUBLE)  AS verified_discount_pct,
            CAST(NULL AS DOUBLE)  AS unit_price_std,
            CAST(NULL AS VARCHAR) AS unit_measure,
            CAST(NULL AS BOOLEAN) AS available,
            CAST(NULL AS VARCHAR) AS product_url,
            CAST(NULL AS VARCHAR) AS dt
        WHERE 1 = 0;

        CREATE OR REPLACE VIEW active_silver_products AS
        SELECT * FROM silver_products;

        CREATE OR REPLACE VIEW gold_basket_index AS
        SELECT
            CAST(NULL AS VARCHAR) AS dt,
            CAST(NULL AS VARCHAR) AS store,
            CAST(NULL AS VARCHAR) AS basket_type,
            CAST(NULL AS DOUBLE)  AS basket_cost_ars,
            CAST(NULL AS BIGINT)  AS items_found,
            CAST(NULL AS BIGINT)  AS total_basket_items,
            CAST(NULL AS DOUBLE)  AS coverage_pct
        WHERE 1 = 0;
        """
    )


def create_lakehouse_connection(base_dir: Path) -> duckdb.DuckDBPyConnection:
    """Crea una conexión DuckDB en memoria apuntando directo a los Parquet del Lakehouse."""
    con = duckdb.connect(database=":memory:")
    partitions = list_silver_partitions(base_dir)
    if not partitions:
        _create_empty_schema(con)
        return con

    silver_glob = _sql_quote(base_dir / "silver" / "dt=*" / "products.parquet")
    con.execute(
        f"""
        CREATE OR REPLACE VIEW _silver_raw AS
        SELECT *
        FROM read_parquet('{silver_glob}', hive_partitioning=true, union_by_name=true);
        """
    )

    # Detectar columnas presentes para compatibilidad con snapshots históricos previos a v2.0
    cols = {row[0] for row in con.execute("DESCRIBE _silver_raw").fetchall()}
    macro_select = (
        "COALESCE(macro_category, 'otros') AS macro_category"
        if "macro_category" in cols
        else "'otros' AS macro_category"
    )
    disc_select = (
        "verified_discount_pct"
        if "verified_discount_pct" in cols
        else "discount_pct AS verified_discount_pct"
    )
    dt_select = "CAST(dt AS VARCHAR) AS dt"

    extra_exclude = [c for c in ("dt", "macro_category", "verified_discount_pct") if c in cols]
    exclude_clause = f"EXCLUDE ({', '.join(extra_exclude)})" if extra_exclude else ""

    con.execute(
        f"""
        CREATE OR REPLACE VIEW silver_products AS
        SELECT
            * {exclude_clause},
            {dt_select},
            {macro_select},
            {disc_select}
        FROM _silver_raw;
        """
    )

    # Vista activa con Carry-Forward nativo en SQL:
    # para cada supermercado conserva únicamente su partición `dt` más reciente (last-known-good)
    con.execute(
        """
        CREATE OR REPLACE VIEW active_silver_products AS
        WITH latest_store_dt AS (
            SELECT store, MAX(dt) AS max_dt
            FROM silver_products
            GROUP BY store
        ),
        latest_rows AS (
            SELECT p.*
            FROM silver_products p
            INNER JOIN latest_store_dt l
                ON p.store = l.store AND p.dt = l.max_dt
        )
        SELECT *
        FROM latest_rows
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY store, product_id
            ORDER BY scraped_at DESC NULLS LAST
        ) = 1;
        """
    )

    # Vistas Gold nativas desde Parquet (o tabla vacía tipada si aún no se materializó Gold)
    for view_name, file_stem in (
        ("gold_cross_store", "cross_store_comparison"),
        ("gold_competitiveness", "store_competitiveness"),
        ("gold_basket_index", "daily_basket_index"),
        ("gold_price_changes", "price_changes"),
    ):
        pq = _find_latest_gold_file(base_dir, file_stem)
        if pq is not None:
            con.execute(
                f"CREATE OR REPLACE VIEW {view_name} AS "
                f"SELECT * FROM read_parquet('{_sql_quote(pq)}', hive_partitioning=false);"
            )
        elif view_name == "gold_basket_index":
            con.execute(
                """
                CREATE OR REPLACE VIEW gold_basket_index AS
                SELECT
                    CAST(NULL AS VARCHAR) AS dt,
                    CAST(NULL AS VARCHAR) AS store,
                    CAST(NULL AS VARCHAR) AS basket_type,
                    CAST(NULL AS DOUBLE)  AS basket_cost_ars,
                    CAST(NULL AS BIGINT)  AS items_found,
                    CAST(NULL AS BIGINT)  AS total_basket_items,
                    CAST(NULL AS DOUBLE)  AS coverage_pct
                WHERE 1 = 0;
                """
            )

    return con


def run_sql_query(sql_text: str, base_dir: Path) -> list[dict[str, Any]]:
    """Ejecuta una consulta SQL arbitraria sobre el Lakehouse y retorna filas como dicts."""
    con = create_lakehouse_connection(base_dir)
    try:
        rel = con.sql(sql_text)
        cols = rel.columns
        rows = rel.fetchall()
        return [dict(zip(cols, (_serialize_val(v) for v in r), strict=True)) for r in rows]
    finally:
        con.close()


def run_sql_file(sql_path: Path, base_dir: Path) -> list[dict[str, Any]]:
    """Ejecuta un archivo `.sql` del directorio `sql/` sobre el Lakehouse."""
    return run_sql_query(sql_path.read_text(encoding="utf-8"), base_dir)


def run_executive_report(base_dir: Path, sql_dir: Path | None = None) -> dict[str, list[dict[str, Any]]]:
    """Ejecuta todas las consultas analíticas estándar del directorio `sql/`."""
    target_sql_dir = sql_dir or SQL_DIR
    results: dict[str, list[dict[str, Any]]] = {}
    if not target_sql_dir.exists():
        return results

    con = create_lakehouse_connection(base_dir)
    try:
        for sql_file in sorted(target_sql_dir.glob("*.sql")):
            rel = con.sql(sql_file.read_text(encoding="utf-8"))
            cols = rel.columns
            results[sql_file.stem] = [
                dict(zip(cols, (_serialize_val(v) for v in r), strict=True))
                for r in rel.fetchall()
            ]
    finally:
        con.close()
    return results
