"""Pruebas unitarias para el optimizador de listas de compras."""

from scraper_precios.assistant import optimize_shopping_list


def test_optimize_shopping_list():
    """Valida la cotización y sugerencia de compra para una lista de productos."""
    items = ["yerba playadito", "leche serenisima"]
    result = optimize_shopping_list(items)

    assert result["total_items_requested"] == 2
    assert len(result["items_analysis"]) == 2
    assert "stores_summary" in result
    assert "split_strategy" in result
    assert "recommendation" in result
