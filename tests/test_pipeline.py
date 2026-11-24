"""Pruebas unitarias para el pipeline de Polars, multipacks, modelos y cross-store."""

from datetime import UTC, datetime
from decimal import Decimal

import polars as pl

from scraper_precios.models import ProductRecord
from scraper_precios.pipeline.cleaning import (
    clean_and_enrich_products,
    records_to_dataframe,
)
from scraper_precios.pipeline.cross_store import (
    compute_store_competitiveness,
    match_products_cross_store,
)


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


def test_product_record_computations():
    rec = create_sample_record(price=3000.0, list_price=4000.0)
    assert rec.discount_pct == 25.0
    assert rec.product_url is not None


def test_records_to_dataframe():
    records = [
        create_sample_record(store="carrefour", price=3000.0),
        create_sample_record(store="jumbo", price=3200.0),
    ]
    df = records_to_dataframe(records)
    assert len(df) == 2
    assert df["price"].dtype == pl.Float64


def test_clean_and_enrich_regex_units_and_multipacks():
    """Valida extracción de peso/volumen, multipacks (6x473ml, Pack x 6 1 L) y $/kg-$/L-$/u."""
    records = [
        create_sample_record(name="Yerba Mate 1 kg", price=3500.0),
        create_sample_record(name="Café Molido 500 gr", price=4000.0),
        create_sample_record(name="Leche Entera 1 lt", price=1200.0),
        create_sample_record(name="Aceite de Girasol 900 ml", price=2700.0),
        create_sample_record(name="Cerveza Pack x 6", price=6000.0),
        create_sample_record(name="Leche Descremada Pack x 6 1 L", price=9000.0),
        create_sample_record(name="Cerveza Quilmes 6x500ml", price=9000.0),
        create_sample_record(name="Salchichas Viena x 6 190 g", price=1900.0),
    ]

    enriched = clean_and_enrich_products(records_to_dataframe(records))
    assert len(enriched) == 8

    row_kg = enriched.filter(pl.col("name").str.contains("Yerba")).to_dicts()[0]
    assert row_kg["weight_kg"] == 1.0
    assert row_kg["unit_price_std"] == 3500.0
    assert row_kg["unit_measure"] == "$/kg"

    row_gr = enriched.filter(pl.col("name").str.contains("Café")).to_dicts()[0]
    assert row_gr["weight_kg"] == 0.5
    assert row_gr["unit_price_std"] == 8000.0
    assert row_gr["unit_measure"] == "$/kg"

    row_ml = enriched.filter(pl.col("name").str.contains("Aceite")).to_dicts()[0]
    assert row_ml["volume_liters"] == 0.9
    assert row_ml["unit_price_std"] == 3000.0
    assert row_ml["unit_measure"] == "$/L"

    row_pack = enriched.filter(pl.col("name") == "Cerveza Pack x 6").to_dicts()[0]
    assert row_pack["pack_units"] == 6
    assert row_pack["unit_price_std"] == 1000.0
    assert row_pack["unit_measure"] == "$/u"

    # Multipack explícito: Pack x 6 de 1 L = 6.0 L -> $9000 / 6 = $1500/L
    row_milk_pack = enriched.filter(pl.col("name").str.contains("Descremada Pack")).to_dicts()[0]
    assert row_milk_pack["pack_units"] == 6
    assert row_milk_pack["volume_liters"] == 6.0
    assert row_milk_pack["unit_price_std"] == 1500.0
    assert row_milk_pack["unit_measure"] == "$/L"

    # Multipack NxSize: 6x500ml = 3.0 L -> $9000 / 3 = $3000/L
    row_beer_6x = enriched.filter(pl.col("name").str.contains("6x500ml")).to_dicts()[0]
    assert row_beer_6x["pack_units"] == 6
    assert row_beer_6x["volume_liters"] == 3.0
    assert row_beer_6x["unit_price_std"] == 3000.0
    assert row_beer_6x["unit_measure"] == "$/L"

    # Peso total del paquete (sin "pack x" ni "NxSize"): 190 g totales -> $10000/kg
    row_sausage = enriched.filter(pl.col("name").str.contains("Salchichas")).to_dicts()[0]
    assert row_sausage["weight_kg"] == 0.19
    assert row_sausage["unit_price_std"] == 10000.0


def test_cross_store_comparison():
    ean_comun = "7791234567890"
    records = [
        create_sample_record(store="carrefour", ean=ean_comun, price=2000.0),
        create_sample_record(store="jumbo", ean=ean_comun, price=3000.0),
        create_sample_record(store="disco", ean=ean_comun, price=2800.0),
        create_sample_record(store="vea", ean="7799999999999", price=1500.0),
    ]

    df = clean_and_enrich_products(records_to_dataframe(records))
    matched = match_products_cross_store(df)

    assert len(matched) == 1
    row = matched.to_dicts()[0]
    assert row["ean_clean"] == ean_comun
    assert row["stores_count"] == 3
    assert row["cheapest_store"] == "carrefour"
    assert row["min_price"] == 2000.0
    assert row["most_expensive_store"] == "jumbo"
    assert row["max_price"] == 3000.0
    assert row["savings_spread_pct"] == 50.0


def test_store_competitiveness():
    ean_comun = "7791234567890"
    records = [
        create_sample_record(store="carrefour", ean=ean_comun, price=1000.0),
        create_sample_record(store="jumbo", ean=ean_comun, price=1500.0),
    ]

    df = clean_and_enrich_products(records_to_dataframe(records))
    comp = compute_store_competitiveness(df)

    assert len(comp) == 2
    assert comp.filter(pl.col("store") == "carrefour").to_dicts()[0]["times_cheapest"] == 1
    assert comp.filter(pl.col("store") == "jumbo").to_dicts()[0]["times_cheapest"] == 0
