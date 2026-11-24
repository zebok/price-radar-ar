"""CLI principal para el Scraper de Precios y Analítica de Supermercados.

Subcomandos:
- stores      Verifica conectividad y latencia de las 6 APIs de supermercados
- extract     Ejecuta el pipeline ETL paralelo (Bronze → Silver → Gold → Data Quality)
- analyze     Analiza rápidamente el snapshot Silver local (o `--demo`)
- report      Ejecuta las consultas SQL analíticas de DuckDB y reporte de Data Quality
- query       Ejecuta una consulta SQL arbitraria o archivo `.sql` con DuckDB sobre Parquet
- export-web  Genera el bundle JSON estático en `web/data/` para GitHub Pages / PWA
- basket      Visualiza o exporta la canasta de referencia
- serve       Inicia la Web App + API FastAPI en local (soporta `--demo`)
- stop        Detiene instancias locales del servidor
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

import polars as pl
from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from .analytics.duckdb_runner import run_executive_report, run_sql_file, run_sql_query
from .baskets import get_basket_items, save_basket_to_file
from .config import Settings, parse_store_selection
from .extractors import ExtractorMetrics, get_extractor, list_available_stores
from .pipeline import (
    compute_store_competitiveness,
    get_top_discounts,
    load_latest_quality_report,
    match_products_cross_store,
    run_etl_pipeline,
)
from .pipeline.export_web import export_web_bundle
from .storage import load_active_silver_with_freshness
from .taxonomy import CANONICAL_CATEGORIES

console = Console()


def _resolve_data_dir(args: argparse.Namespace) -> Path:
    settings = Settings()
    if getattr(args, "demo", False):
        return settings.demo_data_dir
    raw = getattr(args, "data_dir", None) or getattr(args, "output_dir", None)
    return Path(raw) if raw else settings.data_dir


# ──────────────────────────────────────────────────────────────
#  Comando: STORES (Health Check)
# ──────────────────────────────────────────────────────────────
async def handle_stores_command() -> None:
    """Verifica la salud y estado de todas las tiendas configuradas."""
    table = Table(
        title="Estado de APIs de Supermercados",
        show_lines=True,
        header_style="bold cyan",
    )
    table.add_column("Key", style="bold yellow", width=12)
    table.add_column("Supermercado", style="white", width=18)
    table.add_column("Dominio / Base URL", style="dim", width=34)
    table.add_column("Estado API", justify="center", width=14)
    table.add_column("Latencia", justify="right", width=12)

    available = list_available_stores()
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Comprobando APIs de supermercados...", total=len(available))

        for key in available:
            extractor = get_extractor(key)
            start_t = time.time()
            is_healthy = False
            latency_ms = 0.0

            try:
                async with extractor:
                    is_healthy = await extractor.health_check()
                latency_ms = round((time.time() - start_t) * 1000, 1)
            except Exception as e:
                logger.debug("Health check failed for {}: {}", key, e)

            status_str = "[bold green]ACTIVA[/bold green]" if is_healthy else "[bold red]CAÍDA[/bold red]"
            latency_str = f"{latency_ms} ms" if is_healthy else "-"

            table.add_row(key, extractor.display_name, extractor.origin_url, status_str, latency_str)
            progress.advance(task)

    console.print()
    console.print(table)
    console.print()


# ──────────────────────────────────────────────────────────────
#  Comando: EXTRACT
# ──────────────────────────────────────────────────────────────
async def handle_extract_command(args: argparse.Namespace) -> None:
    """Ejecuta el pipeline ETL paralelo end-to-end."""
    settings = Settings()
    output_dir = Path(args.output_dir or settings.data_dir)
    available = list_available_stores()
    selected_stores, invalid_stores = parse_store_selection(args.stores, available)

    if invalid_stores:
        console.print(
            f"[bold red]Tiendas no reconocidas: {invalid_stores}. Opciones válidas: {available}[/bold red]"
        )
        return
    if not selected_stores:
        console.print(f"[bold red]Debés seleccionar al menos una tienda. Opciones: {available}[/bold red]")
        return

    is_fmcg = bool(getattr(args, "fmcg", False) or getattr(args, "category", None))
    mode_desc = (
        f"Categorías FMCG ({', '.join(args.category) if args.category else len(CANONICAL_CATEGORIES)})"
        if is_fmcg
        else (f"Búsquedas puntuales ({len(args.query)})" if args.query else f"Canasta {(args.basket or settings.basket_type).upper()}")
    )

    console.print(
        Panel(
            f"[bold cyan]Pipeline ETL Paralelo — Medallion Lakehouse[/bold cyan]\n\n"
            f"• [bold]Tiendas:[/bold] {', '.join(s.upper() for s in selected_stores)}\n"
            f"• [bold]Modo:[/bold] {mode_desc}\n"
            f"• [bold]Páginas máx.:[/bold] {args.pages} {'(exhaustivo)' if args.pages == 0 else ''}\n"
            f"• [bold]Destino:[/bold] {output_dir}",
            border_style="cyan",
        )
    )

    sync_cloud = bool(getattr(args, "sync_cloud", False) or os.getenv("GCS_BUCKET_NAME"))
    result = await run_etl_pipeline(
        stores=selected_stores,
        queries=args.query,
        basket_type=args.basket,
        fmcg=bool(args.fmcg),
        categories=args.category,
        max_pages=args.pages,
        output_dir=output_dir,
        sync_to_cloud=sync_cloud,
        settings=settings,
    )

    if result.active_silver_df.is_empty():
        console.print("[bold red]No se obtuvieron registros ni snapshots previos disponibles.[/bold red]")
        return

    render_extraction_summary(result.metrics, result.active_silver_df, result.matched_df, result.quality_report)

    if getattr(args, "export_web", False):
        web_dir = Path(getattr(args, "web_dir", None) or settings.web_dir)
        paths = export_web_bundle(output_dir, web_dir)
        console.print(f"[bold green]Bundle estático actualizado en {web_dir / 'data'} ({len(paths)} archivos).[/bold green]")


# ──────────────────────────────────────────────────────────────
#  Comando: ANALYZE
# ──────────────────────────────────────────────────────────────
def handle_analyze_command(args: argparse.Namespace) -> None:
    """Inspecciona y analiza el snapshot Silver activo (o `--demo`)."""
    data_dir = _resolve_data_dir(args)
    df, freshness = load_active_silver_with_freshness(data_dir)

    if df.is_empty():
        console.print(
            f"[bold red]No se encontraron datos en {data_dir / 'silver'}. "
            f"Ejecutá 'uv run scraper extract' o probá 'uv run scraper analyze --demo'.[/bold red]"
        )
        return

    fresh_parts = []
    for k, v in sorted(freshness.items()):
        age = v["age_days"]
        suffix = "" if age == 0 else f" · -{age}d"
        fresh_parts.append(f"{k.upper()} ({v['last_dt']}{suffix})")
    fresh_str = ", ".join(fresh_parts)
    console.print(
        Panel(
            f"[bold green]Análisis de Catálogo Activo (Silver + Carry-Forward)[/bold green]\n"
            f"Registros activos: [bold]{len(df):,}[/bold] | Tiendas: {fresh_str}",
            border_style="green",
        )
    )

    if args.query:
        q = args.query.lower().strip()
        df = df.filter(pl.col("name_clean").str.contains(q, literal=True))
        console.print(f"[dim]Filtrando por: '{q}' ({len(df)} coincidencias)[/dim]\n")

    render_competitiveness_table(compute_store_competitiveness(df))

    matched = match_products_cross_store(df)
    if not matched.is_empty():
        render_cross_store_table(matched.head(15))

    top_deals = get_top_discounts(df, min_discount_pct=15.0, limit=15)
    if not top_deals.is_empty():
        render_top_deals_table(top_deals)


# ──────────────────────────────────────────────────────────────
#  Comandos: REPORT y QUERY (DuckDB SQL)
# ──────────────────────────────────────────────────────────────
def _render_generic_rows(title: str, rows: list[dict[str, Any]], max_rows: int = 15) -> None:
    if not rows:
        console.print(f"[dim]{title}: sin filas para mostrar.[/dim]\n")
        return

    cols = list(rows[0].keys())
    table = Table(title=title, show_lines=False, header_style="bold cyan")
    for c in cols:
        table.add_column(c, overflow="fold")

    for r in rows[:max_rows]:
        table.add_row(*["" if r.get(c) is None else str(r.get(c))[:48] for c in cols])

    console.print(table)
    console.print()


def handle_report_command(args: argparse.Namespace) -> None:
    """Ejecuta el reporte analítico DuckDB SQL + métricas de Data Quality."""
    data_dir = _resolve_data_dir(args)
    quality = load_latest_quality_report(data_dir)
    kpis = quality.get("quality_kpis", {})
    funnel = quality.get("funnel", {})

    console.print(
        Panel(
            f"[bold cyan]Reporte Ejecutivo BI & Data Quality (DuckDB sobre Parquet)[/bold cyan]\n\n"
            f"• [bold]Dataset:[/bold] {data_dir}\n"
            f"• [bold]Registros activos Silver:[/bold] {funnel.get('active_silver_rows', 0):,}\n"
            f"• [bold]Cobertura EAN válido:[/bold] {kpis.get('ean_coverage_pct', 0.0)}% "
            f"| [bold]Match Cross-Store:[/bold] {kpis.get('cross_store_match_rate_pct', 0.0)}% "
            f"({funnel.get('gold_cross_store_eans', 0):,} EANs compartidos)\n"
            f"• [bold]Tiendas activas:[/bold] {kpis.get('stores_total', 0)} "
            f"(carry-forward: {', '.join(kpis.get('carried_forward_stores', [])) or 'ninguna'})",
            border_style="cyan",
        )
    )

    results = run_executive_report(data_dir)
    titles = {
        "01_basket_inflation": "01. Evolución Diaria de Canasta e Inflación (DuckDB)",
        "02_store_competitiveness": "02. Competitividad e Índice Relativo vs Mediana (DuckDB)",
        "03_cazabobos_audit": "03. Auditoría de Promociones Caza-bobos (DuckDB)",
        "04_unit_price_leaders": "04. Líderes de Precio Unitario $/kg y $/L (DuckDB)",
    }
    for key, rows in results.items():
        _render_generic_rows(titles.get(key, key), rows, max_rows=args.limit)


def handle_query_command(args: argparse.Namespace) -> None:
    """Ejecuta un archivo `.sql` o consulta SQL directa con DuckDB sobre el Lakehouse."""
    data_dir = _resolve_data_dir(args)
    target = args.sql
    p = Path(target)
    if p.exists() and p.is_file():
        rows = run_sql_file(p, data_dir)
        title = f"DuckDB SQL: {p.name}"
    else:
        rows = run_sql_query(target, data_dir)
        title = "DuckDB SQL Query"
    _render_generic_rows(title, rows, max_rows=args.limit)


# ──────────────────────────────────────────────────────────────
#  Comando: EXPORT-WEB
# ──────────────────────────────────────────────────────────────
def handle_export_web_command(args: argparse.Namespace) -> None:
    """Exporta los bundles JSON compactos para la PWA estática (GitHub Pages)."""
    settings = Settings()
    data_dir = _resolve_data_dir(args)
    web_dir = Path(args.web_dir or settings.web_dir)
    paths = export_web_bundle(data_dir, web_dir, max_items=args.max_items)
    for name, path in paths.items():
        size_kb = path.stat().st_size / 1024
        console.print(f"[green]✔ {name}.json[/green] → {path} ([bold]{size_kb:.1f} KB[/bold])")


# ──────────────────────────────────────────────────────────────
#  Renderizadores Rich
# ──────────────────────────────────────────────────────────────
def render_extraction_summary(
    metrics_list: list[ExtractorMetrics],
    silver_df: pl.DataFrame,
    matched_df: pl.DataFrame,
    quality_report: dict[str, Any] | None = None,
) -> None:
    console.print()
    op_table = Table(
        title="Observabilidad y Métricas Operacionales",
        show_lines=True,
        header_style="bold blue",
    )
    op_table.add_column("Supermercado", style="bold magenta", width=14)
    op_table.add_column("Estado", justify="center", width=14)
    op_table.add_column("HTTP OK", justify="right", width=12)
    op_table.add_column("Latencia", justify="right", width=11)
    op_table.add_column("Duración", justify="right", width=10)
    op_table.add_column("Registros", justify="right", width=11)

    for m in metrics_list:
        op_table.add_row(
            m.store_name,
            m.status.upper(),
            f"{m.requests_success}/{m.requests_total}",
            f"{m.avg_latency_ms} ms",
            f"{m.duration_seconds}s",
            f"{m.records_extracted}",
        )
    console.print(op_table)
    console.print()

    if quality_report:
        kpis = quality_report.get("quality_kpis", {})
        console.print(
            f"[dim]Data Quality → Cobertura EAN: {kpis.get('ean_coverage_pct', 0)}% | "
            f"Match cross-store: {kpis.get('cross_store_match_rate_pct', 0)}% | "
            f"Carry-forward: {kpis.get('carried_forward_stores') or 'ninguno'}[/dim]\n"
        )

    top_deals = get_top_discounts(silver_df, min_discount_pct=10.0, limit=10)
    if not top_deals.is_empty():
        render_top_deals_table(top_deals)
    if not matched_df.is_empty():
        render_cross_store_table(matched_df.head(10))


def render_top_deals_table(deals_df: pl.DataFrame) -> None:
    table = Table(title="Mejores Descuentos Verificados", show_lines=True, header_style="bold yellow")
    table.add_column("Tienda", style="bold magenta", width=10)
    table.add_column("Producto", style="white", max_width=40)
    table.add_column("Precio Actual", style="bold green", justify="right", width=13)
    table.add_column("Precio Lista", style="dim", justify="right", width=13)
    table.add_column("Descuento", style="bold red", justify="right", width=11)

    disc_col = "verified_discount_pct" if "verified_discount_pct" in deals_df.columns else "discount_pct"
    for row in deals_df.iter_rows(named=True):
        table.add_row(
            row.get("store", "?").upper(),
            str(row.get("name", "?"))[:40],
            f"${row['price']:,.2f}",
            f"${row['list_price']:,.2f}" if row.get("list_price") else "-",
            f"{(row.get(disc_col) or 0.0):.1f}%",
        )
    console.print(table)
    console.print()


def render_cross_store_table(matched_df: pl.DataFrame) -> None:
    table = Table(title="Comparativa Cross-Store (Mismo EAN)", show_lines=True, header_style="bold cyan")
    table.add_column("EAN", style="dim", width=14)
    table.add_column("Producto", style="white", max_width=35)
    table.add_column("Tiendas", justify="center", width=8)
    table.add_column("Más Barato", style="bold green", width=12)
    table.add_column("Min $", style="bold green", justify="right", width=11)
    table.add_column("Más Caro", style="bold red", width=12)
    table.add_column("Max $", style="bold red", justify="right", width=11)
    table.add_column("Brecha %", style="bold yellow", justify="right", width=10)

    for row in matched_df.iter_rows(named=True):
        table.add_row(
            str(row.get("ean_clean", "-")),
            str(row.get("product_name", "?"))[:35],
            str(row.get("stores_count", 0)),
            str(row.get("cheapest_store", "?")).upper(),
            f"${row.get('min_price', 0):,.2f}",
            str(row.get("most_expensive_store", "?")).upper(),
            f"${row.get('max_price', 0):,.2f}",
            f"{row.get('savings_spread_pct', 0):.1f}%",
        )
    console.print(table)
    console.print()


def render_competitiveness_table(comp_df: pl.DataFrame) -> None:
    table = Table(title="Índice de Competitividad por Supermercado", show_lines=True, header_style="bold purple")
    table.add_column("Tienda", style="bold magenta", width=14)
    table.add_column("Catálogo", justify="right", width=12)
    table.add_column("En Stock", justify="right", width=12)
    table.add_column("Precio Promedio", justify="right", width=16)
    table.add_column("Veces más barata", justify="right", style="bold green", width=18)

    for row in comp_df.iter_rows(named=True):
        table.add_row(
            row["store"].upper(),
            str(row["total_catalog_products"]),
            str(row["in_stock_products"]),
            f"${row['avg_catalog_price']:,.2f}",
            str(row["times_cheapest"]),
        )
    console.print(table)
    console.print()


# ──────────────────────────────────────────────────────────────
#  Comando: BASKET
# ──────────────────────────────────────────────────────────────
def handle_basket_command(args: argparse.Namespace) -> None:
    if args.action == "list":
        items = get_basket_items(basket_type=args.type)
        table = Table(title=f"Canasta de Referencia ({args.type.upper()} - {len(items)} ítems)", show_lines=True)
        table.add_column("Categoría", style="bold magenta", width=16)
        table.add_column("Producto", style="bold white", width=26)
        table.add_column("Query", style="yellow", width=22)
        table.add_column("Unidad", justify="center", width=8)
        table.add_column("Core", justify="center", width=6)
        for it in items:
            table.add_row(it.category.upper(), it.name, it.query, it.unit_measure_target, "✔" if it.is_core else "·")
        console.print(table)
    elif args.action == "export":
        target = Path(args.path)
        items = get_basket_items(basket_type="extended")
        save_basket_to_file(items, target)
        console.print(f"[bold green]Canasta exportada a {target} ({len(items)} ítems).[/bold green]")


# ──────────────────────────────────────────────────────────────
#  Comandos: SERVE y STOP
# ──────────────────────────────────────────────────────────────
def handle_serve_command(args: argparse.Namespace) -> None:
    if getattr(args, "demo", False):
        settings = Settings()
        os.environ["SCRAPER_DATA_DIR"] = str(settings.demo_data_dir)
        console.print(f"[bold cyan]Iniciando en MODO DEMO usando {settings.demo_data_dir}[/bold cyan]")

    from .server import run_server

    port = getattr(args, "port", None)
    run_server(port=port if port and port > 0 else None, host=args.host, reload=args.reload)


def handle_stop_command(args: argparse.Namespace) -> None:
    target_port = getattr(args, "port", None)
    stopped_pids: list[int] = []

    if target_port:
        try:
            out = subprocess.check_output(["lsof", "-ti", f":{target_port}"], text=True).strip()
            for pid in [int(p) for p in out.split() if p.isdigit()]:
                if pid != os.getpid():
                    try:
                        os.kill(pid, signal.SIGTERM)
                        stopped_pids.append(pid)
                    except ProcessLookupError:
                        pass
        except Exception:
            pass
    else:
        current_pid = os.getpid()
        try:
            out = subprocess.check_output(["ps", "-eo", "pid,command"], text=True)
            for line in out.splitlines():
                parts = line.strip().split(None, 1)
                if len(parts) < 2 or not parts[0].isdigit():
                    continue
                pid = int(parts[0])
                cmd = parts[1]
                if pid == current_pid or "python -c" in cmd or "stop" in cmd:
                    continue
                if "scraper_precios.server" in cmd or "scraper-server" in cmd or ("scraper" in cmd and "serve" in cmd):
                    try:
                        os.kill(pid, signal.SIGTERM)
                        stopped_pids.append(pid)
                    except ProcessLookupError:
                        pass
        except Exception as e:
            logger.debug("Error buscando procesos del server: {}", e)

    if stopped_pids:
        console.print(f"[bold green]Servidores detenidos (PIDs: {stopped_pids}).[/bold green]")
    else:
        console.print("[yellow]No hay servidores locales de scraper-precios activos.[/yellow]")


# ──────────────────────────────────────────────────────────────
#  Entry Point CLI
# ──────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        prog="scraper",
        description="ETL Medallion, Analítica DuckDB y Comparador Web de Precios de Supermercados",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("stores", help="Verifica conectividad y latencia de las 6 APIs")

    # extract
    extract_p = subparsers.add_parser("extract", help="Ejecuta el pipeline ETL paralelo")
    extract_p.add_argument("--stores", nargs="+", default=["all"], help="Tiendas (espacio o coma) o 'all'")
    extract_p.add_argument("--basket", choices=["core", "extended"], default=None)
    extract_p.add_argument("--query", nargs="+", help="Términos puntuales de búsqueda")
    extract_p.add_argument("--pages", type=int, default=1, help="Páginas por búsqueda/categoría (0 = exhaustivo)")
    extract_p.add_argument("--output-dir", type=str, default=None)
    extract_p.add_argument("--sync-cloud", action="store_true")
    extract_p.add_argument("--fmcg", action="store_true", help="Extraer catálogo por árbol de categorías FMCG")
    extract_p.add_argument("--category", "--categories", nargs="+")
    extract_p.add_argument("--export-web", action="store_true", help="Generar también el bundle JSON estático en web/data/")
    extract_p.add_argument("--web-dir", type=str, default=None)

    # analyze
    analyze_p = subparsers.add_parser("analyze", help="Analiza el snapshot Silver activo")
    analyze_p.add_argument("--query", type=str)
    analyze_p.add_argument("--data-dir", type=str, default=None)
    analyze_p.add_argument("--demo", action="store_true", help="Usar el dataset demo incluido en data/demo")

    # report
    report_p = subparsers.add_parser("report", help="Ejecuta el reporte ejecutivo DuckDB SQL + Data Quality")
    report_p.add_argument("--data-dir", type=str, default=None)
    report_p.add_argument("--demo", action="store_true", help="Usar el dataset demo incluido")
    report_p.add_argument("--limit", type=int, default=12)

    # query
    query_p = subparsers.add_parser("query", help="Ejecuta una consulta SQL o archivo .sql con DuckDB")
    query_p.add_argument("sql", help="Ruta a archivo .sql (ej: sql/02_store_competitiveness.sql) o SQL directo")
    query_p.add_argument("--data-dir", type=str, default=None)
    query_p.add_argument("--demo", action="store_true")
    query_p.add_argument("--limit", type=int, default=25)

    # export-web
    export_p = subparsers.add_parser("export-web", help="Genera los JSON estáticos para la PWA / GitHub Pages")
    export_p.add_argument("--data-dir", type=str, default=None)
    export_p.add_argument("--web-dir", type=str, default=None)
    export_p.add_argument("--demo", action="store_true")
    export_p.add_argument("--max-items", type=int, default=8000)

    # basket
    basket_p = subparsers.add_parser("basket", help="Lista o exporta la canasta de referencia")
    basket_sub = basket_p.add_subparsers(dest="action", required=True)
    list_p = basket_sub.add_parser("list")
    list_p.add_argument("--type", choices=["core", "extended"], default="core")
    exp_p = basket_sub.add_parser("export")
    exp_p.add_argument("--path", default="data/basket_config.json")

    # serve
    serve_p = subparsers.add_parser("serve", help="Inicia la Web App (PWA) + API REST local")
    serve_p.add_argument("-p", "--port", type=int, default=0)
    serve_p.add_argument("--host", type=str, default="0.0.0.0")
    serve_p.add_argument("--reload", action="store_true")
    serve_p.add_argument("--demo", action="store_true", help="Servir el dataset demo incluido")

    # stop
    stop_p = subparsers.add_parser("stop", help="Detiene servidores locales activos")
    stop_p.add_argument("-p", "--port", type=int, default=None)

    args = parser.parse_args()

    if args.command == "stores":
        asyncio.run(handle_stores_command())
    elif args.command == "extract":
        asyncio.run(handle_extract_command(args))
    elif args.command == "analyze":
        handle_analyze_command(args)
    elif args.command == "report":
        handle_report_command(args)
    elif args.command == "query":
        handle_query_command(args)
    elif args.command == "export-web":
        handle_export_web_command(args)
    elif args.command == "basket":
        handle_basket_command(args)
    elif args.command == "serve":
        handle_serve_command(args)
    elif args.command == "stop":
        handle_stop_command(args)


if __name__ == "__main__":
    main()
