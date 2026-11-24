"""Pruebas de integración para Resiliencia (Carry-Forward), Gold Marts, DuckDB SQL y Export Web."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from scraper_precios.analytics.duckdb_runner import run_executive_report
from scraper_precios.config import parse_store_selection
from scraper_precios.models import ProductRecord
from scraper_precios.pipeline.cleaning import clean_and_enrich_products, records_to_dataframe
from scraper_precios.pipeline.export_web import export_web_bundle
from scraper_precios.pipeline.gold import build_and_save_gold_marts
from scraper_precios.storage.parquet import (
    load_active_silver_with_freshness,
    load_all_silver,
    save_silver_dataframe,
)


def _rec(store: str, pid: str, ean: str, name: str, price: float, dt_iso: str, list_price: float | None = None) -> ProductRecord:
    return ProductRecord(
        store=store,
        product_id=pid,
        sku_id=pid,
        ean=ean,
        name=name,
        brand="MarcaTest",
        category="Almacén",
        price=Decimal(str(price)),
        list_price=Decimal(str(list_price)) if list_price else None,
        available=True,
        scraped_at=datetime.fromisoformat(dt_iso).replace(tzinfo=UTC),
    )


def test_parse_store_selection_accepts_commas_spaces_and_all():
    avail = ["carrefour", "coto", "dia", "jumbo", "disco", "vea"]
    valid, invalid = parse_store_selection(["carrefour,coto", "dia"], avail)
    assert valid == ["carrefour", "coto", "dia"]
    assert invalid == []

    all_valid, _ = parse_store_selection(["all"], avail)
    assert all_valid == avail


def test_carry_forward_preserves_failed_store_from_previous_day(tmp_path: Path):
    """Si Coto falla el día 2, el catálogo activo conserva sus datos del día 1 como carried_forward."""
    day1 = [
        _rec("carrefour", "c1", "7793704000744", "Yerba Mate Playadito 1 kg", 4000.0, "2026-11-20T09:00:00"),
        _rec("coto", "k1", "7793704000744", "Yerba Mate Playadito 1 kg", 3900.0, "2026-11-20T09:00:00"),
        _rec("jumbo", "j1", "7793704000744", "Yerba Mate Playadito 1 kg", 4500.0, "2026-11-20T09:00:00"),
    ]
    # Día 2: Coto falló y no entró en la partición de hoy; Jumbo sube precio con falso descuento caza-bobos
    day2 = [
        _rec("carrefour", "c1", "7793704000744", "Yerba Mate Playadito 1 kg", 4100.0, "2026-11-22T09:00:00"),
        _rec("jumbo", "j1", "7793704000744", "Yerba Mate Playadito 1 kg", 4900.0, "2026-11-22T09:00:00", list_price=6000.0),
    ]

    save_silver_dataframe(clean_and_enrich_products(records_to_dataframe(day1)), tmp_path, dt="2026-11-20")
    save_silver_dataframe(clean_and_enrich_products(records_to_dataframe(day2)), tmp_path, dt="2026-11-22")

    active_df, freshness = load_active_silver_with_freshness(tmp_path, max_days=7)
    assert set(active_df["store"].unique().to_list()) == {"carrefour", "coto", "jumbo"}
    assert freshness["carrefour"]["status"] == "fresh"
    assert freshness["carrefour"]["age_days"] == 0
    assert freshness["coto"]["status"] == "carried_forward"
    assert freshness["coto"]["age_days"] == 2
    assert freshness["coto"]["last_dt"] == "2026-11-20"

    # Construir Gold Marts y correr las 4 consultas DuckDB SQL
    all_df = load_all_silver(tmp_path, max_days=30)
    gold_paths = build_and_save_gold_marts(active_df, all_df, tmp_path, dt="2026-11-22")
    assert "cross_store_comparison" in gold_paths
    assert "store_competitiveness" in gold_paths
    assert "daily_basket_index" in gold_paths
    assert "price_changes" in gold_paths

    sql_report = run_executive_report(tmp_path)
    assert "01_basket_inflation" in sql_report
    assert "02_store_competitiveness" in sql_report
    assert "03_cazabobos_audit" in sql_report
    assert "04_unit_price_leaders" in sql_report
    # Verificar que las fechas históricas del índice de canasta no sean pisadas por el directorio dt=
    inflation_dates = {r["dt"] for r in sql_report["01_basket_inflation"]}
    assert inflation_dates == {"2026-11-20", "2026-11-22"}
    # Jumbo con promo a $4900 vs Coto a $3900 debe aparecer como caza-bobos
    assert len(sql_report["03_cazabobos_audit"]) >= 1
    assert sql_report["03_cazabobos_audit"][0]["promo_store"] == "jumbo"

    # Exportar bundle estático de PWA
    web_out = tmp_path / "web"
    exported = export_web_bundle(tmp_path, web_out)
    assert exported["catalog"].exists() and exported["catalog"].stat().st_size > 0
    assert exported["analytics"].exists() and exported["analytics"].stat().st_size > 0
    assert exported["quality"].exists() and exported["quality"].stat().st_size > 0
