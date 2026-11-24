"""Pruebas unitarias para los Data Quality Gates técnicos y utilidades de filtros."""

from datetime import UTC, datetime
from decimal import Decimal

import polars as pl

from scraper_precios.filters import (
    classify_rejection_reason,
    is_non_retail_product,
    is_valid_price,
    is_valid_product_candidate,
    matches_user_exclusions,
)
from scraper_precios.models import ProductRecord
from scraper_precios.pipeline.cleaning import (
    clean_and_enrich_products,
    clean_and_enrich_with_report,
    records_to_dataframe,
)
from scraper_precios.pipeline.cross_store import match_products_cross_store


def create_sample_record(
    store: str = "carrefour",
    product_id: str = "123",
    sku_id: str = "456",
    name: str = "Yerba Mate Playadito 1 kg",
    price: float = 3500.0,
    list_price: float | None = 4000.0,
    ean: str | None = "7791234567890",
    brand: str | None = "Playadito",
    available: bool = True,
) -> ProductRecord:
    return ProductRecord(
        store=store,
        product_id=product_id,
        sku_id=sku_id,
        ean=ean,
        name=name,
        brand=brand,
        price=Decimal(str(price)),
        list_price=Decimal(str(list_price)) if list_price else None,
        available=available,
        scraped_at=datetime.now(UTC),
    )


def test_is_valid_price():
    """Valida los límites económicos de sanidad en ARS."""
    assert not is_valid_price(0.0)
    assert not is_valid_price(0.05)
    assert not is_valid_price(49.99)
    assert not is_valid_price(None)
    assert not is_valid_price(500_001.0)
    assert not is_valid_price(45_000_000.0)

    assert is_valid_price(50.0)
    assert is_valid_price(1500.0)
    assert is_valid_price(500_000.0)
    assert is_valid_price(Decimal("3450.50"))


def test_is_non_retail_product():
    """Valida la detección de testers, muestras gratis y productos no comerciales."""
    assert is_non_retail_product("Tester Perfume Acqua Di Gio 100ml")
    assert is_non_retail_product("Muestra gratis Shampoo Sedal")
    assert is_non_retail_product("Dummy display mayonesa")
    assert is_non_retail_product("Demo producto prueba")
    assert is_non_retail_product("Gift card $5000")
    assert is_non_retail_product("")

    assert not is_non_retail_product("Yerba Mate Playadito 1 kg")
    assert not is_non_retail_product("Leche La Serenísima 1 L")
    assert not is_non_retail_product("Cerveza Quilmes Clásica 473 ml")


def test_classify_rejection_reason():
    """Valida la clasificación exacta del motivo de rechazo técnico."""
    assert classify_rejection_reason("Leche", 1500.0, available=False) == "out_of_stock"
    assert classify_rejection_reason("Leche", 1500.0, available=True, available_quantity=0) == "out_of_stock"
    assert classify_rejection_reason("Leche", 0.15, available=True) == "price_out_of_bounds"
    assert classify_rejection_reason("Leche", 800_000.0, available=True) == "price_out_of_bounds"
    assert classify_rejection_reason("Leche", 1500.0, available=True, ean="0000000000000") == "dummy_ean"
    assert classify_rejection_reason("Tester Crema Nivea", 1500.0, available=True) == "non_retail"
    assert classify_rejection_reason("Arroz Lucchetti 1 kg", Decimal("2850"), available=True, ean="7790070123456") is None


def test_normal_groceries_are_never_blocked_by_etl():
    """Valida que el ETL no oculte productos de consumo masivo habituales (azúcar, té, vino, pañales)."""
    assert is_valid_product_candidate("Azúcar Común Ledesma 1kg", 1150.0, available=True)
    assert is_valid_product_candidate("Té Taragüi en saquitos x 25", 1500.0, available=True)
    assert is_valid_product_candidate("Vino Rutini Malbec 750ml", 12000.0, available=True)
    assert is_valid_product_candidate("Pañales Pampers Premium Care G x 36", 18000.0, available=True)
    assert is_valid_product_candidate("Alimento para gato Whiskas 1kg", 6500.0, available=True)


def test_optional_user_exclusions_helper():
    """Valida la utilidad opcional de exclusiones elegidas por un usuario."""
    assert matches_user_exclusions("Vino Malbec 750ml", ["vino", "te"])
    assert matches_user_exclusions("Té verde x 25", ["vino", "te"])
    assert not matches_user_exclusions("Chocolate Block 300g", ["chocolate"], whitelist_exceptions=["block"])
    assert not matches_user_exclusions("Yerba Playadito 1kg", ["vino", "azucar"])


def test_silver_pipeline_enforces_sanity_rules_and_reports_drops():
    """Valida que Silver filtre registros técnicos inválidos y reporte conteos exactos."""
    records = [
        create_sample_record(product_id="p1", name="Aceite Natura 1.5 L", price=2500.0, list_price=3000.0, available=True),
        create_sample_record(product_id="p2", name="Producto Fantasma 2017", price=0.15, available=True),
        create_sample_record(product_id="p3", name="Yogurt Vencido", price=1200.0, available=False),
        create_sample_record(product_id="p4", name="Tester Perfume Polo", price=5000.0, available=True),
        create_sample_record(
            product_id="p5",
            name="Queso Cremoso La Paulina 1 kg",
            price=8000.0,
            list_price=800_000.0,
            available=True,
        ),
    ]

    df, report = clean_and_enrich_with_report(records_to_dataframe(records))

    assert len(df) == 2
    assert report["input_rows"] == 5
    assert report["dropped_out_of_stock"] == 1
    assert report["dropped_price_out_of_bounds"] == 1
    assert report["dropped_non_retail"] == 1
    assert report["output_rows"] == 2

    aceite_row = df.filter(pl.col("name").str.contains("Aceite")).to_dicts()[0]
    assert aceite_row["verified_discount_pct"] == 16.67
    assert aceite_row["macro_category"] == "almacen"

    queso_row = df.filter(pl.col("name").str.contains("Queso")).to_dicts()[0]
    assert queso_row["verified_discount_pct"] is None
    assert queso_row["macro_category"] == "lacteos"


def test_cross_store_spread_gate():
    """Valida que cross-store descarte coincidencias con ratio > 4x (sachets vs packs 24)."""
    ean_reutilizado = "7791234567890"
    records = [
        create_sample_record(store="carrefour", product_id="c1", ean=ean_reutilizado, price=500.0, available=True),
        create_sample_record(store="jumbo", product_id="j1", ean=ean_reutilizado, price=12000.0, available=True),
    ]

    df = clean_and_enrich_products(records_to_dataframe(records))
    matched = match_products_cross_store(df)
    assert len(matched) == 0
