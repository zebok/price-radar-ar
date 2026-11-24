"""Motor de evaluación de promociones y detección de falsos descuentos (Copilot).

Calcula el precio unitario efectivo para promociones complejas argentinas:
- 2do al 70%, 2do al 80%, 2do al 50%
- 3x2, 4x3
- Descuentos directos en porcentaje o pesos
- Descuentos por medio de pago acumulables (MODO, Cuenta DNI, Bancos)

Compara contra el benchmark de mercado en tiempo real y detecta ofertas 'caza-bobos'
(precios de lista inflados donde la promo termina siendo más cara que el precio regular
de la competencia).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class PromoType(StrEnum):
    NONE = "none"
    SEGUNDO_AL_70 = "2do_al_70"
    SEGUNDO_AL_80 = "2do_al_80"
    SEGUNDO_AL_50 = "2do_al_50"
    TRES_POR_DOS = "3x2"
    CUATRO_POR_TRES = "4x3"
    DIRECT_PCT = "direct_pct"
    DIRECT_AMOUNT = "direct_amount"


class DealVerdict(StrEnum):
    EXCELLENT_DEAL = "EXCELLENT_DEAL"  # >15% más barato que el mejor competidor
    GOOD_DEAL = "GOOD_DEAL"            # 5-15% más barato que el mejor competidor
    FAIR_PRICE = "FAIR_PRICE"          # En línea con el mercado (±5%)
    OVERPRICED_OR_CAZABOBOS = "OVERPRICED_OR_CAZABOBOS"  # Más caro que la competencia


@dataclass
class EffectivePriceCalculation:
    regular_unit_price: float
    effective_unit_price: float
    units_required: int
    total_cost_for_bundle: float
    effective_discount_pct: float
    promo_description: str


@dataclass
class MarketBenchmark:
    cheapest_store: str | None
    cheapest_price: float | None
    cheapest_product_name: str | None
    cheapest_product_url: str | None
    average_market_price: float | None
    total_matches_found: int
    competitor_prices: list[dict[str, Any]]


@dataclass
class DealEvaluation:
    product_name: str
    store: str
    calculation: EffectivePriceCalculation
    market: MarketBenchmark
    verdict: DealVerdict
    savings_pct_vs_cheapest: float  # Positivo = más barato que el competidor; Negativo = más caro
    savings_amount_per_unit: float
    is_cazabobos: bool
    is_stockup_worthy: bool
    recommendation: str


def calculate_effective_price(
    regular_price: float,
    promo_type: str | PromoType = PromoType.NONE,
    promo_discount_pct: float | None = None,
    promo_discount_amount: float | None = None,
    payment_discount_pct: float | None = None,
) -> EffectivePriceCalculation:
    """Calcula el costo por unidad real considerando promociones de supermercado y bancarias.

    Args:
        regular_price: Precio regular de lista de 1 unidad.
        promo_type: Tipo de promoción ('2do_al_70', '3x2', etc.).
        promo_discount_pct: Porcentaje si promo_type es 'direct_pct'.
        promo_discount_amount: Monto fijo en $ si promo_type es 'direct_amount'.
        payment_discount_pct: Descuento adicional por banco / billetera (ej: 15% o 20%).
    """
    p_type = promo_type.value if isinstance(promo_type, PromoType) else str(promo_type).strip().lower()

    units_required = 1
    total_cost = regular_price
    desc_parts: list[str] = []

    if p_type == "2do_al_70":
        units_required = 2
        total_cost = regular_price + (regular_price * 0.30)
        desc_parts.append("2do al 70% (35% off prom.)")
    elif p_type == "2do_al_80":
        units_required = 2
        total_cost = regular_price + (regular_price * 0.20)
        desc_parts.append("2do al 80% (40% off prom.)")
    elif p_type == "2do_al_50":
        units_required = 2
        total_cost = regular_price + (regular_price * 0.50)
        desc_parts.append("2do al 50% (25% off prom.)")
    elif p_type == "3x2":
        units_required = 3
        total_cost = regular_price * 2.0
        desc_parts.append("3x2 (33.3% off prom.)")
    elif p_type == "4x3":
        units_required = 4
        total_cost = regular_price * 3.0
        desc_parts.append("4x3 (25% off prom.)")
    elif p_type == "direct_pct":
        pct = max(0.0, float(promo_discount_pct or 0.0))
        total_cost = regular_price * (1.0 - (pct / 100.0))
        desc_parts.append(f"{pct:.0f}% off directo")
    elif p_type == "direct_amount":
        amt = max(0.0, float(promo_discount_amount or 0.0))
        total_cost = max(0.0, regular_price - amt)
        desc_parts.append(f"${amt:.0f} off directo")
    else:
        desc_parts.append("Precio regular")

    # Aplicar descuento de medio de pago / banco si corresponde
    if payment_discount_pct and payment_discount_pct > 0:
        pay_pct = float(payment_discount_pct)
        total_cost = total_cost * (1.0 - (pay_pct / 100.0))
        desc_parts.append(f"+ {pay_pct:.0f}% reintegro/banco")

    effective_unit = total_cost / units_required
    total_discount_pct = 0.0
    if regular_price > 0:
        total_discount_pct = round(((regular_price - effective_unit) / regular_price) * 100, 1)

    return EffectivePriceCalculation(
        regular_unit_price=round(regular_price, 2),
        effective_unit_price=round(effective_unit, 2),
        units_required=units_required,
        total_cost_for_bundle=round(total_cost, 2),
        effective_discount_pct=total_discount_pct,
        promo_description=" ".join(desc_parts),
    )


def evaluate_deal(
    product_name: str,
    store: str,
    regular_price: float,
    promo_type: str | PromoType = PromoType.NONE,
    promo_discount_pct: float | None = None,
    promo_discount_amount: float | None = None,
    payment_discount_pct: float | None = None,
    category: str | None = None,
    market_benchmark: MarketBenchmark | None = None,
) -> DealEvaluation:
    """Evalúa de forma integral una oferta en vivo contrastándola contra la competencia.

    Determina si la promoción es real, excelente, conveniente o un falso descuento caza-bobos.
    """
    calc = calculate_effective_price(
        regular_price=regular_price,
        promo_type=promo_type,
        promo_discount_pct=promo_discount_pct,
        promo_discount_amount=promo_discount_amount,
        payment_discount_pct=payment_discount_pct,
    )

    market = market_benchmark or MarketBenchmark(
        cheapest_store=None,
        cheapest_price=None,
        cheapest_product_name=None,
        cheapest_product_url=None,
        average_market_price=None,
        total_matches_found=0,
        competitor_prices=[],
    )

    # Lógica de comparación vs. benchmark
    cheapest_p = market.cheapest_price
    cheapest_store = market.cheapest_store or "otra tienda"

    is_cazabobos = False
    is_stockup = False

    if cheapest_p is not None and cheapest_p > 0:
        # Ahorro respecto al competidor más barato
        # Positivo = pagamos menos que el competidor; Negativo = pagamos más caro
        diff = cheapest_p - calc.effective_unit_price
        savings_pct = round((diff / cheapest_p) * 100, 1)
        savings_amount = round(diff, 2)

        # Detección de Cazabobos:
        # Si con toda la supuesta promo terminamos pagando más caro que el precio regular
        # de la competencia, o si el precio de lista estaba inflado >25% vs la competencia.
        if calc.effective_unit_price > (cheapest_p * 1.05):
            verdict = DealVerdict.OVERPRICED_OR_CAZABOBOS
            is_cazabobos = True
            recommendation = (
                f"Cuidado: es un falso descuento / caza-bobos. "
                f"Con la promo pagás ${calc.effective_unit_price:,.2f} c/u en {store.title()}, "
                f"pero en {cheapest_store.title()} conseguís el mismo producto a ${cheapest_p:,.2f} "
                f"({abs(savings_pct):.1f}% más barato) sin necesidad de promo."
            )
        elif savings_pct >= 15.0:
            verdict = DealVerdict.EXCELLENT_DEAL
            is_stockup = True
            recommendation = (
                f"Oportunidad real de compra: pagás ${calc.effective_unit_price:,.2f} c/u, "
                f"un {savings_pct:.1f}% menos (${savings_amount:,.2f} c/u) respecto al mejor precio "
                f"del mercado (${cheapest_p:,.2f} en {cheapest_store.title()}). Vale la pena stockearse."
            )
        elif savings_pct >= 5.0:
            verdict = DealVerdict.GOOD_DEAL
            recommendation = (
                f"Buen precio: con la promo te queda ${calc.effective_unit_price:,.2f} c/u, "
                f"{savings_pct:.1f}% por debajo de {cheapest_store.title()} (${cheapest_p:,.2f}). "
                f"Conviene si estás haciendo la compra en {store.title()}."
            )
        else:
            verdict = DealVerdict.FAIR_PRICE
            recommendation = (
                f"Precio alineado al mercado: ${calc.effective_unit_price:,.2f} c/u es similar "
                f"a los precios de {cheapest_store.title()} (${cheapest_p:,.2f}). No es una ganga imperdible, "
                f"pero no pagás de más."
            )
    else:
        # No hay competidores directos encontrados en el catálogo actual
        savings_pct = calc.effective_discount_pct
        savings_amount = round(regular_price - calc.effective_unit_price, 2)
        if calc.effective_discount_pct >= 30.0:
            verdict = DealVerdict.EXCELLENT_DEAL
            is_stockup = True
            recommendation = (
                f"Descuento significativo del {calc.effective_discount_pct:.1f}% "
                f"(pagás ${calc.effective_unit_price:,.2f} vs ${regular_price:,.2f}). "
                f"No se detectaron ofertas rivales activas hoy. Muy recomendable."
            )
        elif calc.effective_discount_pct >= 15.0:
            verdict = DealVerdict.GOOD_DEAL
            recommendation = (
                f"Descuento del {calc.effective_discount_pct:.1f}% sobre precio de lista. "
                f"Pagás ${calc.effective_unit_price:,.2f} c/u."
            )
        else:
            verdict = DealVerdict.FAIR_PRICE
            recommendation = f"Precio de lista regular o descuento leve (${calc.effective_unit_price:,.2f})."

    # Clasificar para stockeo si es almacén/limpieza con fuerte ahorro
    non_perishable_categories = {"almacen", "limpieza", "higiene", "perfumeria", "bebidas"}
    if category and category.lower() in non_perishable_categories and verdict in (DealVerdict.EXCELLENT_DEAL, DealVerdict.GOOD_DEAL):
        is_stockup = True

    return DealEvaluation(
        product_name=product_name,
        store=store,
        calculation=calc,
        market=market,
        verdict=verdict,
        savings_pct_vs_cheapest=savings_pct,
        savings_amount_per_unit=savings_amount,
        is_cazabobos=is_cazabobos,
        is_stockup_worthy=is_stockup,
        recommendation=recommendation,
    )
