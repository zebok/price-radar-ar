# Arquitectura Técnica y Resiliencia

Este documento detalla las decisiones de arquitectura del pipeline ETL, las garantías de degradación controlada ante fallos externos y las opciones de despliegue portable (Local, GitHub Pages y GCP con Terraform).

---

## 1. Extractores Multi-Fuente (`src/scraper_precios/extractors/`)

El patrón `BaseExtractor` desacopla la lógica HTTP y de resiliencia de las particularidades de cada cadena:

- **Cliente asíncrono HTTP/2 (`httpx.AsyncClient`)** con pool de conexiones *keep-alive*.
- **Rate limiting por supermercado:** semáforo de concurrencia + delay configurable entre requests + rotación de *User-Agents*.
- **Reintentos con backoff exponencial y jitter (`tenacity`)** únicamente sobre errores transitorios (`429`, `5xx`, timeouts).
- **Circuit Breaker por tienda (`CircuitOpenError`):** si una cadena acumula `N` fallos consecutivos (default `3`, ej. bloqueo WAF `403` o caída `503`), el circuito se abre, corta inmediatamente esa tienda y permite que el resto de las cadenas terminen sin demoras.
- **Adaptadores especializados:**
  - `VTEXExtractor` (Carrefour, Jumbo, Disco, Vea, Dia): soporta búsqueda paginada (`Intelligent Search`) y recorrido de catálogo por categoría (`catalog_system`), incluyendo la corrección de anomalía de Cencosud (`ListPrice` reportado en centavos).
  - `CotoExtractor` (Coto Digital vía `Constructor.io`): soporta búsqueda y navegación por `group_id`, normalización de URLs canónicas y extracción de categorías desde `groups`/`facets` con fallback por grupo.

Para sumar una nueva cadena VTEX alcanza con agregar una entrada en `STORES` ([`config.py`](../src/scraper_precios/config.py)); para otra plataforma se hereda de `BaseExtractor` y se registra en `registry.py`.

---

## 2. Orquestación Paralela y Carry-Forward (`pipeline/runner.py` & `storage/parquet.py`)

Todas las tiendas seleccionadas se ejecutan en paralelo con `asyncio.gather(..., return_exceptions=True)`:

1. **Bronze:** se persisten los registros crudos por fecha y tienda (`bronze/dt=YYYY-MM-DD/store={store}/data.parquet`) en formato Parquet con compresión ZSTD.
2. **Silver:** `clean_and_enrich_with_report()` aplica los 5 *Data Quality Gates* técnicos, deduplica, extrae unidades/multipacks (`$/kg`, `$/L`, `$/u`), clasifica `macro_category` y guarda `silver/dt=YYYY-MM-DD/products.parquet`.
3. **Carry-Forward (*Last-Known-Good*):** `load_active_silver_with_freshness()` construye el catálogo activo tomando la partición más reciente disponible de cada cadena (ventana configurable hasta 7 días). Si hoy Coto o Dia fallan, sus precios del día anterior siguen operativos con trazabilidad (`status: "carried_forward"`, `age_days: 1`).
4. **Gold:** `build_and_save_gold_marts()` materializa las 4 tablas analíticas (`cross_store_comparison`, `store_competitiveness`, `daily_basket_index`, `price_changes`).
5. **Observabilidad:** `save_quality_report()` guarda `metrics/latest_run.json` y anexa un registro histórico en `metrics/run_history.parquet`.

---

## 3. Modos de Operación (Portabilidad Total)

### Modo A — Estático + GitHub Pages (`$0`, recomendado para uso diario)
- El workflow [`.github/workflows/daily-etl.yml`](../.github/workflows/daily-etl.yml) ejecuta el ETL diario, preserva snapshots Silver históricos vía `actions/cache`, genera `web/data/*.json` y publica `web/` en GitHub Pages.
- El Service Worker (`web/sw.js`) cachea tanto la interfaz como el último snapshot JSON, permitiendo consultar precios incluso sin señal dentro del supermercado.

### Modo B — Local / Docker (FastAPI + PWA)
- `uv run scraper serve` (o `docker build -t scraper-precios . && docker run -p 8080:8080 scraper-precios`) sirve la misma PWA en `/` generando `/data/*.json` al vuelo desde el Lakehouse Parquet activo (con caché automática invalidada por `mtime`), además de exponer la API REST `/v1/*` y Swagger en `/docs`.

### Modo C — Infraestructura como Código en GCP (`terraform/`)
El directorio [`terraform/`](../terraform/) declara de forma reproducible los recursos necesarios para correr el ETL en Google Cloud Platform dentro del Always Free Tier:

- `storage.tf`: bucket Lakehouse GCS con *Uniform Bucket-Level Access* y regla de ciclo de vida de 365 días.
- `cloud_run.tf`: Cloud Run Job batch (`scraper extract --stores all --basket extended --sync-cloud`).
- `scheduler.tf`: Cloud Scheduler cron diario (`0 6 * * *`, `America/Argentina/Buenos_Aires`) autenticado por OAuth Service Account.
- `iam.tf`: Service Account dedicada con principio de menor privilegio (`roles/storage.objectAdmin` únicamente sobre el bucket y `roles/run.invoker`).

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Completar project_id, bucket_name e image_name en terraform.tfvars
terraform init
terraform plan
terraform apply
```
