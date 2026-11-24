"""Módulo de gestión de Productos Favoritos / Canasta Habitual del Hogar.

Permite consultar, agregar o quitar productos habituales y enriquecerlos con su
mejor precio actual, tienda más barata y tendencia semanal de mercado.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from .baskets import CORE_BASKET_ITEMS
from .query_engine import find_benchmark_for_product, get_price_trend_for_product

DEFAULT_FAVORITES_PATH = Path("data/favorites.json")


@dataclass
class FavoriteItem:
    """Ítem marcado como favorito / compra habitual."""

    id: str
    name: str
    query: str
    category: str
    preferred_brands: list[str]
    unit_target: str = "$/item"  # $/kg, $/L, $/u
    is_favorite: bool = True
    notes: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()


def _initialize_default_favorites() -> list[FavoriteItem]:
    """Inicializa la lista de favoritos con los productos habituales del hogar (Core Basket)."""
    items: list[FavoriteItem] = []
    for bi in CORE_BASKET_ITEMS:
        items.append(
            FavoriteItem(
                id=bi.id,
                name=bi.name,
                query=bi.query,
                category=bi.category,
                preferred_brands=bi.preferred_brands,
                unit_target=bi.unit_measure_target,
                is_favorite=True,
            )
        )
    return items


def load_favorites(path: Path | None = None) -> list[FavoriteItem]:
    """Carga los productos favoritos guardados en disco, o los predeterminados si aún no existe."""
    file_path = path or DEFAULT_FAVORITES_PATH
    if not file_path.exists():
        defaults = _initialize_default_favorites()
        save_favorites(defaults, file_path)
        return defaults

    try:
        raw_text = file_path.read_text(encoding="utf-8")
        if not raw_text.strip():
            return []
        raw_list: list[dict[str, Any]] = json.loads(raw_text)
        return [FavoriteItem(**d) for d in raw_list]
    except Exception as e:
        logger.error("Error al cargar favoritos desde {}: {}", file_path, e)
        return []


def save_favorites(items: list[FavoriteItem], path: Path | None = None) -> None:
    """Guarda la lista de favoritos en formato JSON."""
    file_path = path or DEFAULT_FAVORITES_PATH
    file_path.parent.mkdir(parents=True, exist_ok=True)
    raw_data = [asdict(item) for item in items]
    file_path.write_text(json.dumps(raw_data, indent=2, ensure_ascii=False), encoding="utf-8")


def add_or_update_favorite(
    item: FavoriteItem,
    path: Path | None = None,
) -> FavoriteItem:
    """Agrega o actualiza un producto en los favoritos."""
    current = load_favorites(path)
    clean_id = item.id.strip().lower()
    updated = [f for f in current if f.id != clean_id]
    item.id = clean_id
    updated.append(item)
    save_favorites(updated, path)
    return item


def remove_favorite(item_id: str, path: Path | None = None) -> bool:
    """Elimina un producto de favoritos."""
    clean_id = item_id.strip().lower()
    current = load_favorites(path)
    filtered = [f for f in current if f.id != clean_id]
    if len(filtered) < len(current):
        save_favorites(filtered, path)
        return True
    return False


def toggle_favorite(item_id: str, path: Path | None = None) -> bool | None:
    """Invierte el estado de is_favorite de un ítem. Retorna el nuevo estado o None si no existe."""
    clean_id = item_id.strip().lower()
    current = load_favorites(path)
    found = False
    new_state = False
    for f in current:
        if f.id == clean_id:
            f.is_favorite = not f.is_favorite
            new_state = f.is_favorite
            found = True
            break
    if found:
        save_favorites(current, path)
        return new_state
    return None


def get_favorites_with_live_prices(
    only_favorites: bool = True,
    path: Path | None = None,
) -> list[dict[str, Any]]:
    """Enriquece los ítems favoritos con su mejor precio y tienda actual en el mercado."""
    items = load_favorites(path)
    if only_favorites:
        items = [i for i in items if i.is_favorite]

    results: list[dict[str, Any]] = []
    for it in items:
        bm = find_benchmark_for_product(it.query, brand=it.preferred_brands[0] if it.preferred_brands else None)
        trend = get_price_trend_for_product(it.query, days=7)
        results.append({
            "id": it.id,
            "name": it.name,
            "query": it.query,
            "category": it.category,
            "preferred_brands": it.preferred_brands,
            "unit_target": it.unit_target,
            "is_favorite": it.is_favorite,
            "notes": it.notes,
            "cheapest_store": bm.cheapest_store,
            "cheapest_price": bm.cheapest_price,
            "cheapest_product_name": bm.cheapest_product_name,
            "average_market_price": bm.average_market_price,
            "competitor_count": len(bm.competitor_prices),
            "competitor_prices": bm.competitor_prices,
            "weekly_trend": {
                "direction": trend.get("direction", "sin_datos"),
                "change_pct": trend.get("change_pct", 0.0),
                "price_start": trend.get("price_start"),
                "price_current": trend.get("price_current"),
            },
        })
    return results
