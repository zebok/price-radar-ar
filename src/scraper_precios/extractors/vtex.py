"""Extractor resiliente para tiendas VTEX Intelligent Search en Argentina.

Implementa BaseExtractor con reintentos exponenciales (tenacity), paginación
exhaustiva, circuit breaker, corrección de anomalías de Cencosud y soporte de categorías.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ..config import VTEXStore
from ..filters import MAX_VERIFIED_DISCOUNT_PCT, classify_rejection_reason
from ..models import ProductRecord, normalize_image_url
from .base import BaseExtractor, CircuitOpenError

# Cencosud Argentina (Vea, Jumbo, Disco) almacena en ListPrice el precio sin impuestos
# nacionales (Ley 27.743) en centavos y resuelve sus descuentos vigentes mediante el
# servicio GraphQL `enrichPromotions` de `searchcucardas`.
CENCOSUD_PROMO_CONFIG: dict[str, tuple[str, str]] = {
    "vea": ("veaargentina.store-theme@7.x", "jumboargentinaj5202martinez"),
    "jumbo": ("jumboargentinaio.store-theme@8.x", "jumboargentinaj5202martinez"),
    "disco": ("discoargentina.store-theme@11.x", "jumboargentinaj5202martinez"),
}
CENCOSUD_PROMO_BATCH_SIZE = 25

_CARD_OR_LOYALTY_RE = re.compile(
    r"\b(?:tarjeta|banco|modo|dni|bna|galicia|santander|bbva|macro|ciudad|nacion|"
    r"cencopay|cuota|cuotas|comunidad|socio|socios|club|prime|jumbo\+|mas)\b",
    re.IGNORECASE,
)
_MULTIUNIT_PROMO_RE = re.compile(
    r"(?:2(?:do|da)\s+al\s+\d{1,2}\s*%|\d{1,2}\s*%\s*(?:en\s+la\s+)?2(?:do|da)|\b[2-9]\s*x\s*[1-8]\b)",
    re.IGNORECASE,
)
_PCT_CODE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_SAFE_SKU_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def extract_public_teaser_promo(teasers: Any) -> str | None:
    """Extrae una etiqueta de promo multi-unidad pública (ej. '2do al 70%', '3x2') desde teasers VTEX."""
    if not isinstance(teasers, list):
        return None
    for teaser in teasers:
        if not isinstance(teaser, dict):
            continue
        name = str(teaser.get("name") or "").strip()
        if not name or _CARD_OR_LOYALTY_RE.search(name):
            continue
        m = _MULTIUNIT_PROMO_RE.search(name)
        if m:
            return re.sub(r"\s+", " ", m.group(0)).strip()
    return None


def apply_cencosud_promotions(
    record: ProductRecord,
    promotions: list[dict[str, Any]],
) -> ProductRecord:
    """Aplica promociones reales de Cencosud (`enrichPromotions`) sobre un ProductRecord.

    Reglas estrictas de calidad de datos:
    - `percentual` y `fixed_price` son descuentos directos por 1 unidad: se actualiza `price`
      al precio promocional y se conserva el precio regular original en `list_price`.
    - `segundo_al` (ej: '2do al 70%') y `nxm` (ej: '3x2', '6x5') son condicionales por
      cantidad: NO distorsionan el precio de 1 unidad y se registran en `promo_label`.
    """
    if not promotions or record.price <= 0:
        return record

    # Si ya trae un descuento directo explícito (list_price > price), no aplicar doble descuento
    if record.list_price is not None and record.list_price > record.price:
        return record

    base_price = record.price
    max_disc = Decimal(str(MAX_VERIFIED_DISCOUNT_PCT))
    direct_candidates: list[Decimal] = []
    conditional_labels: list[str] = []

    for promo in promotions:
        if not isinstance(promo, dict):
            continue
        cat_type = str(promo.get("categoryType") or "").strip().lower()
        code = str(promo.get("code") or "").strip()
        raw_val = promo.get("value")

        if cat_type == "percentual":
            m = _PCT_CODE_RE.search(code)
            if m:
                try:
                    pct = Decimal(m.group(1).replace(",", "."))
                except InvalidOperation:
                    continue
                if Decimal("0") < pct <= max_disc:
                    discounted = (
                        base_price * (Decimal("100") - pct) / Decimal("100")
                    ).quantize(Decimal("0.01"))
                    if Decimal("0") < discounted < base_price:
                        direct_candidates.append(discounted)
        elif cat_type == "fixed_price" and raw_val is not None:
            try:
                fixed = Decimal(str(raw_val)).quantize(Decimal("0.01"))
            except InvalidOperation:
                continue
            if Decimal("0") < fixed < base_price:
                pct = ((base_price - fixed) / base_price) * Decimal("100")
                if pct <= max_disc:
                    direct_candidates.append(fixed)
        elif cat_type in ("segundo_al", "nxm") and code:
            clean_code = re.sub(r"\s+", " ", code).strip()
            if clean_code and clean_code not in conditional_labels:
                conditional_labels.append(clean_code)

    if direct_candidates:
        best_direct = min(direct_candidates)
        return record.model_copy(
            update={
                "price": best_direct,
                "list_price": base_price,
                "promo_label": None,
            }
        )

    if conditional_labels:
        return record.model_copy(update={"promo_label": conditional_labels[0]})

    return record


def is_retryable_error(exc: BaseException) -> bool:
    """Determina si un error HTTP es transitorio y califica para reintento."""
    if isinstance(exc, CircuitOpenError):
        return False
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    return False


class VTEXExtractor(BaseExtractor):
    """Extractor para supermercados sobre plataforma VTEX (Carrefour, Jumbo, Disco, Vea, Dia)."""

    RESULTS_PER_PAGE = 24

    def __init__(
        self,
        store: VTEXStore,
        store_key: str,
        *,
        max_concurrent: int = 3,
        request_delay_seconds: float = 0.4,
        timeout_seconds: float = 15.0,
        circuit_breaker_threshold: int = 3,
    ) -> None:
        super().__init__(
            store_key=store_key,
            display_name=store.name,
            origin_url=store.origin,
            max_concurrent=max_concurrent,
            request_delay_seconds=request_delay_seconds,
            timeout_seconds=timeout_seconds,
            circuit_breaker_threshold=circuit_breaker_threshold,
        )
        self.vtex_store = store
        self._cencosud_promo_cache: dict[str, list[dict[str, Any]]] = {}
        self._cencosud_promo_disabled: bool = False

    @retry(
        retry=retry_if_exception(is_retryable_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1.0, max=8.0, jitter=0.5),
        reraise=True,
    )
    async def _fetch_page(
        self,
        endpoint: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Ejecuta una petición con retry exponencial automático."""
        resp = await self.safe_get(endpoint, params=params)
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:
            return json.loads(resp.content.decode("utf-8", errors="replace"))

    async def search_page(
        self,
        query: str,
        *,
        page: int = 1,
        count: int = RESULTS_PER_PAGE,
    ) -> tuple[list[ProductRecord], int]:
        """Obtiene una página individual de resultados para una query."""
        if self.metrics.circuit_open:
            return [], 0

        params = {
            "query": query,
            "page": page,
            "count": count,
            "sort": "score:desc",
            "locale": self.vtex_store.locale,
        }

        try:
            data = await self._fetch_page(self.vtex_store.api_search_url, params)
        except CircuitOpenError:
            return [], 0
        except Exception as e:
            logger.warning(
                "[{store}] Falló la búsqueda '{query}' (página {page}): {err}",
                store=self.display_name,
                query=query,
                page=page,
                err=e,
            )
            return [], 0

        raw_products = data.get("products", [])
        total_filtered = data.get("recordsFiltered", 0)

        records: list[ProductRecord] = []
        for raw in raw_products:
            parsed = self._parse_product(raw)
            if parsed:
                records.append(parsed)

        self.metrics.records_extracted += len(records)
        return records, total_filtered

    async def extract_query(
        self,
        query: str,
        *,
        max_pages: int = 1,
    ) -> list[ProductRecord]:
        """Extrae productos para una búsqueda recorriendo múltiples páginas.

        Si `max_pages <= 0`, extrae todas las páginas disponibles hasta `MAX_EXHAUSTIVE_PAGES`.
        """
        if self.metrics.circuit_open:
            return []

        all_records: list[ProductRecord] = []

        logger.info(
            "[{store}] Iniciando extracción para query='{query}' (max_pages={max_pages})",
            store=self.display_name,
            query=query,
            max_pages=max_pages,
        )

        page1_records, total_filtered = await self.search_page(query, page=1)
        all_records.extend(page1_records)

        if not page1_records or total_filtered == 0 or self.metrics.circuit_open:
            return all_records

        total_available_pages = math.ceil(total_filtered / self.RESULTS_PER_PAGE)
        if max_pages <= 0:
            target_pages = min(total_available_pages, self.MAX_EXHAUSTIVE_PAGES)
        else:
            target_pages = min(max_pages, total_available_pages)

        logger.info(
            "[{store}] '{query}': {total_filtered} resultados (~{total_available_pages} págs). "
            "Procesando {target_pages} págs.",
            store=self.display_name,
            query=query,
            total_filtered=total_filtered,
            total_available_pages=total_available_pages,
            target_pages=target_pages,
        )

        for page in range(2, target_pages + 1):
            if self.metrics.circuit_open:
                break
            page_records, _ = await self.search_page(query, page=page)
            if not page_records:
                break
            all_records.extend(page_records)

        if all_records and self.store_key in CENCOSUD_PROMO_CONFIG:
            all_records = await self._enrich_cencosud_promotions(all_records)

        return all_records

    async def extract_category(
        self,
        category_slug: str,
        *,
        max_pages: int = 1,
        page_size: int = 50,
    ) -> list[ProductRecord]:
        """Extrae productos de una categoría navegando el catálogo con paginación de a 50 items."""
        if self.metrics.circuit_open:
            return []

        category_path = category_slug.strip("/")
        endpoint = f"{self.vtex_store.origin}/api/catalog_system/pub/products/search/{category_path}"
        batch_size = min(max(page_size, 1), 50)

        all_records: list[ProductRecord] = []
        total_items: int | None = None

        logger.info(
            "[{store}] Extrayendo categoría '{cat}' (max_pages={max_pages}, batch_size={batch_size})",
            store=self.display_name,
            cat=category_slug,
            max_pages=max_pages,
            batch_size=batch_size,
        )

        page = 1
        effective_max = self.MAX_EXHAUSTIVE_PAGES if max_pages <= 0 else max_pages
        while page <= effective_max:
            if self.metrics.circuit_open:
                break

            offset_from = (page - 1) * batch_size
            offset_to = offset_from + batch_size - 1

            if total_items is not None and offset_from >= total_items:
                break

            params = {"_from": offset_from, "_to": offset_to}

            try:
                resp = await self.safe_get(endpoint, params=params)
                if resp.status_code not in (200, 206):
                    logger.warning(
                        "[{store}] Categoría '{cat}' p.{page} status {code}",
                        store=self.display_name,
                        cat=category_slug,
                        page=page,
                        code=resp.status_code,
                    )
                    break

                resources_header = resp.headers.get("resources")
                if resources_header and "/" in resources_header:
                    try:
                        total_items = int(resources_header.split("/")[-1])
                    except (ValueError, IndexError):
                        pass

                raw_products = resp.json()
                if not raw_products or not isinstance(raw_products, list):
                    break

                for raw in raw_products:
                    parsed = self._parse_product(raw, fallback_category=category_slug)
                    if parsed:
                        all_records.append(parsed)

                if len(raw_products) < batch_size:
                    break

                page += 1

            except CircuitOpenError:
                break
            except Exception as e:
                logger.warning(
                    "[{store}] Error al extraer categoría '{cat}' p.{page}: {err}",
                    store=self.display_name,
                    cat=category_slug,
                    page=page,
                    err=e,
                )
                break

        if all_records and self.store_key in CENCOSUD_PROMO_CONFIG:
            all_records = await self._enrich_cencosud_promotions(all_records)

        self.metrics.records_extracted += len(all_records)
        logger.info(
            "[{store}] Categoría '{cat}' finalizada: {count} productos extraídos (total: {total})",
            store=self.display_name,
            cat=category_slug,
            count=len(all_records),
            total=total_items if total_items is not None else "?",
        )
        return all_records

    async def _enrich_cencosud_promotions(
        self,
        records: list[ProductRecord],
    ) -> list[ProductRecord]:
        """Enriquece productos de Cencosud (Vea/Jumbo/Disco) con sus descuentos vigentes.

        Consulta en lotes de hasta 25 SKUs el servicio GraphQL `enrichPromotions` con
        alias por SKU. Ante cualquier error de red o cambio de API, degrada con gracia
        manteniendo intactos los precios regulares sin disparar el circuit breaker.
        """
        cfg = CENCOSUD_PROMO_CONFIG.get(self.store_key)
        if not cfg or not records or self._cencosud_promo_disabled or self.metrics.circuit_open:
            return records

        sender, seller = cfg
        missing_skus = list(
            dict.fromkeys(
                r.sku_id
                for r in records
                if r.sku_id
                and _SAFE_SKU_RE.match(r.sku_id)
                and r.sku_id not in self._cencosud_promo_cache
            )
        )

        if missing_skus:
            endpoint = f"{self.vtex_store.origin}/_v/public/graphql/v1"
            headers = {
                **self.get_headers(),
                "Origin": self.vtex_store.origin,
                "Referer": f"{self.vtex_store.origin}/",
                "Content-Type": "application/json",
            }
            for i in range(0, len(missing_skus), CENCOSUD_PROMO_BATCH_SIZE):
                batch = missing_skus[i : i + CENCOSUD_PROMO_BATCH_SIZE]
                aliases = "\n".join(
                    f'  s_{idx}: enrichPromotions(input: {{seller: "{seller}", skus: ["{sid}"]}}) '
                    f"{{ promotions {{ categoryType value code }} }}"
                    for idx, sid in enumerate(batch)
                )
                query = f'query BatchPromos @context(sender: "{sender}") {{\n{aliases}\n}}'

                try:
                    async with self._semaphore:
                        if self.request_delay_seconds > 0:
                            await asyncio.sleep(min(self.request_delay_seconds, 0.25))
                        resp = await self.client.post(
                            endpoint,
                            json={"query": query},
                            headers=headers,
                            timeout=8.0,
                        )

                    if resp.status_code != 200:
                        logger.debug(
                            "[{store}] enrichPromotions devolvió HTTP {code}; conservando precios base.",
                            store=self.display_name,
                            code=resp.status_code,
                        )
                        if resp.status_code in (400, 403, 404, 405):
                            self._cencosud_promo_disabled = True
                            break
                        continue

                    payload = resp.json()
                    data = payload.get("data") if isinstance(payload, dict) else None
                    if not isinstance(data, dict):
                        continue

                    for idx, sid in enumerate(batch):
                        node = data.get(f"s_{idx}")
                        promos = node.get("promotions") if isinstance(node, dict) else []
                        self._cencosud_promo_cache[sid] = promos if isinstance(promos, list) else []
                except Exception as e:
                    logger.debug(
                        "[{store}] Falló enriquecimiento de promos Cencosud (fallback a precio base): {err}",
                        store=self.display_name,
                        err=e,
                    )
                    break

        return [
            apply_cencosud_promotions(r, self._cencosud_promo_cache.get(r.sku_id, []))
            for r in records
        ]

    async def get_category_tree(self, levels: int = 2) -> list[dict[str, Any]]:
        """Obtiene el árbol de categorías nativo de VTEX."""
        url = f"{self.vtex_store.origin}/api/catalog_system/pub/category/tree/{levels}"
        try:
            resp = await self.safe_get(url)
            if resp.is_success:
                return resp.json()
        except Exception as e:
            logger.warning(
                "[{store}] Error al obtener categoría tree: {err}",
                store=self.display_name,
                err=e,
            )
        return []

    async def health_check(self) -> bool:
        """Comprueba conectividad con la API VTEX."""
        try:
            records, total = await self.search_page("yerba", page=1, count=1)
            return len(records) > 0 or total > 0
        except Exception:
            return False

    def _parse_product(
        self,
        item: dict[str, Any],
        *,
        fallback_category: str | None = None,
    ) -> ProductRecord | None:
        """Parsea un item crudo del JSON de VTEX a un ProductRecord validado."""
        try:
            items_list = item.get("items", [])
            if not items_list:
                return None

            sku = items_list[0]
            sellers = sku.get("sellers", [])
            if not sellers:
                return None

            offer = sellers[0].get("commertialOffer", {})
            raw_price = offer.get("Price", 0)
            raw_list_price = offer.get("ListPrice")
            raw_price_without_disc = offer.get("PriceWithoutDiscount")

            try:
                price = Decimal(str(raw_price))
            except (InvalidOperation, TypeError):
                price = Decimal("0")

            list_price = None
            if raw_list_price is not None:
                try:
                    list_price = Decimal(str(raw_list_price))
                except (InvalidOperation, TypeError):
                    pass

            # Corrección Cencosud (Jumbo/Disco/Vea): ListPrice almacena el precio sin impuestos
            # nacionales (Ley 27.743) en centavos (Price / 1.21 * 100), por lo que nunca es
            # un precio de lista válido cuando queda <= price.
            if list_price is not None and price > 0 and list_price > price * 50:
                list_price = list_price / 100

            if (list_price is None or list_price <= price) and raw_price_without_disc is not None:
                try:
                    pwd = Decimal(str(raw_price_without_disc))
                    if pwd > price:
                        list_price = pwd
                except (InvalidOperation, TypeError):
                    pass

            if list_price is not None and list_price <= price:
                list_price = None

            promo_label = extract_public_teaser_promo(
                offer.get("teasers") or offer.get("Teasers")
            )

            # Extracción de EAN
            ean = None
            ean_val = sku.get("ean")
            if ean_val:
                ean = str(ean_val)
            else:
                ref_ids = sku.get("referenceId", [])
                if ref_ids and isinstance(ref_ids, list):
                    ean = str(ref_ids[0].get("Value", "")) or None

            # Extracción de imagen normalizada a HTTPS
            images = sku.get("images", [])
            image_url = normalize_image_url(images[0].get("imageUrl")) if images else None

            # Extracción de URL canónica: priorizar `link` oficial de VTEX sobre `linkText`
            raw_link = item.get("link")
            raw_link_text = item.get("linkText")
            url_slug = None
            if isinstance(raw_link, str) and raw_link.strip():
                url_slug = raw_link.strip()
            elif isinstance(raw_link_text, str) and raw_link_text.strip():
                url_slug = raw_link_text.strip()

            # Extracción de categoría
            categories_raw = item.get("categories", [])
            category = fallback_category
            if categories_raw:
                parts = [p.strip() for p in categories_raw[0].split("/") if p.strip()]
                if parts:
                    category = " > ".join(parts)

            name = item.get("productName", "")
            available = offer.get("AvailableQuantity", 0) > 0
            available_quantity = offer.get("AvailableQuantity")

            rejection = classify_rejection_reason(
                name=name,
                price=price,
                available=available,
                available_quantity=available_quantity,
                ean=ean,
            )
            if rejection is not None:
                self.metrics.record_rejection(rejection)
                return None

            return ProductRecord(
                store=self.store_key,
                product_id=str(item.get("productId", "")),
                sku_id=str(sku.get("itemId", "")),
                ean=ean,
                name=name,
                brand=item.get("brand"),
                sku_name=sku.get("name"),
                category=category,
                url_slug=url_slug,
                image_url=image_url,
                price=price,
                list_price=list_price,
                promo_label=promo_label,
                available=available,
                available_quantity=available_quantity,
            )
        except Exception as e:
            logger.warning(
                "[{store}] Error parseando producto: {err}",
                store=self.display_name,
                err=e,
            )
            return None
