"""
download_csv.py — Descarga automática del CSV desde AppSheet.

Usa la sesión guardada por setup_session.py para abrir AppSheet en modo
headless, hace clic en el menú "More" (⋮) y luego en "Exportar".

Se llama automáticamente desde update.py antes de procesar el inventario.
También puede ejecutarse de forma independiente:

    python3 download_csv.py              # usa rutas del config.json
    python3 download_csv.py --check      # solo verifica si la sesión es válida
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
SESSION_FILE = SCRIPT_DIR / "session.json"

# URL sin filtros — exporta el dataset completo de la tabla DISPONIBLES
APPSHEET_URL = (
    "https://www.appsheet.com/start/31f455dc-18f8-4f0a-b0e6-e1b71432627f"
    "#appName=AutostarLP-6460567-22-08-31"
    "&page=fastTable"
    "&table=DISPONIBLES&view=LP"
)

# Tiempo de espera para que la SPA renderice tras domcontentloaded (segundos)
APP_RENDER_WAIT_S = 10
MORE_BUTTON_TIMEOUT  = 15_000   # ms
EXPORT_OPTION_TIMEOUT = 5_000   # ms
DOWNLOAD_TIMEOUT     = 60_000   # ms

# Mapeo: columna en CSV exportado de AppSheet → nombre interno del pipeline
COLUMN_MAP: dict[str, str] = {
    "VIN":                  "vin",
    "Inv.":                 "inv",
    "Descripción":          "desc",
    "Año":                  "anio",
    "Kms":                  "kms",
    "Color":                "color",
    "Precio":               "precio",
    "Bono":                 "bono",
    "Garantia":             "garantia",
    "Ubicación":            "ubicacion",
    "plaza":                "grupo",
    "Condición de venta":   "condicion",
    "LINK":                 "link",
    "Tipo":                 "tipo",
    "Estatus":              "estatus",
    "Foráneo":              "foraneo",
    "Cil":                  "cil",
    "Lts":                  "lts",
    "Trans.":               "trans",
}


# ---------------------------------------------------------------------------
# Excepciones
# ---------------------------------------------------------------------------

class SessionError(Exception):
    """La sesión no existe o ha expirado."""


class DownloadError(Exception):
    """No se pudo completar la descarga del CSV."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    config_path = SCRIPT_DIR / "config.json"
    if not config_path.exists():
        print("[download] config.json no encontrado.")
        sys.exit(1)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    csv_raw = raw.get("csv_path", "./inventario.csv")
    csv_path = Path(csv_raw)
    if not csv_path.is_absolute():
        csv_path = SCRIPT_DIR / csv_path
    return {"csv_path": csv_path.resolve()}


def _check_session() -> bool:
    if not SESSION_FILE.exists():
        return False
    try:
        data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        return bool(data.get("cookies") or data.get("origins"))
    except Exception:
        return False


def _derive_grupo(ubicacion: str) -> str:
    """Deriva el campo grupo a partir del valor de Ubicación de AppSheet.

    Reglas (en orden de prioridad):
      - Contiene "TJ"   → "Tijuana"
      - Contiene "MXLI" → "Mexicali"
      - Es "AUTOSTAR"   → "Mexicali"
      - Es "TOYOTA CETYS" o "CARROCERIA MXLI" o "TALLER MXLI" o "MAZDA MXLI" → "Mexicali"
      - Todo lo demás   → "Otro"
    """
    u = ubicacion.strip().upper()
    if "TJ" in u:
        return "Tijuana"
    if "MXLI" in u:
        return "Mexicali"
    if u in ("AUTOSTAR", "TOYOTA CETYS"):
        return "Mexicali"
    return "Otro"


def _normalize_csv(raw_path: Path) -> None:
    """Renombra las columnas del CSV exportado de AppSheet a los nombres
    internos del pipeline, deriva el campo grupo desde Ubicación,
    y elimina columnas que no se usan.

    Sobreescribe el archivo en el mismo path.
    """
    with raw_path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        raw_rows = list(reader)

    if not raw_rows:
        return

    internal_cols = list(COLUMN_MAP.values())
    normalized = []
    for row in raw_rows:
        new_row = {}
        for appsheet_col, internal_col in COLUMN_MAP.items():
            new_row[internal_col] = row.get(appsheet_col, "")
        # Derivar grupo desde ubicacion (el campo plaza de AppSheet no tiene los valores correctos)
        new_row["grupo"] = _derive_grupo(new_row.get("ubicacion", ""))
        normalized.append(new_row)

    with raw_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=internal_cols)
        writer.writeheader()
        writer.writerows(normalized)


# ---------------------------------------------------------------------------
# Función principal de descarga
# ---------------------------------------------------------------------------

def download_csv(csv_path: Path, verbose: bool = True) -> None:
    """Abre AppSheet con la sesión guardada y descarga el CSV completo.

    Flujo:
      1. Carga la app sin filtros y espera a que renderice.
      2. Clic en el botón "More" (⋮).
      3. Clic en "Exportar" del menú.
      4. Guarda el CSV y normaliza los nombres de columnas.

    Raises:
        SessionError:  Si session.json no existe o la sesión expiró.
        DownloadError: Si no se pudo completar la descarga.
    """
    if not _check_session():
        raise SessionError(
            "No se encontró una sesión válida. "
            "Ejecuta primero: python3 setup_session.py"
        )

    def log(msg: str) -> None:
        if verbose:
            print(f"[download] {msg}")

    log("Iniciando navegador headless...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            storage_state=str(SESSION_FILE),
            viewport={"width": 1280, "height": 900},
            accept_downloads=True,
        )
        page = context.new_page()

        # --- 1. Cargar la app ---
        log("Abriendo AppSheet (sin filtros)...")
        try:
            page.goto(APPSHEET_URL, wait_until="domcontentloaded", timeout=60_000)
        except PlaywrightTimeout:
            browser.close()
            raise DownloadError("Timeout al cargar AppSheet. Verifica tu conexión.")

        if "accounts.google.com" in page.url or "signin" in page.url.lower():
            browser.close()
            raise SessionError(
                "La sesión de Google ha expirado. "
                "Ejecuta: python3 setup_session.py"
            )

        log(f"Esperando que la app cargue ({APP_RENDER_WAIT_S}s)...")
        time.sleep(APP_RENDER_WAIT_S)

        # --- 2. Clic en "More" (⋮) ---
        log("Abriendo menú '⋮'...")
        try:
            more_btn = page.wait_for_selector(
                "[aria-label='More']",
                timeout=MORE_BUTTON_TIMEOUT,
                state="visible",
            )
        except PlaywrightTimeout:
            page.screenshot(path=str(SCRIPT_DIR / "debug_screenshot.png"))
            browser.close()
            raise DownloadError(
                "No se encontró el botón '⋮'. "
                "Screenshot guardado en debug_screenshot.png"
            )

        more_btn.click()
        time.sleep(1)

        # --- 3. Clic en "Exportar" ---
        log("Seleccionando 'Exportar'...")
        try:
            export_option = page.wait_for_selector(
                ".PopupMenu__option:has-text('Exportar'), "
                ".PopupMenu__option:has-text('Export')",
                timeout=EXPORT_OPTION_TIMEOUT,
                state="visible",
            )
        except PlaywrightTimeout:
            page.screenshot(path=str(SCRIPT_DIR / "debug_screenshot.png"))
            browser.close()
            raise DownloadError(
                "No apareció la opción 'Exportar'. "
                "Screenshot guardado en debug_screenshot.png"
            )

        # --- 4. Capturar descarga ---
        log("Descargando CSV...")
        try:
            with page.expect_download(timeout=DOWNLOAD_TIMEOUT) as dl_info:
                export_option.click()
            download = dl_info.value
        except PlaywrightTimeout:
            browser.close()
            raise DownloadError("Timeout esperando la descarga del CSV.")

        csv_path.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(str(csv_path))
        browser.close()

    if not csv_path.exists() or csv_path.stat().st_size == 0:
        raise DownloadError(f"El archivo descargado está vacío: {csv_path}")

    raw_size = csv_path.stat().st_size

    # --- 5. Normalizar nombres de columnas ---
    log("Normalizando columnas del CSV...")
    _normalize_csv(csv_path)

    # Contar filas para el log
    with csv_path.open(encoding="utf-8") as fh:
        row_count = sum(1 for _ in fh) - 1  # restar encabezado

    log(f"✓ CSV listo → {csv_path} ({row_count} vehículos, {raw_size // 1024} KB raw)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Descarga el CSV de inventario desde AppSheet."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Solo verifica si la sesión es válida, sin descargar.",
    )
    args = parser.parse_args()

    if args.check:
        if _check_session():
            print("✓ session.json existe y parece válido.")
            sys.exit(0)
        else:
            print("✗ No hay sesión guardada. Ejecuta: python3 setup_session.py")
            sys.exit(1)

    config = _load_config()

    try:
        download_csv(config["csv_path"], verbose=True)
    except SessionError as e:
        print(f"\n[error] Sesión inválida: {e}")
        sys.exit(1)
    except DownloadError as e:
        print(f"\n[error] Descarga fallida: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
