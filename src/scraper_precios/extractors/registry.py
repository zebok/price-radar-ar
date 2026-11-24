"""Registro central (Factory) de extractores de supermercados.

Soporta:
- VTEX: Carrefour, Jumbo, Disco, Vea, Dia
- Constructor.io: Coto Digital
"""

from __future__ import annotations

from typing import Any

from ..config import STORES
from .base import BaseExtractor
from .coto import CotoExtractor
from .vtex import VTEXExtractor

ADDITIONAL_STORES: list[str] = ["coto"]


def list_available_stores() -> list[str]:
    """Lista las claves de todas las tiendas soportadas."""
    return list(STORES.keys()) + ADDITIONAL_STORES


def get_extractor(store_key: str, **kwargs: Any) -> BaseExtractor:
    """Instancia y retorna el extractor adecuado para la tienda solicitada.

    Args:
        store_key: Identificador de la tienda ('carrefour', 'jumbo', 'disco', 'vea', 'dia', 'coto')
        **kwargs: Opciones pasadas al constructor (max_concurrent, request_delay_seconds, etc.)

    Raises:
        ValueError: Si la tienda no está registrada.
    """
    key = store_key.lower().strip()

    if key == "coto":
        return CotoExtractor(**kwargs)

    if key in STORES:
        store_def = STORES[key]
        return VTEXExtractor(store=store_def, store_key=key, **kwargs)

    raise ValueError(
        f"Tienda '{store_key}' no soportada. Disponibles: {', '.join(list_available_stores())}"
    )
