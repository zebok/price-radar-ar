"""Servidor HTTP FastAPI liviano para la Web App (PWA) y API REST `/v1`.

Características:
- Sirve la Web App / PWA directamente en `/` y los bundles JSON en `/data/*.json`
  generados al vuelo desde el Lakehouse Parquet activo (con caché automática por mtime).
- Expone endpoints REST JSON limpios bajo `/v1` con documentación Swagger en `/docs`.
- Acceso abierto por defecto; API Key (`X-API-Key` o `Authorization: Bearer`) 100% opcional.
"""

from __future__ import annotations

import secrets
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Security,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import (
    APIKeyHeader,
    APIKeyQuery,
    HTTPAuthorizationCredentials,
    HTTPBearer,
)
from loguru import logger
from pydantic import BaseModel, Field

from .analytics.duckdb_runner import run_executive_report
from .assistant import optimize_shopping_list
from .benchmark import compute_market_reference
from .config import Settings
from .evaluator import evaluate_deal
from .extractors import get_extractor, list_available_stores
from .favorites import (
    FavoriteItem,
    add_or_update_favorite,
    get_favorites_with_live_prices,
    remove_favorite,
    toggle_favorite,
)
from .pipeline.cross_store import get_top_discounts, match_products_cross_store
from .pipeline.export_web import _build_analytics_payload, _build_compact_catalog
from .pipeline.quality import load_latest_quality_report
from .pipeline.runner import run_etl_pipeline
from .query_engine import (
    find_benchmark_for_product,
    get_catalog_categories,
    get_cross_store_catalog,
    get_price_trend_for_product,
    get_stockup_deals,
    get_store_freshness,
    get_weekly_market_trends,
    invalidate_silver_cache,
    search_products,
)
from .storage import (
    get_silver_mtime,
    load_active_silver_with_freshness,
    load_all_silver,
    load_latest_silver,
)

APP_VERSION = "2.0.0"

app = FastAPI(
    title="ChangoRadar — Supermarket Pricing ETL & API",
    description=(
        "Motor ETL Medallion (Polars + Parquet + DuckDB), comparador cross-store, "
        "evaluador de promociones caza-bobos y Web App/PWA para supermercados de Argentina."
    ),
    version=APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

BEARER_SCHEME = HTTPBearer(auto_error=False)
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
API_KEY_QUERY = APIKeyQuery(name="api_key", auto_error=False)

# Caché en memoria para los bundles JSON dinámicos servidos a la Web App
_BUNDLE_CACHE: dict[str, tuple[tuple[str, float], dict[str, Any]]] = {}


def _get_web_dir() -> Path:
    settings = Settings()
    if settings.web_dir.exists():
        return settings.web_dir
    project_web = Path(__file__).resolve().parents[2] / "web"
    return project_web


def _invalidate_all_caches() -> None:
    _BUNDLE_CACHE.clear()
    invalidate_silver_cache()


def verify_auth(
    bearer: HTTPAuthorizationCredentials | None = Security(BEARER_SCHEME),
    header_key: str | None = Security(API_KEY_HEADER),
    query_key: str | None = Security(API_KEY_QUERY),
) -> dict[str, Any]:
    """Autenticación opcional por API Key (acceso público por defecto)."""
    settings = Settings()

    token: str | None = None
    if bearer and bearer.credentials:
        token = bearer.credentials.strip()
    elif header_key:
        token = header_key.strip()
    elif query_key:
        token = query_key.strip()

    if not settings.require_auth and not token:
        return {"role": "public", "auth_method": "anonymous"}

    if not settings.api_key:
        return {"role": "open", "auth_method": "none"}

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida. Envíe una API Key ('X-API-Key: <key>' o 'Authorization: Bearer <key>').",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if secrets.compare_digest(token, settings.api_key.strip()):
        return {"role": "service_role", "auth_method": "api_key"}

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="API Key inválida.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def is_port_free(port: int, host: str = "0.0.0.0") -> bool:
    """Verifica si un puerto TCP está libre para bind."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return True
    except OSError:
        return False


def find_available_port(start_port: int = 8001, max_tries: int = 50) -> int:
    """Busca el primer puerto libre a partir de start_port."""
    for p in range(start_port, start_port + max_tries):
        if is_port_free(p):
            return p
    return get_free_port()


def get_free_port() -> int:
    """Encuentra un puerto libre asignado por el sistema operativo."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.listen(1)
        return s.getsockname()[1]


def resolve_server_port(target_port: int | None = None) -> int:
    """Resuelve el puerto dinámico para ejecución local o contenedor."""
    import os

    if target_port is not None and target_port > 0:
        if is_port_free(target_port):
            return target_port
        logger.warning("Puerto {} ocupado. Buscando siguiente puerto libre...", target_port)
        return find_available_port(target_port + 1)

    for i, arg in enumerate(sys.argv):
        if arg in ("--port", "-p") and i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit():
            p = int(sys.argv[i + 1])
            return get_free_port() if p == 0 else (p if is_port_free(p) else find_available_port(p + 1))
        if arg.startswith("--port="):
            val = arg.split("=", 1)[1]
            if val.isdigit():
                p = int(val)
                return get_free_port() if p == 0 else (p if is_port_free(p) else find_available_port(p + 1))

    env_port = os.getenv("PORT")
    if env_port and env_port.isdigit():
        return int(env_port)

    settings = Settings()
    if settings.port > 0:
        if is_port_free(settings.port):
            return settings.port
        return find_available_port(settings.port + 1)

    return find_available_port(8001)


# ──────────────────────────────────────────────────────────────
#  Modelos de Request (Pydantic v2)
# ──────────────────────────────────────────────────────────────
class ExtractRequest(BaseModel):
    stores: list[str] = Field(default=["all"], description="Tiendas a extraer o ['all']")
    queries: list[str] | None = Field(default=None, description="Términos de búsqueda opcionales")
    basket_type: str | None = Field(default=None, description="'core' o 'extended'")
    fmcg: bool = Field(default=False, description="Extraer árbol completo de categorías FMCG")
    pages: int = Field(default=1, ge=0, le=50, description="Páginas por búsqueda/categoría (0 = exhaustivo)")
    sync_to_cloud: bool = Field(default=False, description="Subir capas Parquet a GCS si está configurado")


class InspectPromoRequest(BaseModel):
    product_name: str = Field(..., description="Nombre del producto (ej: 'Yerba Playadito 1kg')")
    store: str = Field(default="coto", description="Supermercado donde está la oferta")
    regular_price: float = Field(..., gt=0, description="Precio de lista de 1 unidad")
    promo_type: str = Field(
        default="none",
        description="'2do_al_70', '2do_al_80', '2do_al_50', '3x2', '4x3', 'direct_pct', 'direct_amount', 'none'",
    )
    promo_discount_pct: float | None = Field(default=None, ge=0, le=100)
    promo_discount_amount: float | None = Field(default=None, ge=0)
    payment_discount_pct: float | None = Field(default=None, ge=0, le=100)
    category: str | None = Field(default=None)


class OptimizeListRequest(BaseModel):
    items: list[Any] = Field(..., description="Lista de productos a cotizar")


class FavoriteItemCreateRequest(BaseModel):
    id: str = Field(..., description="Slug único del favorito")
    name: str = Field(..., description="Nombre visible")
    query: str = Field(..., description="Término de búsqueda")
    category: str = Field(default="almacen")
    preferred_brands: list[str] = Field(default=[])
    unit_target: str = Field(default="$/item")
    is_favorite: bool = Field(default=True)
    notes: str = Field(default="")


# ──────────────────────────────────────────────────────────────
#  1. Web App / PWA y Healthcheck
# ──────────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
async def serve_web_root() -> Any:
    """Sirve la Web App / PWA si existe `web/index.html`; de lo contrario info JSON."""
    index_path = _get_web_dir() / "index.html"
    if index_path.exists():
        return FileResponse(index_path, media_type="text/html; charset=utf-8")
    return JSONResponse(
        {
            "service": "ChangoRadar Pricing Engine API",
            "status": "online",
            "version": APP_VERSION,
            "docs": "/docs",
        }
    )


@app.get("/health", tags=["Salud"])
async def health_check() -> dict[str, Any]:
    """Healthcheck probe para ejecución local, Docker o Cloud Run."""
    settings = Settings()
    return {
        "status": "healthy",
        "service": "scraper-precios",
        "version": APP_VERSION,
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "available_stores": list_available_stores(),
        "stores_freshness": get_store_freshness(settings.data_dir),
    }


def _get_cached_bundle(kind: str) -> dict[str, Any]:
    settings = Settings()
    data_dir = Path(settings.data_dir)
    cache_key = (str(data_dir.resolve()), get_silver_mtime(data_dir))
    cached = _BUNDLE_CACHE.get(kind)
    if cached and cached[0] == cache_key:
        return cached[1]

    if kind == "catalog":
        active_df, freshness = load_active_silver_with_freshness(data_dir, max_days=settings.carry_forward_max_days)
        payload = _build_compact_catalog(active_df, freshness)
    elif kind == "analytics":
        active_df, _ = load_active_silver_with_freshness(data_dir, max_days=settings.carry_forward_max_days)
        all_df = load_all_silver(data_dir, max_days=30)
        payload = _build_analytics_payload(data_dir, active_df, all_df)
    else:
        payload = load_latest_quality_report(data_dir)

    _BUNDLE_CACHE[kind] = (cache_key, payload)
    return payload


@app.get("/data/{bundle_name}.json", include_in_schema=False)
def serve_live_web_bundle(bundle_name: str) -> JSONResponse:
    """Sirve `catalog.json`, `analytics.json` y `quality.json` al vuelo desde el Lakehouse activo."""
    if bundle_name not in {"catalog", "analytics", "quality"}:
        raise HTTPException(status_code=404, detail="Bundle no encontrado")
    return JSONResponse(_get_cached_bundle(bundle_name))


@app.get("/{asset_name}", include_in_schema=False)
def serve_web_asset(asset_name: str) -> FileResponse:
    """Sirve los assets estáticos de primer nivel de la PWA (`styles.css`, `app.js`, `manifest.json`, `sw.js`, `icon.svg`)."""
    allowed = {"styles.css", "app.js", "manifest.json", "sw.js", "icon.svg"}
    if asset_name not in allowed:
        raise HTTPException(status_code=404, detail="Recurso no encontrado")
    asset_path = _get_web_dir() / asset_name
    if not asset_path.exists():
        raise HTTPException(status_code=404, detail="Asset no encontrado")
    return FileResponse(asset_path)


# ──────────────────────────────────────────────────────────────
#  2. API REST `/v1`
# ──────────────────────────────────────────────────────────────
v1_router = APIRouter(dependencies=[Depends(verify_auth)])


@v1_router.get("/info", tags=["Salud"])
def api_info() -> dict[str, Any]:
    """Metadatos generales del servicio y tiendas monitoreadas."""
    return {
        "service": "ChangoRadar Pricing Engine API",
        "status": "online",
        "version": APP_VERSION,
        "docs": "/docs",
        "available_stores": list_available_stores(),
    }


@v1_router.get("/stores", tags=["Supermercados"])
async def check_stores_health() -> list[dict[str, Any]]:
    """Verifica el estado y latencia en vivo de las APIs de supermercados."""
    results = []
    for key in list_available_stores():
        extractor = get_extractor(key)
        start_t = datetime.now(UTC)
        try:
            async with extractor:
                is_active = await extractor.health_check()
            elapsed_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000
            results.append({
                "store_key": key,
                "name": extractor.display_name,
                "origin": extractor.origin_url,
                "active": is_active,
                "latency_ms": round(elapsed_ms, 1),
            })
        except Exception as e:
            results.append({
                "store_key": key,
                "name": extractor.display_name,
                "origin": extractor.origin_url,
                "active": False,
                "error": str(e),
            })
    return results


@v1_router.get("/products/search", tags=["Catálogo"])
def api_search_products(
    query: str | None = Query(None, description="Término libre (ej: 'yerba', 'roast beef')"),
    store: str | None = Query(None, description="Tienda ('coto', 'carrefour', etc.) o 'all'"),
    category: str | None = Query(None, description="Filtrar por categoría"),
    min_discount: float | None = Query(None, ge=0),
    sort_by: str = Query("price_asc", description="'price_asc', 'price_desc', 'unit_price_asc', 'discount_desc'"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Búsqueda granular paginada con ordenamiento por precio o `$/kg` y `$/L`."""
    return search_products(
        query=query,
        store=store,
        category=category,
        min_discount=min_discount,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
    )


@v1_router.get("/catalog/cross-store", tags=["Catálogo"])
def api_get_cross_store_catalog(
    query: str | None = Query(None),
    store: str | None = Query(None),
    cheapest_store: str | None = Query(None),
    category: str | None = Query(None),
    macro_category: str | None = Query(None),
    min_stores: int = Query(1, ge=1, le=6),
    min_spread: float | None = Query(None, ge=0),
    eans: str | None = Query(None),
    sort_by: str = Query("price_asc"),
    limit: int = Query(40, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Catálogo cross-store multi-supermercado con detección automática del menor precio."""
    ean_list = [e.strip() for e in eans.split(",") if e.strip()] if eans else None
    return get_cross_store_catalog(
        query=query,
        store=store,
        cheapest_store=cheapest_store,
        category=category,
        macro_category=macro_category,
        min_stores=min_stores,
        min_spread=min_spread,
        eans=ean_list,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
    )


@v1_router.get("/catalog/categories", tags=["Catálogo"])
def api_get_catalog_categories(min_count: int = Query(1, ge=1)) -> list[dict[str, Any]]:
    """Listado de categorías consolidadas con conteo de productos."""
    return get_catalog_categories(min_count=min_count)


@v1_router.post("/catalog/refresh-cache", tags=["Catálogo"])
def api_refresh_catalog_cache() -> dict[str, str]:
    """Invalida manualmente la caché en RAM."""
    _invalidate_all_caches()
    return {"status": "ok", "message": "Caché invalidada exitosamente"}


@v1_router.post("/deals/evaluate", tags=["Ofertas & Promociones"])
def api_evaluate_deal(req: InspectPromoRequest) -> dict[str, Any]:
    """Evalúa si una promoción de góndola es oportunidad real o falso descuento caza-bobos."""
    benchmark = find_benchmark_for_product(product_name=req.product_name, category=req.category)
    evaluation = evaluate_deal(
        product_name=req.product_name,
        store=req.store,
        regular_price=req.regular_price,
        promo_type=req.promo_type,
        promo_discount_pct=req.promo_discount_pct,
        promo_discount_amount=req.promo_discount_amount,
        payment_discount_pct=req.payment_discount_pct,
        category=req.category,
        market_benchmark=benchmark,
    )
    return {
        "product_name": evaluation.product_name,
        "store": evaluation.store,
        "verdict": evaluation.verdict.value,
        "is_cazabobos": evaluation.is_cazabobos,
        "is_stockup_worthy": evaluation.is_stockup_worthy,
        "savings_pct_vs_cheapest": evaluation.savings_pct_vs_cheapest,
        "savings_amount_per_unit": evaluation.savings_amount_per_unit,
        "recommendation": evaluation.recommendation,
        "calculation": {
            "regular_unit_price": evaluation.calculation.regular_unit_price,
            "effective_unit_price": evaluation.calculation.effective_unit_price,
            "units_required": evaluation.calculation.units_required,
            "total_cost_for_bundle": evaluation.calculation.total_cost_for_bundle,
            "effective_discount_pct": evaluation.calculation.effective_discount_pct,
            "promo_description": evaluation.calculation.promo_description,
        },
        "market": {
            "cheapest_store": evaluation.market.cheapest_store,
            "cheapest_price": evaluation.market.cheapest_price,
            "cheapest_product_name": evaluation.market.cheapest_product_name,
            "cheapest_product_url": evaluation.market.cheapest_product_url,
            "average_market_price": evaluation.market.average_market_price,
            "total_matches_found": evaluation.market.total_matches_found,
            "competitor_prices": evaluation.market.competitor_prices,
        },
    }


@v1_router.get("/deals", tags=["Ofertas & Promociones"])
def get_current_deals(min_discount: float = 15.0, limit: int = 20) -> list[dict[str, Any]]:
    """Retorna las mejores ofertas verificadas del snapshot Silver."""
    settings = Settings()
    df = load_latest_silver(settings.data_dir)
    if df.is_empty():
        return []
    return get_top_discounts(df, min_discount_pct=min_discount, limit=limit).to_dicts()


@v1_router.get("/deals/stockup", tags=["Ofertas & Promociones"])
def api_get_stockup_deals(
    min_discount: float = Query(20.0, ge=5.0),
    limit: int = Query(30, ge=1, le=100),
) -> list[dict[str, Any]]:
    """Identifica productos no perecederos con fuerte descuento para stockeo."""
    return get_stockup_deals(min_discount=min_discount, limit=limit)


@v1_router.get("/comparison", tags=["Ofertas & Promociones"])
def get_cross_store_comparison() -> list[dict[str, Any]]:
    """Retorna la tabla Gold de comparativa cross-store por EAN."""
    settings = Settings()
    df = load_latest_silver(settings.data_dir)
    if df.is_empty():
        return []
    return match_products_cross_store(df).to_dicts()


@v1_router.get("/trends/product", tags=["Analítica & BI"])
def api_get_price_trend(
    query: str = Query(...),
    store: str | None = Query(None),
    days: int = Query(7, ge=1, le=90),
) -> dict[str, Any]:
    """Retorna la evolución histórica de precio de un producto."""
    return get_price_trend_for_product(query=query, store=store, days=days)


@v1_router.get("/trends/weekly", tags=["Analítica & BI"])
def api_get_weekly_market_trends(
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(15, ge=1, le=100),
) -> dict[str, Any]:
    """Retorna la inflación observada de la canasta y top aumentos/bajas."""
    return get_weekly_market_trends(days=days, limit=limit)


@v1_router.get("/analytics/sql-report", tags=["Analítica & BI"])
def api_get_sql_analytics_report() -> dict[str, Any]:
    """Ejecuta las vistas SQL analíticas de DuckDB sobre el Lakehouse Parquet."""
    settings = Settings()
    return run_executive_report(settings.data_dir)


@v1_router.get("/quality", tags=["Analítica & BI"])
def api_get_quality_report() -> dict[str, Any]:
    """Retorna el reporte de Data Quality, embudo Medallion y frescura por tienda."""
    return _get_cached_bundle("quality")


@v1_router.post("/assistant/optimize-list", tags=["Asistente de Compras"])
def api_optimize_shopping_list(req: OptimizeListRequest) -> dict[str, Any]:
    """Optimiza una lista de compras: mejor compra única vs compra partida óptima."""
    return optimize_shopping_list(req.items)


@v1_router.get("/benchmark/reference-price", tags=["Asistente de Compras"])
def api_get_market_reference(
    product: str = Query(...),
    quantity: float = Query(1.0, gt=0),
    unit: str = Query("u"),
    brand: str | None = Query(None),
    category: str | None = Query(None),
    total_paid: float | None = Query(None),
    paid_unit_price: float | None = Query(None),
) -> dict[str, Any]:
    """Calcula el precio de referencia en supermercados para comparar compras de barrio."""
    ref = compute_market_reference(
        product_query=product,
        quantity=quantity,
        unit=unit,
        brand=brand,
        category=category,
        total_paid=total_paid,
        paid_unit_price=paid_unit_price,
    )
    return {
        "product_query": ref.product_query,
        "quantity": ref.quantity,
        "unit": ref.unit,
        "cheapest_store": ref.cheapest_store,
        "cheapest_unit_price": ref.cheapest_unit_price,
        "cheapest_total_price": ref.cheapest_total_price,
        "cheapest_product_name": ref.cheapest_product_name,
        "cheapest_product_url": ref.cheapest_product_url,
        "average_unit_price": ref.average_unit_price,
        "average_total_price": ref.average_total_price,
        "total_matches_found": ref.total_matches_found,
        "competitor_breakdown": ref.competitor_breakdown,
        "delta_vs_paid": ref.delta_vs_paid,
    }


@v1_router.get("/favorites", tags=["Favoritos"])
def api_get_favorites(only_favorites: bool = Query(True)) -> list[dict[str, Any]]:
    """Lista de productos favoritos con precios vigentes y tendencia."""
    return get_favorites_with_live_prices(only_favorites=only_favorites)


@v1_router.post("/favorites", status_code=status.HTTP_201_CREATED, tags=["Favoritos"])
def api_add_favorite(req: FavoriteItemCreateRequest) -> dict[str, Any]:
    item = FavoriteItem(
        id=req.id.strip().lower(),
        name=req.name.strip(),
        query=req.query.strip(),
        category=req.category.strip().lower(),
        preferred_brands=[b.strip().lower() for b in req.preferred_brands],
        unit_target=req.unit_target,
        is_favorite=req.is_favorite,
        notes=req.notes.strip(),
    )
    saved = add_or_update_favorite(item)
    return {"status": "saved", "id": saved.id, "name": saved.name, "is_favorite": saved.is_favorite}


@v1_router.patch("/favorites/{item_id}/toggle", tags=["Favoritos"])
def api_toggle_favorite(item_id: str) -> dict[str, Any]:
    new_state = toggle_favorite(item_id)
    if new_state is None:
        raise HTTPException(status_code=404, detail=f"Ítem '{item_id}' no encontrado.")
    return {"id": item_id, "is_favorite": new_state}


@v1_router.delete("/favorites/{item_id}", tags=["Favoritos"])
def api_delete_favorite(item_id: str) -> dict[str, Any]:
    deleted = remove_favorite(item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Ítem '{item_id}' no encontrado.")
    return {"status": "deleted", "id": item_id}


@v1_router.post("/extract", tags=["ETL"])
async def trigger_extraction(req: ExtractRequest) -> dict[str, Any]:
    """Dispara una corrida completa del pipeline ETL paralelo con carry-forward y Gold."""
    try:
        result = await run_etl_pipeline(
            stores=req.stores,
            queries=req.queries,
            basket_type=req.basket_type,
            fmcg=req.fmcg,
            max_pages=req.pages,
            sync_to_cloud=req.sync_to_cloud,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _BUNDLE_CACHE.clear()
    return {
        "status": "success" if not result.active_silver_df.is_empty() else "empty",
        "dt": result.dt,
        "mode": result.mode,
        "silver_rows_today": len(result.silver_df),
        "active_silver_rows": len(result.active_silver_df),
        "cross_store_matches": len(result.matched_df),
        "stores_processed": result.stores_requested,
        "quality_kpis": result.quality_report.get("quality_kpis", {}),
        "metrics": [m.to_dict() for m in result.metrics],
    }


app.include_router(v1_router, prefix="/v1")


def run_server(port: int | None = None, host: str = "0.0.0.0", reload: bool = False) -> None:
    """Inicia el servidor uvicorn en el puerto dinámico resuelto."""
    resolved_port = resolve_server_port(port)
    logger.info("ChangoRadar Web App + API en http://localhost:{}", resolved_port)
    logger.info("Swagger OpenAPI Docs en http://localhost:{}/docs", resolved_port)
    uvicorn.run("scraper_precios.server:app", host=host, port=resolved_port, reload=reload)


if __name__ == "__main__":
    run_server()
