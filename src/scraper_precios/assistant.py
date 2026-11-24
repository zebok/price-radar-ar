"""Asistente y optimizador de lista de compras multi-supermercado.

Analiza una lista arbitraria de productos:
1. Cotiza cada producto en las 6 cadenas de supermercados.
2. Identifica dónde conviene comprar cada ítem individual.
3. Evalúa la mejor tienda para una compra única (1 pedido / 1 viaje).
4. Calcula la 'Compra Partida Óptima' (ahorro máximo comprando cada ítem donde es más barato).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl

from .query_engine import _get_active_silver_df


@dataclass
class ShoppingListItemInput:
    query: str
    quantity: float = 1.0
    unit: str = "u"
    preferred_brand: str | None = None


def optimize_shopping_list(
    items: list[ShoppingListItemInput | str | dict[str, Any]],
) -> dict[str, Any]:
    """Optimiza una lista de compras comparando entre todas las tiendas disponibles."""
    # Normalizar input a lista de objetos tipados
    normalized_items: list[ShoppingListItemInput] = []
    for item in items:
        if isinstance(item, str):
            clean = item.strip()
            if clean:
                normalized_items.append(ShoppingListItemInput(query=clean))
        elif isinstance(item, dict):
            normalized_items.append(
                ShoppingListItemInput(
                    query=item.get("query") or item.get("name") or "",
                    quantity=float(item.get("quantity") or 1.0),
                    unit=item.get("unit") or "u",
                    preferred_brand=item.get("preferred_brand"),
                )
            )
        elif isinstance(item, ShoppingListItemInput):
            normalized_items.append(item)

    if not normalized_items:
        return {
            "total_items_requested": 0,
            "items_analysis": [],
            "stores_summary": {},
            "best_single_store": None,
            "split_strategy": {},
            "recommendation": "La lista de compras está vacía.",
        }

    df = _get_active_silver_df()
    available_stores = (
        df["store"].unique().to_list() if not df.is_empty() else ["carrefour", "coto", "dia", "jumbo", "disco", "vea"]
    )

    items_analysis: list[dict[str, Any]] = []
    store_totals: dict[str, dict[str, Any]] = {
        s: {"total_cost": 0.0, "items_found": 0, "items": [], "missing": []}
        for s in available_stores
    }

    split_items: list[dict[str, Any]] = []
    split_total = 0.0

    for it in normalized_items:
        q_words = [w.lower().strip() for w in it.query.replace("/", " ").replace("-", " ").split() if len(w) > 1]
        stopwords = {"de", "la", "el", "en", "con", "sin", "x", "kg", "gr", "g", "ml", "l"}
        clean_words = [w for w in q_words if w not in stopwords] or q_words

        matched = df
        if not df.is_empty():
            for w in clean_words:
                matched = matched.filter(
                    pl.col("name").str.to_lowercase().str.contains(w, literal=True)
                    | pl.col("brand").fill_null("").str.to_lowercase().str.contains(w, literal=True)
                )

        item_best_store = None
        item_best_price = None
        item_best_name = None
        item_best_url = None
        item_store_prices: dict[str, Any] = {}

        for s in available_stores:
            s_matched = matched.filter(pl.col("store") == s) if not matched.is_empty() else pl.DataFrame()
            if not s_matched.is_empty():
                min_row = s_matched.sort("price", descending=False).row(0, named=True)
                unit_p = float(min_row["price"])
                total_p = round(unit_p * it.quantity, 2)
                disc_pct = min_row.get("verified_discount_pct") or min_row.get("discount_pct")

                item_store_prices[s] = {
                    "product_name": min_row["name"],
                    "unit_price": unit_p,
                    "total_price": total_p,
                    "discount_pct": float(disc_pct) if disc_pct else None,
                    "url": min_row.get("product_url"),
                }

                store_totals[s]["total_cost"] = round(store_totals[s]["total_cost"] + total_p, 2)
                store_totals[s]["items_found"] += 1
                store_totals[s]["items"].append({
                    "query": it.query,
                    "product_name": min_row["name"],
                    "price": total_p,
                })

                if item_best_price is None or total_p < item_best_price:
                    item_best_price = total_p
                    item_best_store = s
                    item_best_name = min_row["name"]
                    item_best_url = min_row.get("product_url")
            else:
                store_totals[s]["missing"].append(it.query)

        if item_best_price is not None:
            split_total += item_best_price
            split_items.append({
                "query": it.query,
                "best_store": item_best_store,
                "product_name": item_best_name,
                "total_price": item_best_price,
                "url": item_best_url,
            })

        items_analysis.append({
            "query": it.query,
            "quantity": it.quantity,
            "unit": it.unit,
            "cheapest_store": item_best_store,
            "cheapest_price": item_best_price,
            "cheapest_product_name": item_best_name,
            "store_options": item_store_prices,
        })

    # Calcular la mejor tienda única
    ranked_stores = [
        (s, data) for s, data in store_totals.items() if data["items_found"] > 0
    ]
    best_single = None
    if ranked_stores:
        ranked_stores.sort(key=lambda x: (-x[1]["items_found"], x[1]["total_cost"]))
        best_name, best_data = ranked_stores[0]
        coverage_pct = round((best_data["items_found"] / len(normalized_items)) * 100, 1)
        best_single = {
            "store": best_name,
            "total_cost": best_data["total_cost"],
            "items_covered": best_data["items_found"],
            "total_items": len(normalized_items),
            "coverage_pct": coverage_pct,
            "missing_items": best_data["missing"],
        }

    # Recomendación humana y para Agente
    rec_parts = []
    if best_single:
        rec_parts.append(
            f"Para una compra única, la tienda más conveniente es {best_single['store'].title()} "
            f"con un total de ${best_single['total_cost']:,.2f} ({best_single['coverage_pct']}% de cobertura)."
        )
        if split_total > 0 and split_total < best_single["total_cost"]:
            diff = round(best_single["total_cost"] - split_total, 2)
            diff_pct = round((diff / best_single["total_cost"]) * 100, 1)
            rec_parts.append(
                f"Si hacés compra partida comprando cada ítem donde está más barato, gastás ${split_total:,.2f} "
                f"(ahorrás ${diff:,.2f} o un {diff_pct}%)."
            )
    else:
        rec_parts.append("No se encontraron coincidencias para los productos de la lista en el catálogo actual.")

    return {
        "total_items_requested": len(normalized_items),
        "items_analysis": items_analysis,
        "stores_summary": store_totals,
        "best_single_store": best_single,
        "split_strategy": {
            "total_cost": round(split_total, 2),
            "items_covered": len(split_items),
            "items": split_items,
        },
        "recommendation": " ".join(rec_parts),
    }
