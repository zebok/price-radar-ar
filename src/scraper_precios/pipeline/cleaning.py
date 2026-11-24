"""Pipeline de limpieza, enriquecimiento y calidad de datos con Polars (Silver Layer).

Aplica reglas técnicas determinísticas de calidad de datos, normaliza texto,
extrae unidades de medida (kg/L/u) con soporte de multipacks, clasifica
macro-categorías canónicas y emite métricas exactas de descartes por regla.
"""

from __future__ import annotations

import polars as pl

from ..filters import (
    DUMMY_EANS,
    MAX_PRICE_SANITY_ARS,
    MAX_VERIFIED_DISCOUNT_PCT,
    MIN_PRICE_SANITY_ARS,
    NON_RETAIL_REGEX,
)
from ..models import (
    ProductRecord,
    build_coto_product_url,
    build_vtex_product_url,
    normalize_image_url,
)

# Reglas determinísticas para clasificar macro-categorías unificadas entre las 6 cadenas
MACRO_CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("limpieza", [
        "limpieza", "detergente", "lavandina", "suavizante", "lavavajilla", "limpiador",
        "desinfectante", "insecticida", "rollo de cocina", "papel de cocina", "esponja",
        "trapo", "bolsa de residuo", "antigrasa", "quitamancha", "jabon liquido ropa",
        "jabon para ropa", "jabon en polvo",
    ]),
    ("perfumeria", [
        "perfumeria", "shampoo", "acondicionador", "desodorante", "antitranspirante",
        "pasta dental", "dentifrico", "cepillo dental", "papel higienico", "toallita",
        "protector diario", "afeitado", "crema corporal", "crema facial", "jabon de tocador",
        "jabon tocador", "panal", "pañal", "higiene", "colgate", "dove",
    ]),
    ("congelados", [
        "congelad", "hamburguesa", "milanesa", "papas noisette", "papas fritas congel",
        "helado", "nugget", "patitas", "rebozado", "pizza congel",
    ]),
    ("carnes", [
        "carniceria", "carne", "pollo", "pescado", "cerdo", "vacuna", "roast beef",
        "entrana", "entraña", "pata muslo", "bife", "asado", "picada", "lomo",
        "nalga", "cuadril", "merluza", "peceto", "vacio", "matambre",
    ]),
    ("verduleria", [
        "frutas y verduras", "verduleria", "fruta", "verdura", "papa negra", "papa blanca",
        "batata", "cebolla", "morron", "morrón", "tomate redondo", "tomate perita",
        "lechuga", "banana", "manzana", "naranja", "mandarina", "pomelo", "limon",
        "zanahoria", "zapallo", "palta",
    ]),
    ("lacteos", [
        "lacteo", "lácteo", "leche", "queso", "yogur", "manteca", "crema de leche",
        "fiambre", "jamon", "jamón", "salame", "ricotta", "margarina", "untable",
        "huevo", "finlandia", "casancrem", "ddl", "dulce de leche",
    ]),
    ("desayuno", [
        "desayuno", "yerba", "cafe", "café", "saquito", "te negro", "te verde",
        "infusion", "infusión", "cacao", "mermelada", "tostada", "galletita",
        "bizcochito", "budin", "budín", "magdalena", "cereal", "avena", "alfajor",
        "chocolate", "pan lactal", "pan artesano", "pan brioche", "panaderia",
    ]),
    ("bebidas", [
        "bebida", "gaseosa", "cola", "agua mineral", "agua sin gas", "agua con gas",
        "soda", "jugo", "isotonica", "isotónica", "energizante", "cerveza", "vino",
        "malbec", "cabernet", "espumante", "fernet", "aperitivo", "whisky", "gin",
        "vodka", "sidra", "vermouth",
    ]),
    ("almacen", [
        "almacen", "almacén", "aceite", "vinagre", "arroz", "fideo", "pasta", "harina",
        "azucar", "azúcar", "edulcorante", "sal fina", "sal gruesa", "lenteja",
        "garbanzo", "poroto", "polenta", "tomate triturado", "pure de tomate",
        "puré de tomate", "salsa", "mayonesa", "ketchup", "mostaza", "atun", "atún",
        "conserva", "enlatado", "aceituna", "oregano", "orégano", "provenzal",
        "condimento", "especia", "caldo", "sopa", "mani", "maní", "almendra",
        "nuez", "nueces", "avellana", "frutos secos", "snack", "golosina", "caramelo",
    ]),
]


def infer_macro_category(category: str | None, name_clean: str) -> str:
    """Asigna una macro-categoría canónica a partir de la categoría cruda y el nombre."""
    haystack = f"{(category or '').lower()} {name_clean}"
    for macro, keywords in MACRO_CATEGORY_RULES:
        for kw in keywords:
            if kw in haystack:
                return macro
    return "otros"


def records_to_dataframe(records: list[ProductRecord]) -> pl.DataFrame:
    """Convierte una lista de ProductRecord a un Polars DataFrame tipado."""
    if not records:
        return pl.DataFrame()

    rows = [
        {
            "store": r.store,
            "product_id": r.product_id,
            "sku_id": r.sku_id,
            "ean": r.ean,
            "name": r.name,
            "brand": r.brand,
            "sku_name": r.sku_name,
            "category": r.category,
            "url_slug": r.url_slug,
            "image_url": r.image_url,
            "price": float(r.price),
            "list_price": float(r.list_price) if r.list_price else None,
            "promo_label": r.promo_label,
            "currency": r.currency,
            "available": r.available,
            "available_quantity": r.available_quantity,
            "discount_pct": r.discount_pct,
            "product_url": r.product_url,
            "scraped_at": r.scraped_at,
        }
        for r in records
    ]

    schema = {
        "store": pl.Utf8,
        "product_id": pl.Utf8,
        "sku_id": pl.Utf8,
        "ean": pl.Utf8,
        "name": pl.Utf8,
        "brand": pl.Utf8,
        "sku_name": pl.Utf8,
        "category": pl.Utf8,
        "url_slug": pl.Utf8,
        "image_url": pl.Utf8,
        "price": pl.Float64,
        "list_price": pl.Float64,
        "promo_label": pl.Utf8,
        "currency": pl.Utf8,
        "available": pl.Boolean,
        "available_quantity": pl.Int64,
        "discount_pct": pl.Float64,
        "product_url": pl.Utf8,
        "scraped_at": pl.Datetime("us", time_zone="UTC"),
    }

    return pl.DataFrame(rows, schema=schema)


def clean_and_enrich_with_report(df: pl.DataFrame) -> tuple[pl.DataFrame, dict[str, int]]:
    """Transforma Bronze en Silver con reporte exacto de descartes de calidad.

    Pasos:
    1. Validación técnica de calidad (stock, banda de precio, nombre válido, no-retail)
    2. Deduplicación exacta de filas repetidas entre búsquedas/categorías
    3. Normalización de texto (`name_clean`, `brand_clean`, `ean_clean`, `macro_category`)
    4. Extracción de peso/volumen/packs y precio unitario estandarizado (`$/kg`, `$/L`, `$/u`)
    5. Verificación de descuento real (`verified_discount_pct` <= 75%)
    6. Normalización de URLs canónicas de Coto
    """
    report: dict[str, int] = {
        "input_rows": len(df),
        "dropped_out_of_stock": 0,
        "dropped_price_out_of_bounds": 0,
        "dropped_invalid_name": 0,
        "dropped_non_retail": 0,
        "dropped_duplicates": 0,
        "output_rows": 0,
    }

    if df.is_empty():
        return df, report

    # 1. Conteo y filtrado secuencial por regla de calidad técnica
    working = df

    if "available" in working.columns:
        before = len(working)
        working = working.filter(pl.col("available").fill_null(False))
        report["dropped_out_of_stock"] = before - len(working)

    if not working.is_empty():
        before = len(working)
        working = working.filter(
            pl.col("price").is_not_null()
            & (pl.col("price") >= MIN_PRICE_SANITY_ARS)
            & (pl.col("price") <= MAX_PRICE_SANITY_ARS)
        )
        report["dropped_price_out_of_bounds"] = before - len(working)

    if not working.is_empty():
        before = len(working)
        working = working.filter(
            pl.col("name").is_not_null() & (pl.col("name").str.strip_chars() != "")
        )
        report["dropped_invalid_name"] = before - len(working)

    if not working.is_empty():
        before = len(working)
        working = working.filter(
            ~pl.col("name").str.to_lowercase().str.contains(NON_RETAIL_REGEX.pattern)
        )
        report["dropped_non_retail"] = before - len(working)

    if working.is_empty():
        return working, report

    # Deduplicación exacta de registros repetidos en una misma corrida
    dedup_cols = [c for c in ("store", "product_id", "sku_id", "name") if c in working.columns]
    if dedup_cols:
        before = len(working)
        if "scraped_at" in working.columns:
            working = working.sort("scraped_at", descending=True)
        working = working.unique(subset=dedup_cols, keep="first", maintain_order=True)
        report["dropped_duplicates"] = before - len(working)

    # 2. Normalización de texto y EAN
    combined_name = pl.col("name").fill_null("") + " " + pl.col("sku_name").fill_null("")

    enriched = working.with_columns([
        pl.col("name")
        .str.to_lowercase()
        .str.replace_all(r"\s+", " ")
        .str.strip_chars()
        .alias("name_clean"),
        pl.col("brand")
        .fill_null("generico")
        .str.to_lowercase()
        .str.strip_chars()
        .alias("brand_clean"),
        pl.when(
            pl.col("ean").is_not_null()
            & pl.col("ean").str.strip_chars().str.contains(r"^\d{8,14}$")
            & (~pl.col("ean").str.strip_chars().is_in(list(DUMMY_EANS)))
        )
        .then(pl.col("ean").str.strip_chars())
        .otherwise(None)
        .alias("ean_clean"),
        combined_name.str.to_lowercase().alias("_combined_text"),
    ])

    # 3. Extracción de gramajes, volúmenes y multipacks
    kg_expr = (
        pl.col("_combined_text")
        .str.extract(r"(\d+(?:[.,]\d+)?)\s*(?:k(?:g|ilo|ilos)?)\b", 1)
        .str.replace(",", ".")
        .cast(pl.Float64, strict=False)
    )
    gr_expr = (
        pl.col("_combined_text")
        .str.extract(r"(\d+(?:[.,]\d+)?)\s*(?:gr?|gramos?)\b", 1)
        .str.replace(",", ".")
        .cast(pl.Float64, strict=False)
        / 1000.0
    )
    lt_expr = (
        pl.col("_combined_text")
        .str.extract(r"(\d+(?:[.,]\d+)?)\s*(?:l(?:t|ts|itros?)?)\b", 1)
        .str.replace(",", ".")
        .cast(pl.Float64, strict=False)
    )
    ml_expr = (
        pl.col("_combined_text")
        .str.extract(r"(\d+(?:[.,]\d+)?)\s*(?:ml|cc|cm3)\b", 1)
        .str.replace(",", ".")
        .cast(pl.Float64, strict=False)
        / 1000.0
    )

    # Multipacks explícitos donde el tamaño indicado es por unidad (ej: '6x473ml', 'Pack x 6 1 L')
    explicit_nx_size_expr = (
        pl.col("_combined_text")
        .str.extract(
            r"\b(\d{1,2})\s*x\s*\d+(?:[.,]\d+)?\s*(?:k(?:g|ilo|ilos)?|gr?|gramos?|l(?:t|ts|itros?)?|ml|cc|cm3)\b",
            1,
        )
        .cast(pl.Int64, strict=False)
    )
    explicit_pack_expr = (
        pl.col("_combined_text")
        .str.extract(r"\bpack\s*x?\s*(\d{1,2})\b", 1)
        .cast(pl.Int64, strict=False)
    )
    generic_x_units_expr = (
        pl.col("_combined_text")
        .str.extract(r"(?:pack\s*x?\s*|x\s*)(\d{1,2})\s*(?:u|un|unid|unidades|rollos|latas|botellas)?\b", 1)
        .cast(pl.Int64, strict=False)
    )

    enriched = enriched.with_columns([
        pl.coalesce([kg_expr, gr_expr]).alias("_unit_weight_kg"),
        pl.coalesce([lt_expr, ml_expr]).alias("_unit_volume_l"),
        pl.coalesce([explicit_nx_size_expr, explicit_pack_expr])
        .alias("_multipack_factor"),
        pl.coalesce([explicit_nx_size_expr, explicit_pack_expr, generic_x_units_expr])
        .fill_null(1)
        .alias("pack_units"),
    ])

    # Sanitizar factores (evitar 0 o multiplicadores irreales > 60)
    enriched = enriched.with_columns([
        pl.when((pl.col("pack_units") >= 1) & (pl.col("pack_units") <= 60))
        .then(pl.col("pack_units"))
        .otherwise(1)
        .alias("pack_units"),
        pl.when((pl.col("_multipack_factor") >= 2) & (pl.col("_multipack_factor") <= 60))
        .then(pl.col("_multipack_factor"))
        .otherwise(1)
        .alias("_safe_multipack"),
    ])

    # Peso y volumen efectivos (multiplicando por factor solo en multipacks explícitos)
    enriched = enriched.with_columns([
        (pl.col("_unit_weight_kg") * pl.col("_safe_multipack")).round(4).alias("weight_kg"),
        (pl.col("_unit_volume_l") * pl.col("_safe_multipack")).round(4).alias("volume_liters"),
    ])

    # 4. Precio unitario estandarizado ($/kg, $/L, $/u, $/item)
    enriched = enriched.with_columns([
        pl.when(pl.col("weight_kg").is_not_null() & (pl.col("weight_kg") > 0))
        .then(pl.col("price") / pl.col("weight_kg"))
        .when(pl.col("volume_liters").is_not_null() & (pl.col("volume_liters") > 0))
        .then(pl.col("price") / pl.col("volume_liters"))
        .when(pl.col("pack_units") > 1)
        .then(pl.col("price") / pl.col("pack_units"))
        .otherwise(pl.col("price"))
        .round(2)
        .alias("unit_price_std"),
        pl.when(pl.col("weight_kg").is_not_null() & (pl.col("weight_kg") > 0))
        .then(pl.lit("$/kg"))
        .when(pl.col("volume_liters").is_not_null() & (pl.col("volume_liters") > 0))
        .then(pl.lit("$/L"))
        .when(pl.col("pack_units") > 1)
        .then(pl.lit("$/u"))
        .otherwise(pl.lit("$/item"))
        .alias("unit_measure"),
    ])

    # 5. Descuento real verificado (<= 75%) y partición dt
    discount_calc = (
        (pl.col("list_price") - pl.col("price")) / pl.col("list_price") * 100.0
    ).round(2)

    enriched = enriched.with_columns([
        pl.when(
            pl.col("list_price").is_not_null()
            & (pl.col("list_price") > pl.col("price"))
            & (pl.col("list_price") > 0)
            & (discount_calc <= MAX_VERIFIED_DISCOUNT_PCT)
        )
        .then(discount_calc)
        .otherwise(None)
        .alias("verified_discount_pct"),
        pl.col("scraped_at").dt.date().alias("dt"),
    ])

    # 6. Macro-categoría unificada entre supermercados
    cats = enriched["category"].to_list() if "category" in enriched.columns else [None] * len(enriched)
    names_clean = enriched["name_clean"].to_list()
    macro_cats = [infer_macro_category(c, n) for c, n in zip(cats, names_clean, strict=True)]
    enriched = enriched.with_columns(pl.Series("macro_category", macro_cats))

    # 7. Normalización y validación de URLs de producto e imágenes para todas las cadenas
    if "store" in enriched.columns:
        names = enriched["name"].to_list()
        slugs = (
            enriched["url_slug"].to_list()
            if "url_slug" in enriched.columns
            else [None] * len(enriched)
        )
        prod_ids = (
            enriched["product_id"].to_list()
            if "product_id" in enriched.columns
            else [None] * len(enriched)
        )
        urls = (
            enriched["product_url"].to_list()
            if "product_url" in enriched.columns
            else [None] * len(enriched)
        )
        stores = enriched["store"].to_list()

        new_urls: list[str | None] = []
        for n, s, p, u, st in zip(names, slugs, prod_ids, urls, stores, strict=True):
            if st == "coto":
                new_urls.append(build_coto_product_url(n, s, p))
            elif u and isinstance(u, str) and u.startswith("https://") and "/p/p" not in u and " " not in u:
                new_urls.append(u)
            else:
                new_urls.append(build_vtex_product_url(st, s, n) or u)

        enriched = enriched.with_columns(pl.Series("product_url", new_urls))

    if "image_url" in enriched.columns:
        clean_imgs = [normalize_image_url(img) for img in enriched["image_url"].to_list()]
        enriched = enriched.with_columns(pl.Series("image_url", clean_imgs, dtype=pl.Utf8))

    cleaned = enriched.drop([
        "_combined_text",
        "_unit_weight_kg",
        "_unit_volume_l",
        "_multipack_factor",
        "_safe_multipack",
    ])
    report["output_rows"] = len(cleaned)
    return cleaned, report


def clean_and_enrich_products(df: pl.DataFrame) -> pl.DataFrame:
    """Aplica la transformación Bronze → Silver y retorna el DataFrame enriquecido."""
    cleaned, _ = clean_and_enrich_with_report(df)
    return cleaned
