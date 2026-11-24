"""Pruebas unitarias e integración para el servidor FastAPI, PWA y endpoints `/v1`."""

from fastapi.testclient import TestClient

from scraper_precios.server import app, find_available_port, is_port_free, resolve_server_port

client = TestClient(app)


def test_root_serves_web_app_or_info():
    resp = client.get("/")
    assert resp.status_code == 200
    ct = resp.headers["content-type"]
    assert "text/html" in ct or "application/json" in ct


def test_health_and_info_endpoints():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["service"] == "scraper-precios"
    assert len(data["available_stores"]) == 6

    info_resp = client.get("/v1/info")
    assert info_resp.status_code == 200
    assert info_resp.json()["docs"] == "/docs"


def test_web_bundles_served_dynamically():
    for name in ("catalog", "analytics", "quality"):
        resp = client.get(f"/data/{name}.json")
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)


def test_search_and_cross_store_endpoints():
    resp = client.get("/v1/products/search?query=yerba&limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data and isinstance(data["results"], list)

    cs_resp = client.get("/v1/catalog/cross-store?min_stores=2&limit=5")
    assert cs_resp.status_code == 200
    assert "results" in cs_resp.json()

    cats_resp = client.get("/v1/catalog/categories")
    assert cats_resp.status_code == 200
    assert isinstance(cats_resp.json(), list)

    ref_resp = client.post("/v1/catalog/refresh-cache")
    assert ref_resp.status_code == 200
    assert ref_resp.json()["status"] == "ok"


def test_evaluate_deal_endpoint():
    payload = {
        "product_name": "Yerba Playadito 1kg",
        "store": "coto",
        "regular_price": 5000.0,
        "promo_type": "2do_al_70",
        "payment_discount_pct": 10.0,
    }
    resp = client.post("/v1/deals/evaluate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["product_name"] == "Yerba Playadito 1kg"
    assert "verdict" in data
    assert "calculation" in data


def test_assistant_and_benchmark_endpoints():
    opt_resp = client.post("/v1/assistant/optimize-list", json={"items": ["yerba", "leche"]})
    assert opt_resp.status_code == 200
    assert opt_resp.json()["total_items_requested"] == 2

    bm_resp = client.get("/v1/benchmark/reference-price?product=roast+beef&quantity=1.5&unit=kg&total_paid=9000")
    assert bm_resp.status_code == 200
    assert bm_resp.json()["quantity"] == 1.5


def test_analytics_and_quality_endpoints():
    q_resp = client.get("/v1/quality")
    assert q_resp.status_code == 200
    assert "quality_kpis" in q_resp.json()

    sql_resp = client.get("/v1/analytics/sql-report")
    assert sql_resp.status_code == 200
    assert isinstance(sql_resp.json(), dict)

    t_resp = client.get("/v1/trends/weekly?days=7")
    assert t_resp.status_code == 200
    assert "basket_weekly_inflation_pct" in t_resp.json()


def test_favorites_lifecycle_endpoints(tmp_path, monkeypatch):
    from scraper_precios import favorites as fav_mod

    monkeypatch.setattr(fav_mod, "DEFAULT_FAVORITES_PATH", tmp_path / "favorites.json")

    create_resp = client.post(
        "/v1/favorites",
        json={
            "id": "item_favorito_test",
            "name": "Producto Test",
            "query": "producto test",
            "category": "almacen",
        },
    )
    assert create_resp.status_code == 201
    assert create_resp.json()["status"] == "saved"

    toggle_resp = client.patch("/v1/favorites/item_favorito_test/toggle")
    assert toggle_resp.status_code == 200
    assert toggle_resp.json()["is_favorite"] is False

    del_resp = client.delete("/v1/favorites/item_favorito_test")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "deleted"


def test_optional_api_key_authentication(monkeypatch):
    """Por defecto es público; si se activa SCRAPER_REQUIRE_AUTH=true, valida API Key."""
    monkeypatch.setenv("SCRAPER_REQUIRE_AUTH", "true")
    monkeypatch.setenv("SCRAPER_API_KEY", "test_key_abc")

    raw_client = TestClient(app)
    assert raw_client.get("/v1/products/search?query=yerba").status_code == 401
    assert raw_client.get("/v1/products/search?query=yerba", headers={"X-API-Key": "wrong"}).status_code == 401
    assert raw_client.get("/v1/products/search?query=yerba", headers={"X-API-Key": "test_key_abc"}).status_code == 200
    assert raw_client.get("/v1/products/search?query=yerba", headers={"Authorization": "Bearer test_key_abc"}).status_code == 200
    assert raw_client.get("/health").status_code == 200


def test_extract_validates_store_names():
    resp = client.post("/v1/extract", json={"stores": ["tienda_inexistente"]})
    assert resp.status_code == 400
    assert "Ninguna tienda válida" in resp.json()["detail"]


def test_dynamic_port_resolution():
    port = resolve_server_port()
    assert isinstance(port, int) and 1024 <= port <= 65535
    assert is_port_free(port)

    free_target = find_available_port(8001)
    assert resolve_server_port(free_target) == free_target
