"""Pruebas unitarias para el módulo de taxonomía FMCG y categorías."""

from scraper_precios.taxonomy import (
    CANONICAL_CATEGORIES,
    get_store_categories,
)


def test_canonical_categories():
    """Valida la lista de categorías canónicas FMCG."""
    assert "almacen" in CANONICAL_CATEGORIES
    assert "bebidas" in CANONICAL_CATEGORIES
    assert "lacteos_frescos" in CANONICAL_CATEGORIES
    assert "limpieza" in CANONICAL_CATEGORIES
    assert "perfumeria" in CANONICAL_CATEGORIES
    # Validar que NO contenga categorías excluidas solicitadas por el usuario
    assert "mascotas" not in CANONICAL_CATEGORIES
    assert "bebe" not in CANONICAL_CATEGORIES
    assert "electro" not in CANONICAL_CATEGORIES
    assert "hogar" not in CANONICAL_CATEGORIES


def test_store_category_mappings():
    """Valida que todas las tiendas principales tengan categorías mapeadas."""
    expected_stores = ["carrefour", "jumbo", "disco", "vea", "dia", "coto"]
    for store in expected_stores:
        targets = get_store_categories(store)
        assert len(targets) > 0, f"La tienda {store} no tiene categorías FMCG asignadas"
        # Verificar que todos los targets tengan identifier y canonical
        for t in targets:
            assert t.canonical in CANONICAL_CATEGORIES
            assert len(t.identifier) > 0
            assert len(t.display_name) > 0


def test_category_filtering():
    """Valida el filtrado selectivo por categorías canónicas."""
    almacen_carrefour = get_store_categories("carrefour", canonical_filter=["almacen"])
    assert len(almacen_carrefour) >= 1
    assert all(t.canonical == "almacen" for t in almacen_carrefour)

    bebidas_coto = get_store_categories("coto", canonical_filter=["bebidas"])
    assert len(bebidas_coto) == 1
    assert bebidas_coto[0].identifier == "catv00001256"
    assert bebidas_coto[0].canonical == "bebidas"
