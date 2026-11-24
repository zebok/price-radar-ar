"""Pruebas unitarias para el oráculo de cálculo de benchmark de mercado."""

from scraper_precios.benchmark import compute_market_reference


def test_market_reference_calculation():
    """Valida el cálculo de precio de referencia para un producto y cantidad."""
    ref = compute_market_reference(
        product_query="yerba playadito",
        quantity=2.0,
        unit="kg",
        paid_unit_price=3000.0,
    )
    assert ref.product_query == "yerba playadito"
    assert ref.quantity == 2.0
    assert ref.delta_vs_paid is not None
    assert ref.delta_vs_paid["total_paid"] == 6000.0
