"""Pruebas unitarias para el módulo de canastas de compra (baskets.py)."""

from pathlib import Path

from scraper_precios.baskets import (
    CORE_BASKET_ITEMS,
    EXTENDED_BASKET_ITEMS,
    get_basket_items,
    get_basket_queries,
    load_basket_from_file,
    save_basket_to_file,
)


def test_core_and_extended_basket_counts():
    """Valida la integridad de las canastas Core y Extended."""
    assert len(CORE_BASKET_ITEMS) > 40
    assert len(EXTENDED_BASKET_ITEMS) > len(CORE_BASKET_ITEMS)

    core_queries = get_basket_queries("core")
    ext_queries = get_basket_queries("extended")

    assert "yerba" in core_queries
    assert "roast beef" in core_queries
    assert "pan brioche" in core_queries
    assert "almendras" in core_queries
    assert "jabon dove" in core_queries

    # Benchmark items solo en extended
    assert "harina 000" in ext_queries
    assert "cerveza lata" in ext_queries
    assert "harina 000" not in core_queries


def test_basket_json_export_and_import(tmp_path: Path):
    """Valida la serialización y deserialización a archivo JSON."""
    test_json_path = tmp_path / "custom_basket.json"
    items = get_basket_items("core")
    save_basket_to_file(items, test_json_path)

    assert test_json_path.exists()
    loaded = load_basket_from_file(test_json_path)

    assert len(loaded) == len(items)
    assert loaded[0].id == items[0].id
    assert loaded[0].name == items[0].name
