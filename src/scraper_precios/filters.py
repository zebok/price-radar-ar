"""Reglas determinísticas de calidad de datos (Data Quality Gates).

Define únicamente reglas técnicas objetivas de sanidad sobre el catálogo:
1. Stock Gate: descarta ítems sin stock o con cantidad 0.
2. Price Sanity Band: descarta precios fuera del rango económico realista en ARS.
3. Non-Retail Gate: descarta testers, muestras gratis, productos demo y gift cards.
4. Dummy EAN Gate: anula o descarta códigos EAN ficticios conocidos.
5. Spread & Promo Gates: acota ratios absurdos cross-store (>4x) y descuentos irreales (>75%).

Las preferencias personales (ej. ocultar rubros o palabras clave específicas)
se gestionan del lado del cliente en la Web App (localStorage) para no alterar
el catálogo analítico ni ocultar productos a otros usuarios.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

# ──────────────────────────────────────────────────────────────
#  1. Umbrales de Sanidad Económica (ARS)
# ──────────────────────────────────────────────────────────────
MIN_PRICE_SANITY_ARS: float = 50.0
MAX_PRICE_SANITY_ARS: float = 500_000.0

# Ratio máximo permitido entre el súper más caro y el más barato para un mismo EAN.
# Evita emparejamientos espurios (ej. sachet individual vs pack x 24 con mismo EAN).
MAX_CROSS_STORE_SPREAD_RATIO: float = 4.0
MAX_CROSS_STORE_SAVINGS_PCT: float = 300.0

# Descuento máximo verificable en retail FMCG (descarta list_price corruptos en centavos).
MAX_VERIFIED_DISCOUNT_PCT: float = 75.0

# ──────────────────────────────────────────────────────────────
#  2. Palabras clave de productos no comerciales / basura técnica
# ──────────────────────────────────────────────────────────────
NON_RETAIL_KEYWORDS: list[str] = [
    "tester",
    "muestra gratis",
    "muestra sin cargo",
    "no vendible",
    "dummy",
    "demo",
    "producto prueba",
    "categoria test",
    "test category",
    "tarjeta de regalo",
    "gift card",
]

NON_RETAIL_REGEX: re.Pattern[str] = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in NON_RETAIL_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

# Códigos EAN ficticios o inválidos conocidos
DUMMY_EANS: set[str] = {
    "0",
    "00000000",
    "0000000000000",
    "1111111111111",
    "9999999999999",
    "1234567890128",
}
KNOWN_BOGUS_EANS: set[str] = DUMMY_EANS


def normalize_text(text: str) -> str:
    """Elimina acentos, diacríticos y normaliza espacios a minúsculas."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    cleaned = "".join(c for c in normalized if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", cleaned).lower().strip()


def is_valid_price(price: float | Decimal | None) -> bool:
    """Verifica si un precio se encuentra dentro de la banda de sanidad en ARS."""
    if price is None:
        return False
    try:
        val = float(price)
        return MIN_PRICE_SANITY_ARS <= val <= MAX_PRICE_SANITY_ARS
    except (ValueError, TypeError):
        return False


def is_non_retail_product(name: str) -> bool:
    """Detecta si el nombre corresponde a un tester, muestra o ítem no comercial."""
    if not name or not name.strip():
        return True
    return bool(NON_RETAIL_REGEX.search(name))


def classify_rejection_reason(
    name: str,
    price: float | Decimal | None,
    available: bool,
    available_quantity: int | None = None,
    ean: str | None = None,
) -> str | None:
    """Evalúa un candidato y retorna el motivo de rechazo técnico, o None si es válido."""
    if not available or (available_quantity is not None and available_quantity <= 0):
        return "out_of_stock"

    if not is_valid_price(price):
        return "price_out_of_bounds"

    if ean is not None and str(ean).strip() in DUMMY_EANS:
        return "dummy_ean"

    if not name or not name.strip():
        return "invalid_name"

    if is_non_retail_product(name):
        return "non_retail"

    return None


def is_valid_product_candidate(
    name: str,
    price: float | Decimal | None,
    available: bool,
    available_quantity: int | None = None,
    ean: str | None = None,
) -> bool:
    """Gatekeeper técnico de primer nivel antes de persistir registros."""
    return (
        classify_rejection_reason(
            name=name,
            price=price,
            available=available,
            available_quantity=available_quantity,
            ean=ean,
        )
        is None
    )


def matches_user_exclusions(
    name: str,
    excluded_keywords: list[str],
    whitelist_exceptions: list[str] | None = None,
) -> bool:
    """Utilidad opcional para aplicar filtros de exclusión elegidos por un usuario."""
    if not name or not excluded_keywords:
        return False

    norm_name = normalize_text(name)
    for exc in whitelist_exceptions or []:
        norm_exc = normalize_text(exc)
        if norm_exc and norm_exc in norm_name:
            return False

    for excl in excluded_keywords:
        norm_excl = normalize_text(excl)
        if not norm_excl:
            continue
        if len(norm_excl) <= 4:
            if re.search(r"\b" + re.escape(norm_excl) + r"\b", norm_name):
                return True
        elif norm_excl in norm_name:
            return True

    return False
