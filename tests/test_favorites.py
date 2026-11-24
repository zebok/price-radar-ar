"""Pruebas unitarias para la gestión de productos favoritos / canasta habitual."""

from pathlib import Path

from scraper_precios.favorites import (
    FavoriteItem,
    add_or_update_favorite,
    load_favorites,
    remove_favorite,
    toggle_favorite,
)


def test_favorites_lifecycle(tmp_path: Path):
    """Valida carga inicial, alta, toggle de favorito y eliminación."""
    test_file = tmp_path / "favorites.json"

    # 1. Carga inicial (debe inicializar con los productos de la canasta core)
    items = load_favorites(test_file)
    assert len(items) > 0
    assert any(i.id == "yerba" for i in items)

    # 2. Agregar nuevo favorito
    custom = FavoriteItem(
        id="queso_brie",
        name="Queso Brie",
        query="queso brie",
        category="lacteos",
        preferred_brands=["la serenisima"],
        is_favorite=True,
    )
    add_or_update_favorite(custom, test_file)

    loaded = load_favorites(test_file)
    assert any(i.id == "queso_brie" for i in loaded)

    # 3. Toggle de favorito
    new_state = toggle_favorite("queso_brie", test_file)
    assert new_state is False

    # 4. Eliminar
    deleted = remove_favorite("queso_brie", test_file)
    assert deleted is True
    assert not any(i.id == "queso_brie" for i in load_favorites(test_file))
