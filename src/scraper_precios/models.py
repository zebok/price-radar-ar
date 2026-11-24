"""Modelos Pydantic para los datos extraídos — Schema estricto y construcción segura de URLs."""

from __future__ import annotations

import re
import unicodedata
import urllib.parse
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, computed_field


def build_store_search_url(store: str, query: str | None) -> str | None:
    """Construye una URL de búsqueda válida de respaldo en el sitio oficial del supermercado."""
    from .config import STORES

    clean_q = (query or "").strip()
    if not clean_q:
        return None
    q_enc = urllib.parse.quote(clean_q)

    if store in STORES:
        return f"{STORES[store].origin}/{q_enc}?_q={q_enc}&map=ft"
    if store == "coto":
        return f"https://www.coto.com.ar/browse?_dyncharset=utf-8&Ntt={q_enc}"
    return None


def build_vtex_product_url(
    store: str,
    url_slug: str | None,
    name: str | None = None,
) -> str | None:
    """Construye una URL canónica de producto VTEX evitando rutas malformadas o `/p/p`."""
    from .config import STORES

    if store not in STORES:
        return None

    origin = STORES[store].origin
    if url_slug and url_slug.strip():
        raw = url_slug.strip()
        if raw.startswith("http://") or raw.startswith("https://"):
            parsed = urllib.parse.urlparse(raw)
            path = parsed.path.strip("/")
        else:
            path = raw.split("?", 1)[0].strip("/")

        if path.endswith("/p"):
            path = path[:-2].strip("/")

        # Validar que el slug no contenga espacios ni caracteres inválidos
        if path and not re.search(r"\s", path):
            return f"{origin}/{path}/p"

    return build_store_search_url(store, name)


def build_coto_product_url(
    name: str | None,
    url_slug: str | None,
    product_id: str | None = None,
) -> str:
    """Construye la URL canónica del producto en Coto (https://www.coto.com.ar/productos/{slug}-/_/R-...)."""
    slug_part = ""
    if url_slug:
        clean_slug = url_slug.strip("/")
        r_match = re.search(r"(R-\d+(?:-\d+)*)", clean_slug)
        if r_match:
            slug_part = f"_/{r_match.group(1)}"
        elif clean_slug.startswith("_/"):
            slug_part = clean_slug
        elif clean_slug:
            slug_part = f"_/{clean_slug}"
    elif product_id:
        digits = re.sub(r"\D", "", product_id)
        if digits:
            clean_id = digits.zfill(8)
            slug_part = f"_/R-{clean_id}-{clean_id}-200"

    name_slug = ""
    if name and name.strip():
        text = unicodedata.normalize("NFKD", name)
        text = "".join(c for c in text if not unicodedata.combining(c))
        text = text.lower()
        text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
        if text:
            name_slug = f"{text}-"

    if name_slug and slug_part:
        return f"https://www.coto.com.ar/productos/{name_slug}/{slug_part}"
    if slug_part:
        return f"https://www.coto.com.ar/productos/{slug_part}"
    return build_store_search_url("coto", name) or "https://www.coto.com.ar"


def normalize_image_url(url: str | None) -> str | None:
    """Normaliza URLs de imágenes asegurando esquema HTTPS y descartando cadenas inválidas."""
    if not url or not isinstance(url, str):
        return None
    cleaned = url.strip()
    if not cleaned:
        return None
    if cleaned.startswith("//"):
        cleaned = f"https:{cleaned}"
    elif cleaned.startswith("http://"):
        cleaned = f"https://{cleaned[7:]}"
    if not cleaned.startswith("https://") or " " in cleaned:
        return None
    return cleaned


class ProductRecord(BaseModel):
    """Registro normalizado de un producto extraído de cualquier supermercado.

    Schema canónico usado en todo el pipeline:
    Extracción → Validación → Polars DataFrame → Parquet (Bronze/Silver/Gold).
    """

    store: str = Field(..., description="Clave de la tienda (ej: 'carrefour', 'jumbo', 'coto')")
    product_id: str = Field(..., description="ID del producto en la plataforma origen")
    sku_id: str = Field(..., description="ID del SKU específico")
    ean: str | None = Field(None, description="Código de barras EAN-13 (si disponible)")

    name: str = Field(..., description="Nombre completo del producto")
    brand: str | None = Field(None, description="Marca del producto")
    sku_name: str | None = Field(None, description="Variante del SKU (ej: '1 Kg', '500 ml')")
    category: str | None = Field(None, description="Categoría del producto")
    url_slug: str | None = Field(None, description="Slug o path canónico para construir la URL")
    image_url: str | None = Field(None, description="URL HTTPS de la imagen principal")

    price: Decimal = Field(..., ge=0, description="Precio actual de venta por unidad (spotPrice)")
    list_price: Decimal | None = Field(None, ge=0, description="Precio de lista regular (sin descuento)")
    promo_label: str | None = Field(
        None,
        description="Etiqueta de promoción condicional multi-unidad (ej: '2do al 70%', '3x2', '2do al 50%')",
    )
    currency: str = Field(default="ARS", description="Código de moneda ISO 4217")

    available: bool = Field(default=True, description="Si el producto está en stock")
    available_quantity: int | None = Field(None, ge=0, description="Cantidad disponible")

    scraped_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp UTC de la extracción",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def discount_pct(self) -> float | None:
        if self.list_price and self.list_price > 0 and self.list_price > self.price:
            return round(
                float((self.list_price - self.price) / self.list_price * 100), 2
            )
        return None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def product_url(self) -> str | None:
        """URL canónica verificada del producto en la tienda (con fallback a búsqueda)."""
        if self.store == "coto":
            return build_coto_product_url(self.name, self.url_slug, self.product_id)
        return build_vtex_product_url(self.store, self.url_slug, self.name)
