"""Pruebas unitarias para el motor de promociones y detección de cazabobos (Evaluator)."""

from scraper_precios.evaluator import (
    DealVerdict,
    MarketBenchmark,
    calculate_effective_price,
    evaluate_deal,
)


def test_calculate_effective_price_2do_al_70():
    """Valida el cálculo del 2do al 70%: 2da unidad al 30%, promedio 35% de descuento."""
    calc = calculate_effective_price(
        regular_price=1000.0,
        promo_type="2do_al_70",
    )
    assert calc.regular_unit_price == 1000.0
    assert calc.units_required == 2
    assert calc.total_cost_for_bundle == 1300.0
    assert calc.effective_unit_price == 650.0
    assert calc.effective_discount_pct == 35.0


def test_calculate_effective_price_3x2():
    """Valida el cálculo de 3x2: pagás 2 llevás 3, promedio 33.3% de descuento."""
    calc = calculate_effective_price(
        regular_price=1500.0,
        promo_type="3x2",
    )
    assert calc.units_required == 3
    assert calc.total_cost_for_bundle == 3000.0
    assert calc.effective_unit_price == 1000.0
    assert calc.effective_discount_pct == 33.3


def test_calculate_effective_price_with_bank_payment():
    """Valida la combinación de 2do al 70% + 15% de reintegro bancario adicional."""
    calc = calculate_effective_price(
        regular_price=1000.0,
        promo_type="2do_al_70",
        payment_discount_pct=15.0,
    )
    # Total antes de banco: 1300. Con 15% off: 1300 * 0.85 = 1105.
    # Por unidad (llevando 2): 1105 / 2 = 552.5
    assert calc.total_cost_for_bundle == 1105.0
    assert calc.effective_unit_price == 552.5
    assert calc.effective_discount_pct == 44.8


def test_evaluate_deal_detects_cazabobos():
    """Valida detección de falso descuento: regular inflado donde la promo es más cara que el rival."""
    # Competidor en Carrefour lo vende a $3000 sin promo
    benchmark = MarketBenchmark(
        cheapest_store="carrefour",
        cheapest_price=3000.0,
        cheapest_product_name="Yerba Playadito 1kg",
        cheapest_product_url=None,
        average_market_price=3100.0,
        total_matches_found=3,
        competitor_prices=[{"store": "carrefour", "price": 3000.0}],
    )

    # Coto lo tiene inflado a $5500 y ofrece '2do al 70%' -> $3575 c/u
    res = evaluate_deal(
        product_name="Yerba Playadito 1kg",
        store="coto",
        regular_price=5500.0,
        promo_type="2do_al_70",
        market_benchmark=benchmark,
    )

    assert res.verdict == DealVerdict.OVERPRICED_OR_CAZABOBOS
    assert res.is_cazabobos is True
    assert "caza-bobos" in res.recommendation.lower()
    assert res.savings_pct_vs_cheapest < 0  # Pagás más caro


def test_evaluate_deal_excellent_opportunity():
    """Valida detección de ganga real (>15% de ahorro vs competencia)."""
    benchmark = MarketBenchmark(
        cheapest_store="carrefour",
        cheapest_price=4500.0,
        cheapest_product_name="Café Bonafide 170g",
        cheapest_product_url=None,
        average_market_price=4800.0,
        total_matches_found=2,
        competitor_prices=[{"store": "carrefour", "price": 4500.0}],
    )

    # Coto tiene precio regular de $4600 y 2do al 70% -> $2990 c/u (33.5% de ahorro vs $4500)
    res = evaluate_deal(
        product_name="Café Bonafide 170g",
        store="coto",
        regular_price=4600.0,
        promo_type="2do_al_70",
        category="almacen",
        market_benchmark=benchmark,
    )

    assert res.verdict == DealVerdict.EXCELLENT_DEAL
    assert res.is_cazabobos is False
    assert res.is_stockup_worthy is True
    assert res.savings_pct_vs_cheapest > 15.0
