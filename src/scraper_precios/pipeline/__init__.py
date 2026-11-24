"""Pipeline de procesamiento, analítica Gold, Data Quality y orquestación ETL."""

from .cleaning import (
    clean_and_enrich_products,
    clean_and_enrich_with_report,
    infer_macro_category,
    records_to_dataframe,
)
from .cross_store import (
    compute_store_competitiveness,
    get_top_discounts,
    match_products_cross_store,
)
from .gold import (
    build_and_save_gold_marts,
    build_daily_basket_index_mart,
    build_price_changes_mart,
    build_store_competitiveness_mart,
)
from .quality import build_quality_report, load_latest_quality_report, save_quality_report
from .runner import PipelineRunResult, run_etl_pipeline

__all__ = [
    "PipelineRunResult",
    "build_and_save_gold_marts",
    "build_daily_basket_index_mart",
    "build_price_changes_mart",
    "build_quality_report",
    "build_store_competitiveness_mart",
    "clean_and_enrich_products",
    "clean_and_enrich_with_report",
    "compute_store_competitiveness",
    "get_top_discounts",
    "infer_macro_category",
    "load_latest_quality_report",
    "match_products_cross_store",
    "records_to_dataframe",
    "run_etl_pipeline",
    "save_quality_report",
]
