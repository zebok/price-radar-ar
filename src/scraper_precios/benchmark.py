"""Módulo de cálculo de benchmarks y precios de referencia de mercado.

Determina el precio de referencia (mínimo, promedio y desglose por cadena)
para contrastar compras en comercios de barrio (verdulería, carnicería, almacén)
contra el precio vigente en los supermercados monitoreados.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .evaluator import MarketBenchmark
from .query_engine import find_benchmark_for_product


@dataclass
class MarketReferenceResult:
    """Resultado del cálculo de precio de referencia de mercado."""

    product_query: str
    quantity: float
    unit: str
    cheapest_store: str | None
    cheapest_unit_price: float | None
    cheapest_total_price: float | None
    cheapest_product_name: str | None
    cheapest_product_url: str | None
    average_unit_price: float | None
    average_total_price: float | None
    total_matches_found: int
    competitor_breakdown: list[dict[str, Any]]
    delta_vs_paid: dict[str, Any] | None = None


def compute_market_reference(
    product_query: str,
    quantity: float = 1.0,
    unit: str = "u",
    brand: str | None = None,
    category: str | None = None,
    total_paid: float | None = None,
    paid_unit_price: float | None = None,
) -> MarketReferenceResult:
    """Calcula el precio de referencia de mercado para un producto y cantidad dados.

    Si se provee total_paid o paid_unit_price, calcula el delta de ahorro / sobreprecio.
    """
    bm: MarketBenchmark = find_benchmark_for_product(
        product_name=product_query,
        brand=brand,
        category=category,
    )

    qty = max(0.001, float(quantity))
    cheapest_total = None
    if bm.cheapest_price is not None:
        cheapest_total = round(bm.cheapest_price * qty, 2)

    avg_total = None
    if bm.average_market_price is not None:
        avg_total = round(bm.average_market_price * qty, 2)

    delta_info: dict[str, Any] | None = None
    actual_paid = total_paid
    if actual_paid is None and paid_unit_price is not None:
        actual_paid = round(paid_unit_price * qty, 2)

    if actual_paid is not None:
        savings_vs_cheapest = None
        savings_pct_vs_cheapest = None
        if cheapest_total is not None and cheapest_total > 0:
            savings_vs_cheapest = round(cheapest_total - actual_paid, 2)
            savings_pct_vs_cheapest = round((savings_vs_cheapest / cheapest_total) * 100, 1)

        savings_vs_avg = None
        savings_pct_vs_avg = None
        if avg_total is not None and avg_total > 0:
            savings_vs_avg = round(avg_total - actual_paid, 2)
            savings_pct_vs_avg = round((savings_vs_avg / avg_total) * 100, 1)

        delta_info = {
            "total_paid": actual_paid,
            "savings_vs_cheapest": savings_vs_cheapest,
            "savings_pct_vs_cheapest": savings_pct_vs_cheapest,
            "savings_vs_average": savings_vs_avg,
            "savings_pct_vs_average": savings_pct_vs_avg,
            "is_cheaper_than_supermarket": bool(savings_vs_cheapest and savings_vs_cheapest > 0),
        }

    return MarketReferenceResult(
        product_query=product_query,
        quantity=qty,
        unit=unit,
        cheapest_store=bm.cheapest_store,
        cheapest_unit_price=bm.cheapest_price,
        cheapest_total_price=cheapest_total,
        cheapest_product_name=bm.cheapest_product_name,
        cheapest_product_url=bm.cheapest_product_url,
        average_unit_price=bm.average_market_price,
        average_total_price=avg_total,
        total_matches_found=bm.total_matches_found,
        competitor_breakdown=bm.competitor_prices,
        delta_vs_paid=delta_info,
    )
