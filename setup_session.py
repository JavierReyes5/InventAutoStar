"""
setup_session.py — Login inicial a AppSheet con Google OAuth.

Ejecuta este script UNA SOLA VEZ (o cuando la sesión expire).
Abre un navegador visible donde puedes hacer login con tu cuenta de Google.
Guarda las cookies en session.json para que download_csv.py las reutilice
sin volver a pedir credenciales.

Uso:
    python3 setup_session.py
"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

# URL de la app AppSheet (vista LP con los datos DISPONIBLES)
APPSHEET_URL = (
    "https://www.appsheet.com/start/31f455dc-18f8-4f0a-b0e6-e1b71432627f"
    "#appName=AutostarLP-6460567-22-08-31"
    "&defaults=%5B%7B%22ColumnName%22%3A%22Tipo%22%2C%22ColumnValue%22%3A%221%22%7D%5D"
    "&group=%5B%7B%22Column%22%3A%22Estatus%22%2C%22Order%22%3A%22Ascending%22%7D%5D"
    "&page=fastTable"
    "&sort=%5B%7B%22Column%22%3A%22Estatus%22%2C%22Order%22%3A%22Descending%22%7D%5D"
    "&table=DISPONIBLES&view=LP"
)

SCRIPT_DIR = Path(__file__).resolve().parent
SESSION_FILE = SCRIPT_DIR / "session.json"


def main() -> None:
    print("=" * 60)
    print("  Autostar — Configuración de sesión AppSheet")
    print("=" * 60)
    print()
    print("Se abrirá un navegador. Pasos a seguir:")
    print("  1. Inicia sesión con tu cuenta de Google.")
    print("  2. Espera a que la app AppSheet cargue completamente.")
    print("  3. Cuando veas el inventario, CIERRA el navegador.")
    print()
    print("La sesión se guardará automáticamente en session.json")
    print()

    with sync_playwright() as p:
        # Navegador visible (no headless) para que puedas hacer el login
        browser = p.chromium.launch(headless=False, slow_mo=100)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        print(f"Abriendo: {APPSHEET_URL[:60]}...")
        page.goto(APPSHEET_URL, wait_until="domcontentloaded", timeout=60_000)

        print()
        print("Esperando a que completes el login...")
        print("(Cierra el navegador cuando el inventario haya cargado)")
        print()

        # Esperar a que el usuario cierre el navegador
        try:
            page.wait_for_event("close", timeout=300_000)  # 5 minutos máximo
        except Exception:
            pass  # El usuario cerró el navegador

        # Guardar cookies y storage state
        storage = context.storage_state()
        SESSION_FILE.write_text(
            json.dumps(storage, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        browser.close()

    print(f"✓ Sesión guardada en: {SESSION_FILE}")
    print()
    print("Ahora puedes ejecutar:")
    print("  python3 download_csv.py    — para descargar el CSV manualmente")
    print("  python3 update.py          — para ejecutar el pipeline completo")


if __name__ == "__main__":
    main()
