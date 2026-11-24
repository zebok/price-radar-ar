"""Extractor de productos y precios para Coto Digital.

Coto Digital utiliza un frontend respaldado por Constructor.io (ac.cnstrc.com).
Este extractor consulta el API pública de búsqueda y navegación por grupos,
obteniendo respuestas JSON limpias con EAN-13, descuentos y categorías mapeadas.
"""

from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from loguru import logger
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from ..filters import classify_rejection_reason
from ..models import ProductRecord, normalize_image_url
from .base import BaseExtractor, CircuitOpenError
from .vtex import is_retryable_error

GROUP_ID_TO_CATEGORY: dict[str, str] = {
    "catv00001254": "Almacén",
    "catv00001255": "Lácteos y Frescos",
    "catv00001256": "Bebidas",
    "catv00001257": "Perfumería",
    "catv00001258": "Limpieza",
    "catv00001296": "Congelados",
}


class CotoExtractor(BaseExtractor):
    """Extractor para Coto Digital vía Constructor.io API."""

    API_KEY = "key_r6xzz4IAoTWcipni"
    SEARCH_ENDPOINT = "https://ac.cnstrc.com/search/"
    BROWSE_GROUP_ENDPOINT = "https://ac.cnstrc.com/browse/group_id/"
    ORIGIN = "https://www.cotodigital3.com.ar"
    RESULTS_PER_PAGE = 24

    def __init__(
        self,
        *,
        max_concurrent: int = 3,
        request_delay_seconds: float = 0.4,
        timeout_seconds: float = 15.0,
        circuit_breaker_threshold: int = 3,
    ) -> None:
        super().__init__(
            store_key="coto",
            display_name="Coto",
            origin_url=self.ORIGIN,
            max_concurrent=max_concurrent,
            request_delay_seconds=request_delay_seconds,
            timeout_seconds=timeout_seconds,
            circuit_breaker_threshold=circuit_breaker_threshold,
        )

    def get_headers(self) -> dict[str, str]:
        headers = super().get_headers()
        headers.update({
            "Referer": f"{self.ORIGIN}/",
            "Origin": self.ORIGIN,
        })
        return headers

    @retry(
        retry=retry_if_exception(is_retryable_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1.0, max=8.0, jitter=0.5),
        reraise=True,
    )
    async def _fetch_constructor_page(
        self, query: str, page: int, count: int
    ) -> dict[str, Any]:
        """Consulta el motor Constructor.io de Coto."""
        endpoint = f"{self.SEARCH_ENDPOINT}{query}"
        params = {
            "key": self.API_KEY,
            "i": "client-ses-coto-1",
            "s": str(page),
            "page": str(page),
            "num_results_per_page": str(count),
        }
        resp = await self.safe_get(endpoint, params=params)
        resp.raise_for_status()
        return resp.json()

    async def search_page(
        self, query: str, *, page: int = 1, count: int = RESULTS_PER_PAGE
    ) -> tuple[list[ProductRecord], int]:
        """Obtiene una página de resultados desde Constructor.io."""
        if self.metrics.circuit_open:
            return [], 0

        try:
            data = await self._fetch_constructor_page(query, page, count)
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

        response_data = data.get("response", {})
        total_num_results = response_data.get("total_num_results", 0)
        results = response_data.get("results", [])

        records: list[ProductRecord] = []
        for r in results:
            parsed = self._parse_item(r)
            if parsed:
                records.append(parsed)

        self.metrics.records_extracted += len(records)
        return records, total_num_results

    async def extract_query(
        self, query: str, *, max_pages: int = 1
    ) -> list[ProductRecord]:
        """Extrae productos de Coto para una búsqueda, recorriendo páginas."""
        if self.metrics.circuit_open:
            return []

        all_records: list[ProductRecord] = []

        logger.info(
            "[{store}] Iniciando extracción para query='{query}' (max_pages={max_pages})",
            store=self.display_name,
            query=query,
            max_pages=max_pages,
        )

        page1_records, total_results = await self.search_page(query, page=1)
        all_records.extend(page1_records)

        if not page1_records or total_results == 0 or self.metrics.circuit_open:
            return all_records

        total_available_pages = math.ceil(total_results / self.RESULTS_PER_PAGE)
        if max_pages <= 0:
            target_pages = min(total_available_pages, self.MAX_EXHAUSTIVE_PAGES)
        else:
            target_pages = min(max_pages, total_available_pages)

        logger.info(
            "[{store}] '{query}': {total_results} resultados (~{total_available_pages} págs). "
            "Procesando {target_pages} págs.",
            store=self.display_name,
            query=query,
            total_results=total_results,
            total_available_pages=total_available_pages,
            target_pages=target_pages,
        )

        for p in range(2, target_pages + 1):
            if self.metrics.circuit_open:
                break
            page_records, _ = await self.search_page(query, page=p)
            if not page_records:
                break
            all_records.extend(page_records)

        return all_records

    @retry(
        retry=retry_if_exception(is_retryable_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1.0, max=8.0, jitter=0.5),
        reraise=True,
    )
    async def _fetch_constructor_browse(
        self, group_id: str, page: int, count: int
    ) -> dict[str, Any]:
        """Consulta el motor Constructor.io de Coto por grupo/categoría."""
        endpoint = f"{self.BROWSE_GROUP_ENDPOINT}{group_id}"
        params = {
            "key": self.API_KEY,
            "i": "client-ses-coto-1",
            "s": str(page),
            "page": str(page),
            "num_results_per_page": str(count),
        }
        resp = await self.safe_get(endpoint, params=params)
        resp.raise_for_status()
        return resp.json()

    async def browse_page(
        self,
        group_id: str,
        *,
        page: int = 1,
        count: int = 50,
        default_category: str | None = None,
    ) -> tuple[list[ProductRecord], int]:
        """Obtiene una página de resultados por grupo/categoría desde Constructor.io."""
        if self.metrics.circuit_open:
            return [], 0

        try:
            data = await self._fetch_constructor_browse(group_id, page, count)
        except CircuitOpenError:
            return [], 0
        except Exception as e:
            logger.warning(
                "[{store}] Falló el browse de grupo '{group}' (página {page}): {err}",
                store=self.display_name,
                group=group_id,
                page=page,
                err=e,
            )
            return [], 0

        response_data = data.get("response", {})
        total_num_results = response_data.get("total_num_results", 0)
        results = response_data.get("results", [])

        fallback_cat = default_category or GROUP_ID_TO_CATEGORY.get(group_id)
        records: list[ProductRecord] = []
        for r in results:
            parsed = self._parse_item(r, default_category=fallback_cat)
            if parsed:
                records.append(parsed)

        self.metrics.records_extracted += len(records)
        return records, total_num_results

    async def extract_category(
        self,
        category_slug: str,
        *,
        max_pages: int = 1,
        page_size: int = 50,
    ) -> list[ProductRecord]:
        """Extrae productos de una categoría navegando por group_id en Constructor.io."""
        if self.metrics.circuit_open:
            return []

        group_id = category_slug.strip()
        canonical_map = {
            "almacen": "catv00001254",
            "frescos": "catv00001255",
            "lacteos_frescos": "catv00001255",
            "bebidas": "catv00001256",
            "perfumeria": "catv00001257",
            "limpieza": "catv00001258",
            "congelados": "catv00001296",
        }
        if group_id.lower() in canonical_map:
            group_id = canonical_map[group_id.lower()]

        if not group_id.startswith("catv"):
            return await self.extract_query(category_slug, max_pages=max_pages)

        default_cat = GROUP_ID_TO_CATEGORY.get(group_id, category_slug)
        all_records: list[ProductRecord] = []
        logger.info(
            "[{store}] Iniciando browse de categoría '{group}' ({cat}, max_pages={max_pages})",
            store=self.display_name,
            group=group_id,
            cat=default_cat,
            max_pages=max_pages,
        )

        page1_records, total_results = await self.browse_page(
            group_id, page=1, count=page_size, default_category=default_cat
        )
        all_records.extend(page1_records)

        if not page1_records or total_results == 0 or self.metrics.circuit_open:
            return all_records

        total_available_pages = math.ceil(total_results / page_size)
        if max_pages <= 0:
            target_pages = min(total_available_pages, self.MAX_EXHAUSTIVE_PAGES)
        else:
            target_pages = min(max_pages, total_available_pages)

        logger.info(
            "[{store}] '{group}': {total_results} productos (~{total_available_pages} págs). "
            "Procesando {target_pages} págs.",
            store=self.display_name,
            group=group_id,
            total_results=total_results,
            total_available_pages=total_available_pages,
            target_pages=target_pages,
        )

        for p in range(2, target_pages + 1):
            if self.metrics.circuit_open:
                break
            page_records, _ = await self.browse_page(
                group_id, page=p, count=page_size, default_category=default_cat
            )
            if not page_records:
                break
            all_records.extend(page_records)

        return all_records

    async def health_check(self) -> bool:
        """Comprueba conectividad con el API de Coto / Constructor.io."""
        try:
            records, total = await self.search_page("yerba", page=1, count=1)
            return len(records) > 0 or total > 0
        except Exception:
            return False

    @staticmethod
    def _extract_category(data: dict[str, Any], default_category: str | None) -> str | None:
        """Extrae la categoría desde los grupos/facets de Constructor.io o usa fallback."""
        groups = data.get("groups")
        if isinstance(groups, list) and groups:
            names = [
                str(g.get("display_name", "")).strip()
                for g in groups
                if isinstance(g, dict) and g.get("display_name")
            ]
            if names:
                return " > ".join(names[:3])

        facets = data.get("facets")
        if isinstance(facets, dict):
            for key in ("category", "categoria", "departamento", "rubro"):
                val = facets.get(key)
                if isinstance(val, list) and val:
                    return str(val[0]).strip()
                if isinstance(val, str) and val.strip():
                    return val.strip()

        raw_cat = data.get("category") or data.get("product_category")
        if isinstance(raw_cat, str) and raw_cat.strip():
            return raw_cat.strip()

        return default_category

    def _parse_item(
        self,
        item: dict[str, Any],
        *,
        default_category: str | None = None,
    ) -> ProductRecord | None:
        """Parsea un resultado de Constructor.io al ProductRecord canónico."""
        try:
            name = item.get("value", "")
            if not name:
                return None

            data = item.get("data", {})
            prod_id = str(data.get("id", ""))
            sku_id = str(data.get("sku_id", prod_id))
            ean = data.get("product_main_ean")
            brand = data.get("product_brand")
            sku_name = data.get("sku_display_name")

            raw_list_price = data.get("product_list_price")
            try:
                list_price = Decimal(str(raw_list_price)) if raw_list_price is not None else None
            except (InvalidOperation, TypeError):
                list_price = None

            price = list_price or Decimal("0")
            promo_label: str | None = None
            discounts = data.get("discounts", [])
            if discounts and isinstance(discounts, list):
                for disc in discounts:
                    if not isinstance(disc, dict):
                        continue
                    disc_img = str(disc.get("discountImage") or "").lower()
                    disc_text = str(disc.get("discountText") or "").strip()
                    taking_text = str(disc.get("takingText") or "").strip()

                    # Omitir beneficios exclusivos de tarjetas/comunidad (+5% Comunidad Coto)
                    if "comunidad" in disc_img or disc_text.startswith("+"):
                        continue

                    is_multiunit = bool(taking_text) or bool(
                        re.search(
                            r"(?:2(?:da|do)|[2-9]\s*x\s*[1-8]|llevando)",
                            disc_text,
                            re.IGNORECASE,
                        )
                    )

                    if is_multiunit:
                        # Promoción condicional por cantidad: conservar el precio de 1 unidad
                        # y registrar una etiqueta limpia (ej: "50% 2da" -> "2do al 50%")
                        m_2da = re.search(r"(\d{1,2})\s*%\s*2(?:da|do)", disc_text, re.IGNORECASE)
                        if m_2da:
                            promo_label = f"2do al {m_2da.group(1)}%"
                        else:
                            promo_label = disc_text or taking_text
                        break

                    disc_price_str = disc.get("discountPrice")
                    if disc_price_str:
                        clean_p = re.sub(r"[^\d.]", "", str(disc_price_str))
                        try:
                            parsed_p = Decimal(clean_p)
                            if parsed_p > 0:
                                price = parsed_p
                        except (InvalidOperation, TypeError):
                            pass
                    break

            if (list_price is None or list_price == 0) and data.get("price"):
                p0 = data["price"][0]
                raw_lp = p0.get("listPrice") or p0.get("formatPrice")
                if raw_lp:
                    try:
                        list_price = Decimal(str(raw_lp))
                        if price == 0:
                            price = list_price
                    except (InvalidOperation, TypeError):
                        pass

            image_url = normalize_image_url(
                data.get("product_large_image_url")
                or data.get("product_medium_image_url")
                or data.get("image_url")
            )
            url_path = data.get("url")
            url_slug = url_path.strip("/") if url_path else None

            store_avail = data.get("store_availability")
            if store_avail is not None:
                available = bool(store_avail) if isinstance(store_avail, (list, bool, int)) else True
            else:
                available = True

            rejection = classify_rejection_reason(
                name=name,
                price=price,
                available=available,
                ean=str(ean) if ean else None,
            )
            if rejection is not None:
                self.metrics.record_rejection(rejection)
                return None

            category = self._extract_category(data, default_category)

            return ProductRecord(
                store=self.store_key,
                product_id=prod_id,
                sku_id=sku_id,
                ean=str(ean) if ean else None,
                name=name,
                brand=str(brand) if brand else None,
                sku_name=sku_name,
                category=category,
                url_slug=url_slug,
                image_url=image_url,
                price=price,
                list_price=list_price if list_price and list_price > price else None,
                promo_label=promo_label,
                available=available,
                available_quantity=None,
            )
        except Exception as e:
            logger.warning("[Coto] Error parseando producto: {}", e)
            return None
