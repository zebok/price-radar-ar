"""Definición y gestión de Canastas de Compra (Core vs. Ampliada).

Permite configurar:
- Canasta Reducida (Core): Los productos habituales personalizados del hogar.
- Canasta Ampliada (Extended): Core + productos clásicos de consumo masivo para benchmark.
- Persistencia y edición sencilla vía archivo JSON (sin necesidad de tocar código).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from loguru import logger


@dataclass
class BasketItem:
    """Definición de un producto a monitorear en la canasta."""

    id: str
    name: str
    query: str
    category: str
    preferred_brands: list[str]
    unit_measure_target: str = "$/item"  # $/kg, $/L, $/u, $/item
    is_core: bool = True
    allow_alternatives: bool = True


# ──────────────────────────────────────────────────────────────
#  1. Canasta Reducida (Personal / Core)
# ──────────────────────────────────────────────────────────────
CORE_BASKET_ITEMS: list[BasketItem] = [
    # ── Almacén ──
    BasketItem(
        id="yerba",
        name="Yerba Mate",
        query="yerba",
        category="almacen",
        preferred_brands=["playadito", "romance"],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="aceite_girasol",
        name="Aceite de Girasol",
        query="aceite girasol",
        category="almacen",
        preferred_brands=[],
        unit_measure_target="$/L",
        is_core=True,
    ),
    BasketItem(
        id="cafe_instantaneo",
        name="Café Instantáneo",
        query="cafe instantaneo",
        category="almacen",
        preferred_brands=["bonafide"],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="arroz",
        name="Arroz",
        query="arroz",
        category="almacen",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="fideos_tirabuzon",
        name="Fideos Tirabuzón",
        query="fideos tirabuzon",
        category="almacen",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="fideos_spaghetti",
        name="Fideos Spaghetti",
        query="fideos spaghetti",
        category="almacen",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="tomate_triturado",
        name="Tomate Triturado / Botella",
        query="tomate triturado",
        category="almacen",
        preferred_brands=[],
        unit_measure_target="$/L",
        is_core=True,
    ),
    BasketItem(
        id="pure_tomate",
        name="Puré de Tomate",
        query="pure de tomate",
        category="almacen",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="lentejas",
        name="Lentejas",
        query="lentejas",
        category="almacen",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="aceitunas",
        name="Aceitunas Descarozadas",
        query="aceitunas descarozadas",
        category="almacen",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="oregano",
        name="Orégano",
        query="oregano",
        category="almacen",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="provenzal",
        name="Provenzal",
        query="provenzal",
        category="almacen",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),

    # ── Carnicería y Pollería ──
    BasketItem(
        id="roast_beef",
        name="Roast Beef",
        query="roast beef",
        category="carniceria",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="entrana",
        name="Entraña",
        query="entrana",
        category="carniceria",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="pata_muslo",
        name="Pollo Pata Muslo",
        query="pata muslo",
        category="carniceria",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="patitas_pollo",
        name="Patitas / Bocaditos de Pollo",
        query="patitas",
        category="carniceria",
        preferred_brands=["patitas", "granja del sol"],
        unit_measure_target="$/kg",
        is_core=True,
    ),

    # ── Lácteos & Fiambrería ──
    BasketItem(
        id="leche_entera",
        name="Leche Entera Cartón 1L",
        query="leche entera carton",
        category="lacteos",
        preferred_brands=["la serenisima"],
        unit_measure_target="$/L",
        is_core=True,
    ),
    BasketItem(
        id="queso_finlandia",
        name="Queso Finlandia Clásico",
        query="queso finlandia",
        category="lacteos",
        preferred_brands=["finlandia"],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="queso_cremoso",
        name="Queso Cremoso / Cuartirolo",
        query="queso cremoso",
        category="lacteos",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="queso_por_salut",
        name="Queso Por Salut",
        query="queso por salut",
        category="lacteos",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="queso_parmesano",
        name="Queso Parmesano en Trozo",
        query="queso parmesano",
        category="lacteos",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="huevos",
        name="Huevos Maple / Pack",
        query="huevos",
        category="lacteos",
        preferred_brands=[],
        unit_measure_target="$/u",
        is_core=True,
    ),

    # ── Verdulería & Frutas ──
    BasketItem(
        id="papa",
        name="Papa",
        query="papa negra",
        category="verduleria",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="batata",
        name="Batata",
        query="batata",
        category="verduleria",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="cebolla",
        name="Cebolla",
        query="cebolla",
        category="verduleria",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="morron_rojo",
        name="Morrón Rojo",
        query="morron rojo",
        category="verduleria",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="mandarina",
        name="Mandarina",
        query="mandarina",
        category="verduleria",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="naranja",
        name="Naranja",
        query="naranja para jugo",
        category="verduleria",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="banana",
        name="Banana",
        query="banana",
        category="verduleria",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="pomelo",
        name="Pomelo",
        query="pomelo",
        category="verduleria",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),

    # ── Frutos Secos ──
    BasketItem(
        id="almendras",
        name="Almendras",
        query="almendras",
        category="frutos_secos",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="avellanas",
        name="Avellanas",
        query="avellanas",
        category="frutos_secos",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="nueces",
        name="Nueces",
        query="nueces peladas",
        category="frutos_secos",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="mani",
        name="Maní",
        query="mani pelado",
        category="frutos_secos",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="mix_frutos_secos",
        name="Mix Frutos Secos",
        query="mix frutos secos",
        category="frutos_secos",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=True,
    ),

    # ── Panadería ──
    BasketItem(
        id="pan_brioche",
        name="Pan Brioche / Hamburguesa",
        query="pan brioche",
        category="panaderia",
        preferred_brands=["bimbo", "artesano"],
        unit_measure_target="$/kg",
        is_core=True,
    ),
    BasketItem(
        id="pan_artesano",
        name="Pan Artesano Lactal",
        query="pan artesano",
        category="panaderia",
        preferred_brands=["bimbo"],
        unit_measure_target="$/kg",
        is_core=True,
    ),

    # ── Limpieza del Hogar ──
    BasketItem(
        id="jabon_liquido_ropa",
        name="Jabón Líquido Ropa",
        query="jabon liquido ropa",
        category="limpieza",
        preferred_brands=[],
        unit_measure_target="$/L",
        is_core=True,
    ),
    BasketItem(
        id="detergente_vajilla",
        name="Detergente Vajilla",
        query="detergente",
        category="limpieza",
        preferred_brands=[],
        unit_measure_target="$/L",
        is_core=True,
    ),
    BasketItem(
        id="lavandina",
        name="Lavandina Líquida / Gel",
        query="lavandina",
        category="limpieza",
        preferred_brands=[],
        unit_measure_target="$/L",
        is_core=True,
    ),
    BasketItem(
        id="limpiador_inodoro",
        name="Limpiador Inodoros",
        query="limpiador inodoro",
        category="limpieza",
        preferred_brands=[],
        unit_measure_target="$/L",
        is_core=True,
    ),
    BasketItem(
        id="multiuso",
        name="Limpiador Multiuso / Desengrasante",
        query="multiuso",
        category="limpieza",
        preferred_brands=[],
        unit_measure_target="$/L",
        is_core=True,
    ),
    BasketItem(
        id="rollo_cocina",
        name="Rollo de Cocina",
        query="rollo de cocina",
        category="limpieza",
        preferred_brands=[],
        unit_measure_target="$/u",
        is_core=True,
    ),
    BasketItem(
        id="papel_higienico",
        name="Papel Higiénico",
        query="papel higienico",
        category="limpieza",
        preferred_brands=[],
        unit_measure_target="$/u",
        is_core=True,
    ),

    # ── Cuidado Personal ──
    BasketItem(
        id="jabon_dove",
        name="Jabón de Tocador Dove",
        query="jabon dove",
        category="cuidado_personal",
        preferred_brands=["dove"],
        unit_measure_target="$/u",
        is_core=True,
    ),
    BasketItem(
        id="pasta_colgate",
        name="Pasta Dental Colgate",
        query="colgate",
        category="cuidado_personal",
        preferred_brands=["colgate"],
        unit_measure_target="$/u",
        is_core=True,
    ),
    BasketItem(
        id="desodorante_nivea",
        name="Desodorante Nivea",
        query="desodorante nivea",
        category="cuidado_personal",
        preferred_brands=["nivea"],
        unit_measure_target="$/u",
        is_core=True,
    ),
]


# ──────────────────────────────────────────────────────────────
#  2. Productos Clásicos Adicionales para Canasta Ampliada (Benchmark)
# ──────────────────────────────────────────────────────────────
BENCHMARK_EXTRA_ITEMS: list[BasketItem] = [
    BasketItem(
        id="harina_000",
        name="Harina 000",
        query="harina 000",
        category="almacen",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=False,
    ),
    BasketItem(
        id="harina_leudante",
        name="Harina Leudante",
        query="harina leudante",
        category="almacen",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=False,
    ),
    BasketItem(
        id="azucar",
        name="Azúcar Común",
        query="azucar comun",
        category="almacen",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=False,
    ),
    BasketItem(
        id="edulcorante",
        name="Edulcorante",
        query="edulcorante liquido",
        category="almacen",
        preferred_brands=[],
        unit_measure_target="$/L",
        is_core=False,
    ),
    BasketItem(
        id="galletitas_dulces",
        name="Galletitas Dulces",
        query="galletitas dulces",
        category="almacen",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=False,
    ),
    BasketItem(
        id="chocolinas",
        name="Chocolinas",
        query="chocolinas",
        category="almacen",
        preferred_brands=["chocolinas"],
        unit_measure_target="$/kg",
        is_core=False,
    ),
    BasketItem(
        id="galletitas_agua",
        name="Galletitas de Agua",
        query="galletitas de agua",
        category="almacen",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=False,
    ),
    BasketItem(
        id="dulce_de_leche",
        name="Dulce de Leche",
        query="dulce de leche",
        category="almacen",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=False,
    ),
    BasketItem(
        id="mermelada",
        name="Mermelada",
        query="mermelada",
        category="almacen",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=False,
    ),
    BasketItem(
        id="atun",
        name="Atún en Lata",
        query="atun al natural",
        category="almacen",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=False,
    ),
    BasketItem(
        id="manteca",
        name="Manteca",
        query="manteca",
        category="lacteos",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=False,
    ),
    BasketItem(
        id="yogur",
        name="Yogur Firme / Bebible",
        query="yogur",
        category="lacteos",
        preferred_brands=[],
        unit_measure_target="$/kg",
        is_core=False,
    ),
    BasketItem(
        id="suavizante",
        name="Suavizante para Ropa",
        query="suavizante para ropa",
        category="limpieza",
        preferred_brands=[],
        unit_measure_target="$/L",
        is_core=False,
    ),
    BasketItem(
        id="shampoo",
        name="Shampoo",
        query="shampoo",
        category="cuidado_personal",
        preferred_brands=[],
        unit_measure_target="$/L",
        is_core=False,
    ),
    BasketItem(
        id="acondicionador",
        name="Acondicionador",
        query="acondicionador",
        category="cuidado_personal",
        preferred_brands=[],
        unit_measure_target="$/L",
        is_core=False,
    ),
    BasketItem(
        id="cerveza",
        name="Cerveza Rubia",
        query="cerveza lata",
        category="bebidas",
        preferred_brands=[],
        unit_measure_target="$/L",
        is_core=False,
    ),
    BasketItem(
        id="gaseosa_cola",
        name="Gaseosa Cola",
        query="gaseosa cola",
        category="bebidas",
        preferred_brands=[],
        unit_measure_target="$/L",
        is_core=False,
    ),
    BasketItem(
        id="agua_mineral",
        name="Agua Mineral sin Gas",
        query="agua mineral sin gas",
        category="bebidas",
        preferred_brands=[],
        unit_measure_target="$/L",
        is_core=False,
    ),
]


EXTENDED_BASKET_ITEMS: list[BasketItem] = CORE_BASKET_ITEMS + BENCHMARK_EXTRA_ITEMS


# ──────────────────────────────────────────────────────────────
#  3. Funciones de Acceso y Persistencia
# ──────────────────────────────────────────────────────────────
DEFAULT_CUSTOM_BASKET_PATH = Path("data/basket_config.json")


def get_basket_items(
    basket_type: str = "core",
    custom_path: Path | None = None,
) -> list[BasketItem]:
    """Retorna los ítems de la canasta según el tipo elegido o archivo personalizado.

    Args:
        basket_type: 'core' (reducida personal) o 'extended' (ampliada de referencia).
        custom_path: Ruta opcional a un archivo JSON con configuración personalizada.
    """
    clean_type = basket_type.strip().lower()

    # Si se pasa un custom_path explícito o existe el archivo en disco
    path = custom_path
    if path and path.exists():
        try:
            items = load_basket_from_file(path)
            if clean_type == "core":
                return [i for i in items if i.is_core]
            return items
        except Exception as e:
            logger.warning("Error leyendo canasta personalizada de {}: {}. Usando predefinida.", path, e)

    if clean_type == "extended":
        return EXTENDED_BASKET_ITEMS
    return CORE_BASKET_ITEMS


def get_basket_queries(
    basket_type: str = "core",
    custom_path: Path | None = None,
) -> list[str]:
    """Retorna únicamente la lista de strings para búsqueda en las tiendas."""
    items = get_basket_items(basket_type=basket_type, custom_path=custom_path)
    return [item.query for item in items]


def save_basket_to_file(items: list[BasketItem], path: Path) -> None:
    """Guarda la canasta en un archivo JSON fácilmente editable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    raw_data = [asdict(item) for item in items]
    path.write_text(json.dumps(raw_data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Canasta guardada en {}", path)


def load_basket_from_file(path: Path) -> list[BasketItem]:
    """Carga la canasta desde un archivo JSON."""
    raw_text = path.read_text(encoding="utf-8")
    raw_data: list[dict[str, Any]] = json.loads(raw_text)
    items: list[BasketItem] = []
    for d in raw_data:
        items.append(BasketItem(**d))
    return items
