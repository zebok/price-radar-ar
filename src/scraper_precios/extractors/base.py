"""Clase base abstracta para extractores de precios (BaseExtractor).

Define la interfaz común, gestión de ciclo de vida HTTP (httpx con HTTP/2),
rate limiting polite, rotación de User-Agents, circuit breaker por tienda
y métricas operacionales detalladas (latencia, tasa de éxito y rechazos).
"""

from __future__ import annotations

import abc
import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from loguru import logger

from ..models import ProductRecord

REALISTIC_USER_AGENTS: list[str] = [
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) "
        "Gecko/20100101 Firefox/128.0"
    ),
]


class CircuitOpenError(RuntimeError):
    """Se lanza cuando una tienda supera el umbral de fallos consecutivos."""


@dataclass
class ExtractorMetrics:
    """Métricas operacionales y de calidad de extracción para observabilidad."""

    store_name: str
    store_key: str = ""
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    requests_total: int = 0
    requests_success: int = 0
    requests_failed: int = 0
    consecutive_failures: int = 0
    circuit_open: bool = False
    records_extracted: int = 0
    bytes_received: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    rejection_counts: dict[str, int] = field(default_factory=dict)
    error_message: str | None = None

    def record_rejection(self, reason: str) -> None:
        self.rejection_counts[reason] = self.rejection_counts.get(reason, 0) + 1

    @property
    def duration_seconds(self) -> float:
        end = self.end_time or time.time()
        return round(end - self.start_time, 2)

    @property
    def success_rate(self) -> float:
        if self.requests_total == 0:
            return 100.0
        return round((self.requests_success / self.requests_total) * 100, 1)

    @property
    def avg_latency_ms(self) -> float:
        if not self.latencies_ms:
            return 0.0
        return round(sum(self.latencies_ms) / len(self.latencies_ms), 1)

    @property
    def throughput_records_sec(self) -> float:
        d = self.duration_seconds
        return round(self.records_extracted / d, 1) if d > 0 else 0.0

    @property
    def status(self) -> str:
        if self.circuit_open:
            return "circuit_open"
        if self.records_extracted == 0 and self.requests_failed > 0:
            return "failed"
        if self.requests_failed > 0 and self.success_rate < 90.0:
            return "degraded"
        return "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_key": self.store_key or self.store_name.lower(),
            "store_name": self.store_name,
            "status": self.status,
            "requests_total": self.requests_total,
            "requests_success": self.requests_success,
            "requests_failed": self.requests_failed,
            "success_rate_pct": self.success_rate,
            "avg_latency_ms": self.avg_latency_ms,
            "duration_seconds": self.duration_seconds,
            "records_extracted": self.records_extracted,
            "throughput_records_sec": self.throughput_records_sec,
            "circuit_open": self.circuit_open,
            "rejection_counts": dict(self.rejection_counts),
            "error_message": self.error_message,
        }


class BaseExtractor(abc.ABC):
    """Clase base abstracta para todos los extractores de supermercados.

    Provee:
    - Context manager asíncrono para gestionar httpx.AsyncClient compartido
    - Rate limiting semafórico y delay configurable
    - Rotación de User-Agents y cabeceras realistas
    - Circuit breaker ante fallos consecutivos (403/5xx/red) para no trabar corridas
    - Métricas operacionales y conteo de descartes de calidad
    """

    CIRCUIT_FAILURE_STATUSES = {403, 429, 500, 502, 503, 504}
    MAX_EXHAUSTIVE_PAGES = 50

    def __init__(
        self,
        store_key: str,
        display_name: str,
        origin_url: str,
        *,
        max_concurrent: int = 3,
        request_delay_seconds: float = 0.4,
        timeout_seconds: float = 15.0,
        circuit_breaker_threshold: int = 3,
    ) -> None:
        self.store_key = store_key
        self.display_name = display_name
        self.origin_url = origin_url.rstrip("/")
        self.request_delay_seconds = request_delay_seconds
        self.timeout_seconds = timeout_seconds
        self.circuit_breaker_threshold = max(1, circuit_breaker_threshold)

        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._ua_index = 0
        self._last_request_time: float = 0.0
        self._client: httpx.AsyncClient | None = None
        self.metrics = ExtractorMetrics(store_name=display_name, store_key=store_key)

    async def __aenter__(self) -> BaseExtractor:
        """Inicializa el cliente HTTP asíncrono optimizado."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                http2=True,
                follow_redirects=True,
                timeout=httpx.Timeout(self.timeout_seconds, connect=10.0),
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            )
        self.metrics = ExtractorMetrics(store_name=self.display_name, store_key=self.store_key)
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Cierra el cliente HTTP y finaliza métricas."""
        self.metrics.end_time = time.time()
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Retorna el cliente HTTP activo. Lanza RuntimeError si no está en contexto async."""
        if self._client is None or self._client.is_closed:
            raise RuntimeError(
                f"Extractor {self.display_name} no inicializado. Usar 'async with extractor:'"
            )
        return self._client

    def get_headers(self) -> dict[str, str]:
        """Genera headers HTTP realistas con rotación de User-Agent."""
        ua = REALISTIC_USER_AGENTS[self._ua_index % len(REALISTIC_USER_AGENTS)]
        self._ua_index += 1
        return {
            "User-Agent": ua,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
            "Origin": self.origin_url,
            "Referer": f"{self.origin_url}/",
            "Connection": "keep-alive",
            "Sec-Ch-Ua": '"Chromium";v="126", "Not(A:Brand";v="24", "Google Chrome";v="126"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"macOS"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

    def _register_failure(self, reason: str) -> None:
        self.metrics.requests_failed += 1
        self.metrics.consecutive_failures += 1
        self.metrics.error_message = reason
        if self.metrics.consecutive_failures >= self.circuit_breaker_threshold:
            if not self.metrics.circuit_open:
                self.metrics.circuit_open = True
                logger.warning(
                    "[{store}] Circuit breaker ABIERTO tras {n} fallos consecutivos ({reason}). "
                    "Se omiten las consultas restantes de esta tienda.",
                    store=self.display_name,
                    n=self.metrics.consecutive_failures,
                    reason=reason,
                )

    async def safe_get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Ejecuta una petición GET con rate limiting, delay, métricas y circuit breaker."""
        if self.metrics.circuit_open:
            raise CircuitOpenError(f"Circuit breaker abierto para {self.display_name}")

        headers = self.get_headers()
        if extra_headers:
            headers.update(extra_headers)

        async with self._semaphore:
            if self.metrics.circuit_open:
                raise CircuitOpenError(f"Circuit breaker abierto para {self.display_name}")

            elapsed_since_last = time.time() - self._last_request_time
            if elapsed_since_last < self.request_delay_seconds:
                await asyncio.sleep(self.request_delay_seconds - elapsed_since_last)

            self.metrics.requests_total += 1
            req_start = time.time()
            try:
                response = await self.client.get(url, params=params, headers=headers)
                latency_ms = round((time.time() - req_start) * 1000, 1)
                self._last_request_time = time.time()
                self.metrics.latencies_ms.append(latency_ms)
                self.metrics.bytes_received += len(response.content)

                if response.is_success:
                    self.metrics.requests_success += 1
                    self.metrics.consecutive_failures = 0
                else:
                    if response.status_code in self.CIRCUIT_FAILURE_STATUSES:
                        self._register_failure(f"HTTP {response.status_code}")
                    else:
                        self.metrics.requests_failed += 1
                    logger.warning(
                        "[{store}] HTTP {status} al consultar {url}",
                        store=self.display_name,
                        status=response.status_code,
                        url=url,
                    )
                return response
            except CircuitOpenError:
                raise
            except Exception as e:
                self._last_request_time = time.time()
                self._register_failure(f"{type(e).__name__}: {e}")
                logger.error(
                    "[{store}] Error en GET {url}: {err}",
                    store=self.display_name,
                    url=url,
                    err=e,
                )
                raise

    @abc.abstractmethod
    async def extract_query(
        self, query: str, *, max_pages: int = 1
    ) -> list[ProductRecord]:
        """Extrae productos para un término de búsqueda, paginando hasta max_pages."""
        ...

    @abc.abstractmethod
    async def extract_category(
        self, category_slug: str, *, max_pages: int = 1
    ) -> list[ProductRecord]:
        """Extrae productos de una categoría específica."""
        ...

    @abc.abstractmethod
    async def health_check(self) -> bool:
        """Verifica la conectividad y respuesta saludable de la API."""
        ...
