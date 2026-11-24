#!/usr/bin/env bash
# ==============================================================================
# Actualización Local en 1 Comando (Plan B ante bloqueos de IP en la nube)
# Extrae precios desde tu IP residencial, actualiza Bronze/Silver/Gold y
# regenera el bundle estático en `web/data/`.
# ==============================================================================

set -euo pipefail

MODE="${1:-basket}"

if [ "$MODE" = "fmcg" ]; then
  echo "Ejecutando extracción completa por categorías FMCG..."
  uv run scraper extract --stores all --fmcg --pages 2 --export-web
else
  echo "Ejecutando extracción rápida de canasta extendida..."
  uv run scraper extract --stores all --basket extended --pages 2 --export-web
fi

echo ""
echo "Reporte ejecutivo DuckDB:"
uv run scraper report --limit 8
echo ""
echo "Listo. Podés abrir la Web App local con: uv run scraper serve"
