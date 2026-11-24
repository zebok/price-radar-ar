"""Configuración central del scraper — Stores VTEX, rate limiting, resiliencia y rutas."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings


@dataclass(frozen=True, slots=True)
class VTEXStore:
    """Definición de una tienda VTEX para scraping."""

    name: str
    account_name: str  # {account}.vtexcommercestable.com.br
    base_url: str  # URL pública del sitio (para Referer/Origin)
    locale: str = "es-AR"

    @property
    def origin(self) -> str:
        if self.base_url.startswith("http://") or self.base_url.startswith("https://"):
            return self.base_url.rstrip("/")
        return f"https://{self.base_url}"

    @property
    def api_search_url(self) -> str:
        """Endpoint de VTEX Intelligent Search (legacy IO path, compatible con todas)."""
        return f"{self.origin}/api/io/_v/api/intelligent-search/product_search/"


# ──────────────────────────────────────────────────────────────
#  Registro de tiendas VTEX en Argentina
#  Para agregar una nueva: solo agregar una entrada acá.
# ──────────────────────────────────────────────────────────────
STORES: dict[str, VTEXStore] = {
    "carrefour": VTEXStore(
        name="Carrefour",
        account_name="carrefourar",
        base_url="www.carrefour.com.ar",
    ),
    "jumbo": VTEXStore(
        name="Jumbo",
        account_name="jumboargentina",
        base_url="www.jumbo.com.ar",
    ),
    "disco": VTEXStore(
        name="Disco",
        account_name="discoargentina",
        base_url="www.disco.com.ar",
    ),
    "vea": VTEXStore(
        name="Vea",
        account_name="veaargentina",
        base_url="www.vea.com.ar",
    ),
    "dia": VTEXStore(
        name="Dia",
        account_name="supermercadosdia",
        base_url="diaonline.supermercadosdia.com.ar",
    ),
}


def parse_store_selection(
    raw_stores: list[str] | str,
    available: list[str],
) -> tuple[list[str], list[str]]:
    """Normaliza argumentos de tiendas aceptando espacios, comas o 'all'.

    Ejemplos soportados:
    - ["carrefour", "coto"]
    - ["carrefour,coto,dia"]
    - "carrefour, jumbo"
    - ["all"]
    """
    tokens: list[str] = []
    items = [raw_stores] if isinstance(raw_stores, str) else list(raw_stores)
    for item in items:
        for part in str(item).split(","):
            cleaned = part.strip().lower()
            if cleaned:
                tokens.append(cleaned)

    if "all" in tokens:
        return list(available), []

    valid: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in available:
            if token not in seen:
                valid.append(token)
                seen.add(token)
        else:
            invalid.append(token)
    return valid, invalid


class Settings(BaseSettings):
    """Configuración global del scraper, leída desde variables de entorno."""

    # Puerto dinámico — se asigna automáticamente si no se especifica
    port: int = Field(default=0, validation_alias=AliasChoices("SCRAPER_PORT", "PORT"))

    # Rate limiting y resiliencia por tienda
    max_concurrent_requests: int = Field(
        default=4,
        validation_alias=AliasChoices("SCRAPER_MAX_CONCURRENT_REQUESTS", "MAX_CONCURRENT_REQUESTS"),
    )
    request_delay_seconds: float = Field(
        default=0.4,
        validation_alias=AliasChoices("SCRAPER_REQUEST_DELAY_SECONDS", "REQUEST_DELAY_SECONDS"),
    )
    max_retries: int = Field(
        default=3,
        validation_alias=AliasChoices("SCRAPER_MAX_RETRIES", "MAX_RETRIES"),
    )
    circuit_breaker_threshold: int = Field(
        default=3,
        validation_alias=AliasChoices("SCRAPER_CIRCUIT_BREAKER_THRESHOLD", "CIRCUIT_BREAKER_THRESHOLD"),
    )
    carry_forward_max_days: int = Field(
        default=7,
        validation_alias=AliasChoices("SCRAPER_CARRY_FORWARD_MAX_DAYS", "CARRY_FORWARD_MAX_DAYS"),
    )

    # Rutas locales
    data_dir: Path = Field(
        default=Path("data/scraper-precios"),
        validation_alias=AliasChoices("SCRAPER_DATA_DIR", "DATA_DIR"),
    )
    demo_data_dir: Path = Field(
        default=Path("data/demo"),
        validation_alias=AliasChoices("SCRAPER_DEMO_DATA_DIR", "DEMO_DATA_DIR"),
    )
    web_dir: Path = Field(
        default=Path("web"),
        validation_alias=AliasChoices("SCRAPER_WEB_DIR", "WEB_DIR"),
    )
    output_format: str = Field(
        default="parquet",
        validation_alias=AliasChoices("SCRAPER_OUTPUT_FORMAT", "OUTPUT_FORMAT"),
    )

    # Stores habilitadas
    enabled_stores: list[str] | str = Field(
        default=["carrefour", "coto", "dia", "jumbo", "disco", "vea"],
        validation_alias=AliasChoices("SCRAPER_ENABLED_STORES", "ENABLED_STORES"),
    )

    # Canasta por defecto: 'core' o 'extended'
    basket_type: str = Field(
        default="extended",
        validation_alias=AliasChoices("SCRAPER_BASKET_TYPE", "BASKET_TYPE"),
    )

    # Seguridad puramente opcional (acceso abierto por defecto)
    api_key: str = Field(default="", validation_alias=AliasChoices("SCRAPER_API_KEY", "API_KEY"))
    require_auth: bool = Field(
        default=False,
        validation_alias=AliasChoices("SCRAPER_REQUIRE_AUTH", "REQUIRE_AUTH"),
    )

    # Cloud Storage opcional (GCP)
    gcs_bucket: str = Field(
        default="",
        validation_alias=AliasChoices("SCRAPER_GCS_BUCKET", "GCS_BUCKET_NAME", "GCS_BUCKET"),
    )

    @field_validator("enabled_stores", mode="after")
    @classmethod
    def _normalize_stores(cls, v: list[str] | str) -> list[str]:
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                try:
                    return json.loads(v)
                except Exception:
                    pass
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    model_config = {
        "env_prefix": "SCRAPER_",
        "env_file": ".env",
        "extra": "ignore",
    }
