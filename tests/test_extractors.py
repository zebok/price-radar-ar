"""Pruebas unitarias para los extractores especializados: Coto, VTEX, Registry y Circuit Breaker."""

from decimal import Decimal

import pytest

from scraper_precios.extractors import (
    CircuitOpenError,
    CotoExtractor,
    VTEXExtractor,
    get_extractor,
    list_available_stores,
)


def test_registry_stores():
    """Valida que todas las tiendas esperadas estén registradas."""
    stores = list_available_stores()
    expected = ["carrefour", "jumbo", "disco", "vea", "dia", "coto"]
    for s in expected:
        assert s in stores

    assert isinstance(get_extractor("coto"), CotoExtractor)
    assert isinstance(get_extractor("carrefour"), VTEXExtractor)
    assert isinstance(get_extractor("dia"), VTEXExtractor)

    with pytest.raises(ValueError, match="no soportada"):
        get_extractor("supermercado_fantasma")


def test_coto_parser_and_category_extraction():
    """Valida el parseo de Constructor.io incluyendo extracción y fallback de categoría."""
    extractor = CotoExtractor()
    mock_item = {
        "value": "Yerba Mate Mañanita Paq 1 Kg",
        "data": {
            "id": "prod00499475",
            "sku_id": "sku00499475",
            "product_main_ean": "7790387015317",
            "product_brand": "MAÑANITA",
            "sku_display_name": "1 Kg",
            "product_list_price": 5747,
            "groups": [
                {"display_name": "Almacén"},
                {"display_name": "Infusiones"},
            ],
            "discounts": [
                {
                    "discountPrice": "$4310.25",
                    "discountText": "25%Dto",
                }
            ],
            "product_large_image_url": "https://static.cotodigital3.com.ar/img.jpg",
            "url": "_/R-00499475-200",
            "store_availability": True,
        },
    }

    record = extractor._parse_item(mock_item)
    assert record is not None
    assert record.store == "coto"
    assert record.category == "Almacén > Infusiones"
    assert record.ean == "7790387015317"
    assert record.price == Decimal("4310.25")
    assert record.list_price == Decimal("5747")
    assert record.discount_pct is not None and record.discount_pct > 20.0

    # Sin groups en payload -> usa default_category
    mock_item_no_group = {
        "value": "Detergente Magistral 750ml",
        "data": {
            "id": "prod00112233",
            "product_list_price": 3200,
            "store_availability": True,
        },
    }
    rec_fallback = extractor._parse_item(mock_item_no_group, default_category="Limpieza")
    assert rec_fallback is not None
    assert rec_fallback.category == "Limpieza"


def test_coto_canonical_url():
    """Valida la generación de URLs canónicas de Coto."""
    from scraper_precios.models import build_coto_product_url

    expected = "https://www.coto.com.ar/productos/papas-noisette-mccain-600g-/_/R-00579539-00579539-200"
    assert build_coto_product_url("Papas Noisette MCCAIN 600g", "_/R-00579539-00579539-200") == expected
    assert build_coto_product_url("Papas Noisette MCCAIN 600g", "producto/_/R-00579539-00579539-200") == expected
    assert build_coto_product_url("Papas Noisette MCCAIN 600g", None, product_id="prod00579539") == expected


def test_vtex_url_and_image_normalization():
    """Valida URLs VTEX sin duplicar `/p`, fallback de búsqueda e imágenes HTTPS."""
    from scraper_precios.models import build_vtex_product_url, normalize_image_url

    assert (
        build_vtex_product_url("carrefour", "/yerba-mate-playadito-1-kg/p")
        == "https://www.carrefour.com.ar/yerba-mate-playadito-1-kg/p"
    )
    assert (
        build_vtex_product_url("dia", "https://diaonline.supermercadosdia.com.ar/yerba-269577/p")
        == "https://diaonline.supermercadosdia.com.ar/yerba-269577/p"
    )
    fallback = build_vtex_product_url("jumbo", None, name="Yerba Playadito 1kg")
    assert fallback is not None and fallback.startswith("https://www.jumbo.com.ar/") and "map=ft" in fallback

    assert normalize_image_url("//cdn.example.com/a.jpg") == "https://cdn.example.com/a.jpg"
    assert normalize_image_url("http://cdn.example.com/a.jpg") == "https://cdn.example.com/a.jpg"
    assert normalize_image_url("   ") is None


async def test_circuit_breaker_opens_after_consecutive_failures():
    """Valida que el circuit breaker corte rápido tras superar el umbral de fallos."""
    extractor = CotoExtractor(circuit_breaker_threshold=2)
    extractor._register_failure("HTTP 403")
    assert not extractor.metrics.circuit_open
    extractor._register_failure("HTTP 403")
    assert extractor.metrics.circuit_open
    assert extractor.metrics.status == "circuit_open"

    with pytest.raises(CircuitOpenError):
        await extractor.safe_get("https://example.com")


def test_coto_conditional_multiunit_promo_preserves_unit_price():
    """Valida que promos multi-unidad ('Llevando 2', '50% 2da') no distorsionen el precio unitario."""
    extractor = CotoExtractor()
    mock_item = {
        "value": "Gaseosa Coca-Cola Sabor Original 2,25 Lt",
        "data": {
            "id": "prod00123456",
            "sku_id": "sku00123456",
            "product_main_ean": "7790895000997",
            "product_brand": "COCA-COLA",
            "product_list_price": 6100,
            "discounts": [
                {
                    "takingText": "Llevando 2",
                    "discountText": "50% 2da",
                    "discountPrice": "$4575.00",
                    "discountImage": None,
                }
            ],
            "store_availability": True,
        },
    }
    rec = extractor._parse_item(mock_item)
    assert rec is not None
    assert rec.price == Decimal("6100")
    assert rec.list_price is None
    assert rec.discount_pct is None
    assert rec.promo_label == "2do al 50%"

    # Comunidad Coto (+5%) no debe sobreescribir el precio público
    mock_loyalty_only = {
        "value": "Leche Entera 1 L",
        "data": {
            "id": "prod00999888",
            "product_list_price": 2000,
            "discounts": [
                {
                    "discountText": "+5%",
                    "discountImage": "/content/images/cdigi/ofertas/comunidad.png",
                    "discountPrice": "$1900.00",
                }
            ],
            "store_availability": True,
        },
    }
    rec_loy = extractor._parse_item(mock_loyalty_only)
    assert rec_loy is not None
    assert rec_loy.price == Decimal("2000")
    assert rec_loy.list_price is None
    assert rec_loy.promo_label is None


def test_cencosud_list_price_and_enrich_promotions():
    """Valida limpieza de ListPrice sin IVA (Ley 27.743) y aplicación de promos de Cencosud."""
    from scraper_precios.config import STORES
    from scraper_precios.extractors.vtex import (
        apply_cencosud_promotions,
        extract_public_teaser_promo,
    )

    vea = VTEXExtractor(STORES["vea"], "vea")
    raw_vea_item = {
        "productId": "245602",
        "productName": "Aceite De Girasol Cocinero 1.5 L",
        "brand": "COCINERO",
        "link": "https://www.vea.com.ar/aceite-de-girasol-cocinero-1-5-l/p",
        "categories": ["/Almacén/Aceites/"],
        "items": [
            {
                "itemId": "244750",
                "ean": "7790272001050",
                "name": "1.5 L",
                "images": [{"imageUrl": "https://jumboargentina.vtexassets.com/img.jpg"}],
                "sellers": [
                    {
                        "commertialOffer": {
                            "Price": 6890,
                            # Ley 27.743 sin IVA en centavos: 6890 / 1.21 * 100 = 569421
                            "ListPrice": 569421,
                            "PriceWithoutDiscount": 6890,
                            "AvailableQuantity": 10,
                            "teasers": [],
                        }
                    }
                ],
            }
        ],
    }

    parsed = vea._parse_product(raw_vea_item)
    assert parsed is not None
    assert parsed.price == Decimal("6890")
    assert parsed.list_price is None  # No debe guardar el precio sin IVA como list_price

    # 1. Descuento directo percentual (40%)
    enriched_pct = apply_cencosud_promotions(
        parsed, [{"categoryType": "percentual", "code": "40%", "value": 0}]
    )
    assert enriched_pct.price == Decimal("4134.00")
    assert enriched_pct.list_price == Decimal("6890")
    assert enriched_pct.discount_pct == 40.0
    assert enriched_pct.promo_label is None

    # 2. Promoción condicional multi-unidad (2do al 50%) no altera el precio de 1 unidad
    enriched_multi = apply_cencosud_promotions(
        parsed, [{"categoryType": "segundo_al", "code": "2do al 50%", "value": 0}]
    )
    assert enriched_multi.price == Decimal("6890")
    assert enriched_multi.list_price is None
    assert enriched_multi.promo_label == "2do al 50%"

    # 3. Teasers VTEX: ignorar tarjetas/bancos, capturar promos públicas multi-unidad
    assert extract_public_teaser_promo([{"name": "Tarjeta Carrefour 15%"}]) is None
    assert extract_public_teaser_promo([{"name": "Promo 2do al 70%"}]) == "2do al 70%"
