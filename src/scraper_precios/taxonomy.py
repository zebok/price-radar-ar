"""Taxonomía FMCG unificada (Fast Moving Consumer Goods) para supermercados argentinos.

Filtra el 80/20 del catálogo de consumo masivo (Alimentos, Bebidas, Lácteos, Frescos,
Congelados, Limpieza y Perfumería) y descarta categorías de baja rotación o no
supermercadistas (Electro, Hogar, Textil, Indumentaria, Bebés, Mascotas, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CanonicalCategory = Literal[
    "almacen",
    "bebidas",
    "lacteos_frescos",
    "carnes_pescados",
    "frutas_verduras",
    "panaderia",
    "congelados",
    "limpieza",
    "perfumeria",
]

CANONICAL_CATEGORIES: list[CanonicalCategory] = [
    "almacen",
    "bebidas",
    "lacteos_frescos",
    "carnes_pescados",
    "frutas_verduras",
    "panaderia",
    "congelados",
    "limpieza",
    "perfumeria",
]


@dataclass(frozen=True, slots=True)
class StoreCategoryTarget:
    """Representa una categoría objetivo a extraer en un supermercado puntual."""

    canonical: CanonicalCategory
    identifier: str  # Slug para VTEX (ej. 'almacen') o group_id para Coto (ej. 'catv00001254')
    display_name: str


# ──────────────────────────────────────────────────────────────
#  Mapeo específico por supermercado
# ──────────────────────────────────────────────────────────────

# Carrefour (VTEX)
CARREFOUR_CATEGORIES: list[StoreCategoryTarget] = [
    StoreCategoryTarget("almacen", "almacen", "Almacén"),
    StoreCategoryTarget("almacen", "desayuno-y-merienda", "Desayuno y Merienda"),
    StoreCategoryTarget("bebidas", "bebidas", "Bebidas"),
    StoreCategoryTarget("lacteos_frescos", "lacteos-y-productos-frescos", "Lácteos y Productos Frescos"),
    StoreCategoryTarget("carnes_pescados", "carnes-y-pescados", "Carnes y Pescados"),
    StoreCategoryTarget("frutas_verduras", "frutas-y-verduras", "Frutas y Verduras"),
    StoreCategoryTarget("panaderia", "panaderia", "Panadería"),
    StoreCategoryTarget("congelados", "congelados", "Congelados"),
    StoreCategoryTarget("limpieza", "limpieza", "Limpieza"),
    StoreCategoryTarget("perfumeria", "perfumeria-y-farmacia", "Perfumería y Farmacia"),
]

# Cencosud: Jumbo, Disco, Vea (VTEX)
CENCOSUD_CATEGORIES: list[StoreCategoryTarget] = [
    StoreCategoryTarget("almacen", "almacen", "Almacén"),
    StoreCategoryTarget("bebidas", "bebidas", "Bebidas"),
    StoreCategoryTarget("lacteos_frescos", "lacteos", "Lácteos"),
    StoreCategoryTarget("lacteos_frescos", "quesos-y-fiambres", "Quesos y Fiambres"),
    StoreCategoryTarget("carnes_pescados", "carnes", "Carnes"),
    StoreCategoryTarget("carnes_pescados", "pescados-y-mariscos", "Pescados y Mariscos"),
    StoreCategoryTarget("frutas_verduras", "frutas-y-verduras", "Frutas y Verduras"),
    StoreCategoryTarget("panaderia", "panaderia-y-pasteleria", "Panadería y Pastelería"),
    StoreCategoryTarget("congelados", "congelados", "Congelados"),
    StoreCategoryTarget("limpieza", "limpieza", "Limpieza"),
    StoreCategoryTarget("perfumeria", "perfumeria", "Perfumería"),
]

# Dia Online (VTEX)
DIA_CATEGORIES: list[StoreCategoryTarget] = [
    StoreCategoryTarget("almacen", "almacen", "Almacén"),
    StoreCategoryTarget("almacen", "desayuno-y-merienda", "Desayuno y Merienda"),
    StoreCategoryTarget("bebidas", "bebidas", "Bebidas"),
    StoreCategoryTarget("lacteos_frescos", "frescos", "Frescos"),
    StoreCategoryTarget("carnes_pescados", "carniceria", "Carnicería"),
    StoreCategoryTarget("frutas_verduras", "frutas-y-verduras", "Frutas y Verduras"),
    StoreCategoryTarget("congelados", "congelados", "Congelados"),
    StoreCategoryTarget("limpieza", "limpieza", "Limpieza"),
    StoreCategoryTarget("perfumeria", "perfumeria", "Perfumería"),
]

# Coto Digital (Constructor.io Groups)
COTO_CATEGORIES: list[StoreCategoryTarget] = [
    StoreCategoryTarget("almacen", "catv00001254", "Almacén"),
    StoreCategoryTarget("lacteos_frescos", "catv00001255", "Frescos (Lácteos, Carnes, Verdulería)"),
    StoreCategoryTarget("bebidas", "catv00001256", "Bebidas"),
    StoreCategoryTarget("perfumeria", "catv00001257", "Perfumería"),
    StoreCategoryTarget("limpieza", "catv00001258", "Limpieza"),
    StoreCategoryTarget("congelados", "catv00001296", "Congelados"),
]

STORE_CATEGORY_REGISTRY: dict[str, list[StoreCategoryTarget]] = {
    "carrefour": CARREFOUR_CATEGORIES,
    "jumbo": CENCOSUD_CATEGORIES,
    "disco": CENCOSUD_CATEGORIES,
    "vea": CENCOSUD_CATEGORIES,
    "dia": DIA_CATEGORIES,
    "coto": COTO_CATEGORIES,
}


def get_store_categories(
    store_key: str,
    canonical_filter: list[str] | None = None,
) -> list[StoreCategoryTarget]:
    """Retorna las categorías objetivo para un supermercado, opcionalmente filtradas.

    Args:
        store_key: Identificador de la tienda ('carrefour', 'jumbo', 'coto', etc.)
        canonical_filter: Lista de categorías canónicas ('almacen', 'bebidas', etc.).
                          Si es None, devuelve todas las categorías FMCG configuradas.
    """
    key = store_key.lower().strip()
    targets = STORE_CATEGORY_REGISTRY.get(key, [])

    if not canonical_filter:
        return list(targets)

    filter_set = {c.lower().strip() for c in canonical_filter}
    return [t for t in targets if t.canonical in filter_set]
