# Modelo de Datos (Medallion Lakehouse) y Reglas de Calidad

Todos los datasets se almacenan en formato **Apache Parquet** con compresión **ZSTD** y particionamiento estilo **Hive** (`dt=YYYY-MM-DD`), directamente consultables con **Polars** o **DuckDB**.

```text
data/scraper-precios/
├── bronze/dt=YYYY-MM-DD/store={store}/data.parquet
├── silver/dt=YYYY-MM-DD/products.parquet
├── gold/dt=YYYY-MM-DD/
│   ├── cross_store_comparison.parquet
│   ├── store_competitiveness.parquet
│   ├── daily_basket_index.parquet
│   └── price_changes.parquet
└── metrics/
    ├── latest_run.json
    └── run_history.parquet
```

---

## 1. Capa Bronze (`bronze/dt=YYYY-MM-DD/store={store}/data.parquet`)

Captura fiel de los registros parseados por cada extractor (`ProductRecord` en Pydantic v2), sin transformaciones destructivas:

| Columna | Tipo | Descripción |
| :--- | :--- | :--- |
| `store` | `Utf8` | Clave de cadena (`carrefour`, `coto`, `dia`, `jumbo`, `disco`, `vea`). |
| `product_id`, `sku_id` | `Utf8` | Identificadores nativos en la plataforma origen. |
| `ean` | `Utf8` | Código de barras crudo (EAN-13 / EAN-8 cuando existe). |
| `name`, `brand`, `sku_name` | `Utf8` | Descripción comercial, marca y variante. |
| `category` | `Utf8` | Categoría reportada por la tienda (o grupo de navegación en Coto). |
| `price`, `list_price` | `Float64` | Precio actual de venta por 1 unidad y precio regular anterior en ARS (en Cencosud se normaliza `ListPrice` Ley 27.743 sin IVA y se enriquecen descuentos reales vía GraphQL `enrichPromotions`). |
| `promo_label` | `Utf8` | Etiqueta de promoción condicional multi-unidad (`2do al 70%`, `2do al 50%`, `3x2`, `6x5`) sin distorsionar el precio unitario. |
| `available`, `available_quantity` | `Boolean` / `Int64` | Disponibilidad de stock al momento de la extracción. |
| `product_url`, `image_url` | `Utf8` | Enlace directo canónico al producto e imagen. |
| `scraped_at` | `Datetime(UTC)` | Timestamp exacto de captura. |

---

## 2. Capa Silver (`silver/dt=YYYY-MM-DD/products.parquet`)

Datos limpios, deduplicados y enriquecidos por [`pipeline/cleaning.py`](../src/scraper_precios/pipeline/cleaning.py):

### Reglas de Data Quality (Gates Técnicos)

| # | Regla | Criterio | Objetivo |
| :-: | :--- | :--- | :--- |
| **1** | **Stock Gate** | `available == True` y `available_quantity > 0` | Evitar precios congelados de productos discontinuados. |
| **2** | **Price Sanity Band** | `50.0 <= price <= 500_000.0` ARS | Descartar errores de tipeo de millones o centavos históricos. |
| **3** | **Non-Retail Gate** | Regex sobre `tester`, `muestra gratis`, `dummy`, `gift card`, nombre vacío | Mantener solo productos comerciales reales. |
| **4** | **Dummy EAN Gate** | Anula EANs ficticios (`0000000000000`, `1111111111111`, etc.) o fuera de 8–14 dígitos | Garantizar integridad del join cross-store por EAN. |
| **5** | **Promo Gate** | `verified_discount_pct <= 75.0%` | Anular falsos descuentos producto de `list_price` corruptos en centavos. |
| **6** | **Spread Gate (Gold)** | `max_price / min_price <= 4.0` | Descartar emparejamientos espurios (sachet individual vs. caja cerrada con mismo EAN). |

### Columnas Enriquecidas en Silver

| Columna | Tipo | Descripción |
| :--- | :--- | :--- |
| `name_clean`, `brand_clean`, `ean_clean` | `Utf8` | Campos normalizados para búsqueda y matching exacto. |
| `macro_category` | `Utf8` | Taxonomía unificada (`almacen`, `desayuno`, `lacteos`, `bebidas`, `carnes`, `verduleria`, `congelados`, `limpieza`, `perfumeria`, `otros`). |
| `weight_kg`, `volume_liters`, `pack_units` | `Float64` / `Int64` | Cantidades extraídas por regex contemplando multipacks explícitos (`6x473ml`, `Pack x 6 1 L`). |
| `unit_price_std`, `unit_measure` | `Float64` / `Utf8` | Precio unitario normalizado (`$/kg`, `$/L`, `$/u`, `$/item`). |
| `verified_discount_pct` | `Float64` | Porcentaje de descuento real validado contra el Promo Gate. |
| `dt` | `Date` | Partición diaria ISO (`YYYY-MM-DD`). |

---

## 3. Capa Gold (`gold/dt=YYYY-MM-DD/*.parquet`)

| Tabla | Granularidad | Propósito Analítico |
| :--- | :--- | :--- |
| `cross_store_comparison` | 1 fila por `ean_clean` (≥2 tiendas) | Tienda más barata, más cara, precio mínimo/máximo/promedio y `savings_spread_pct`. |
| `store_competitiveness` | 1 fila por `store` | Tamaño de catálogo, `times_cheapest`, `win_rate_pct`, precio mediano, ofertas ≥15% y cobertura EAN. |
| `daily_basket_index` | 1 fila por `(dt, store)` + `split_optimal` | Serie histórica del costo de canasta básica por cadena y estrategia de compra partida. |
| `price_changes` | 1 fila por `(store, product_id)` presente en ≥2 fechas | Variación en `$` y `%` (`subio` / `bajo` / `estable`) entre inicio y fin del período. |

---

## 4. Observabilidad (`metrics/`)

- `metrics/latest_run.json`: embudo completo de la última corrida (`candidates_seen` → `extractor_rejections` → `bronze_rows` → `silver_cleaning_drops` → `active_silver_rows` → `gold_cross_store_eans`), KPIs de cobertura EAN / match rate y estado de cada supermercado (`ok`, `degraded`, `circuit_open`, `carried_forward`).
- `metrics/run_history.parquet`: bitácora tabular histórica (hasta 365 corridas) para auditar tendencias de salud del pipeline.
