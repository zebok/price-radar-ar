"""Diagnóstico de conectividad e IP pública para los 6 supermercados soportados.

Permite verificar rápidamente desde una compu local, Docker, GitHub Actions o Cloud Run
si la IP emisora puede consultar las APIs de VTEX y Constructor.io sin bloqueos WAF.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

ENDPOINTS = {
    "Carrefour (VTEX)": {
        "url": "https://www.carrefour.com.ar/api/io/_v/api/intelligent-search/product_search/?query=yerba&page=1&count=1",
        "origin": "https://www.carrefour.com.ar",
    },
    "Jumbo (VTEX)": {
        "url": "https://www.jumbo.com.ar/api/io/_v/api/intelligent-search/product_search/?query=yerba&page=1&count=1",
        "origin": "https://www.jumbo.com.ar",
    },
    "Disco (VTEX)": {
        "url": "https://www.disco.com.ar/api/io/_v/api/intelligent-search/product_search/?query=yerba&page=1&count=1",
        "origin": "https://www.disco.com.ar",
    },
    "Vea (VTEX)": {
        "url": "https://www.vea.com.ar/api/io/_v/api/intelligent-search/product_search/?query=yerba&page=1&count=1",
        "origin": "https://www.vea.com.ar",
    },
    "Dia Online (VTEX)": {
        "url": "https://diaonline.supermercadosdia.com.ar/api/io/_v/api/intelligent-search/product_search/?query=yerba&page=1&count=1",
        "origin": "https://diaonline.supermercadosdia.com.ar",
    },
    "Coto (Constructor.io)": {
        "url": "https://ac.cnstrc.com/search/yerba?key=key_r6xzz4IAoTWcipni&i=client-ses-coto-1&s=1&page=1&num_results_per_page=1",
        "origin": "https://www.cotodigital3.com.ar",
    },
}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def get_ip_info() -> dict[str, str]:
    try:
        req = urllib.request.Request("https://ipinfo.io/json", headers={"User-Agent": "curl/8.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {
                "ip": data.get("ip", "Desconocida"),
                "org": data.get("org", "Desconocido"),
                "city": data.get("city", "-"),
                "country": data.get("country", "-"),
            }
    except Exception as e:
        return {"ip": "Error", "org": str(e), "city": "-", "country": "-"}


def check_endpoint(name: str, config: dict[str, str]) -> dict[str, str | int | float]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
        "Origin": config["origin"],
        "Referer": f"{config['origin']}/",
    }
    req = urllib.request.Request(config["url"], headers=headers)
    start_time = time.time()

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            elapsed_ms = round((time.time() - start_time) * 1000, 1)
            resp.read()
            return {"name": name, "status": resp.status, "latency_ms": elapsed_ms, "result": "ACTIVA (200 OK)"}
    except urllib.error.HTTPError as e:
        elapsed_ms = round((time.time() - start_time) * 1000, 1)
        reason = "403 FORBIDDEN (WAF/IP)" if e.code == 403 else f"HTTP {e.code}"
        return {"name": name, "status": e.code, "latency_ms": elapsed_ms, "result": reason}
    except Exception as e:
        elapsed_ms = round((time.time() - start_time) * 1000, 1)
        return {"name": name, "status": 0, "latency_ms": elapsed_ms, "result": f"ERROR ({type(e).__name__})"}


def main() -> None:
    print("=" * 72)
    print(" Diagnóstico de Conectividad e IP: 6 Supermercados de Argentina")
    print("=" * 72)

    ip_info = get_ip_info()
    print(f" • IP Pública  : {ip_info['ip']} ({ip_info['city']}, {ip_info['country']})")
    print(f" • ISP / ASN   : {ip_info['org']}")
    print("-" * 72)
    print(f"{'Supermercado':<24} | {'Estado':<28} | {'Latencia':<10}")
    print("-" * 72)

    ok_count = 0
    for name, cfg in ENDPOINTS.items():
        res = check_endpoint(name, cfg)
        if "200 OK" in str(res["result"]):
            ok_count += 1
        print(f"{name:<24} | {str(res['result']):<28} | {res['latency_ms']} ms")
        time.sleep(0.3)

    print("=" * 72)
    print(f" Resultado: {ok_count}/{len(ENDPOINTS)} supermercados alcanzables desde esta IP.")
    print("=" * 72)


if __name__ == "__main__":
    main()
