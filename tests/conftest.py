"""
Fixtures compartidos para la suite de tests del pipeline de auto-actualización
del inventario Autostar.

Todos los fixtures que trabajan con el filesystem usan el fixture `tmp_path`
integrado de pytest, que provee un directorio temporal aislado por test.
"""

import csv
import io
import json
import os
import textwrap
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, settings

# ---------------------------------------------------------------------------
# Configuración global de Hypothesis
# ---------------------------------------------------------------------------

settings.register_profile(
    "ci",
    max_examples=200,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
settings.register_profile(
    "dev",
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "ci"))


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Columnas obligatorias según Requisito 1.4
REQUIRED_CSV_COLUMNS = [
    "vin", "inv", "desc", "anio", "kms", "color",
    "precio", "tipo", "estatus", "grupo",
]

# Columnas opcionales
OPTIONAL_CSV_COLUMNS = [
    "bono", "garantia", "ubicacion", "condicion",
    "link", "foraneo", "cil", "lts", "trans",
]

# Todas las columnas en el orden esperado por el CSV
ALL_CSV_COLUMNS = REQUIRED_CSV_COLUMNS + OPTIONAL_CSV_COLUMNS

# Valores válidos para el campo `grupo`
VALID_GRUPOS = {"Mexicali", "Tijuana", "Otro"}


# ---------------------------------------------------------------------------
# Datos de muestra mínimos
# ---------------------------------------------------------------------------

SAMPLE_VEHICLES: list[dict[str, Any]] = [
    {
        "vin": "RT103350",
        "inv": "5184",
        "desc": "SUZUKI GRAND VITARA GLX",
        "anio": "2024",
        "kms": "39159",
        "color": "AZUL",
        "precio": "335000.0",
        "bono": "",
        "garantia": "VALIDAR",
        "ubicacion": "AUTOSTAR TJ",
        "grupo": "Tijuana",
        "condicion": "Financiera/Banco con convenio",
        "link": "",
        "tipo": "SUV SUBCOMPACTAS",
        "estatus": "DISPONIBLE",
        "foraneo": "N",
        "cil": "4",
        "lts": "1.5",
        "trans": "AUT",
    },
    {
        "vin": "LL494334",
        "inv": "5234",
        "desc": "NISSAN KICKS ADVANCE",
        "anio": "2020",
        "kms": "77910",
        "color": "BLANCO",
        "precio": "240000.0",
        "bono": "",
        "garantia": "EXCELLENCE (DEFENSA A DEFENSA)",
        "ubicacion": "AUTOSTAR",
        "grupo": "Mexicali",
        "condicion": "Financiera/Banco con convenio",
        "link": "",
        "tipo": "SUV SUBCOMPACTAS",
        "estatus": "DISPONIBLE",
        "foraneo": "N",
        "cil": "4",
        "lts": "1.6",
        "trans": "AUT",
    },
    {
        "vin": "NZ047982",
        "inv": "5285",
        "desc": "MG ZS EXCITE",
        "anio": "2022",
        "kms": "73364",
        "color": "ROJO",
        "precio": "0.0",
        "bono": "",
        "garantia": "EXCELLENCE (DEFENSA A DEFENSA)",
        "ubicacion": "POR RECIBIR TJ",
        "grupo": "Tijuana",
        "condicion": "Financiera/Banco con convenio",
        "link": "",
        "tipo": "SUV SUBCOMPACTAS",
        "estatus": "POR RECIBIR",
        "foraneo": "N",
        "cil": "4",
        "lts": "1.5",
        "trans": "AUT",
    },
]

# Fila de muestra válida para usar en unit tests de transform_row
SAMPLE_ROW_VALID: dict[str, str] = {
    "vin": "TESTVIN01",
    "inv": "9001",
    "desc": "TOYOTA COROLLA LE",
    "anio": "2023",
    "kms": "30000",
    "color": "BLANCO",
    "precio": "350000.0",
    "bono": "",
    "garantia": "VALIDAR",
    "ubicacion": "AUTOSTAR",
    "grupo": "Mexicali",
    "condicion": "Financiera/Banco con convenio",
    "link": "",
    "tipo": "SEDANES COMPACTOS",
    "estatus": "DISPONIBLE",
    "foraneo": "N",
    "cil": "4",
    "lts": "2.0",
    "trans": "AUT",
}

# Contenido del template HTML de muestra.
# Contiene exactamente un placeholder /*%%DATA%%*/ y un %%FECHA%% en el footer.
SAMPLE_TEMPLATE_CONTENT: str = textwrap.dedent("""\
    <!DOCTYPE html>
    <html lang="es">
    <head>
    <meta charset="UTF-8">
    <title>Autostar · Piso de unidades</title>
    <style>
    :root { --amber: #C2185B; }
    body { font-family: 'Inter', sans-serif; }
    .card { border: 1px solid #ccc; border-radius: 8px; padding: 12px; }
    </style>
    </head>
    <body>
    <div class="wrap">
      <header>
        <div class="brand"><div class="plate">AUTOSTAR</div></div>
        <div id="shownCount">0</div> de <span id="totalCount">0</span>
      </header>
      <div class="tabs" id="tabs"></div>
      <div class="filters">
        <input type="text" id="fSearch" placeholder="Buscar...">
        <select id="fSort"><option value="precio_asc">Precio asc</option></select>
      </div>
      <div id="results"></div>
      <footer>Datos cargados de AppSheet · %%FECHA%% · Los precios y disponibilidad pueden cambiar; verifica antes de ofertar al cliente.</footer>
    </div>
    <script>
    const GROUPS = ["Mexicali","Tijuana","Otro"];
    let activeGroup = "Mexicali";
    const DATA = [/*%%DATA%%*/];
    function render() {
      document.getElementById('totalCount').textContent = DATA.length;
      document.getElementById('shownCount').textContent = DATA.length;
      const results = document.getElementById('results');
      results.innerHTML = DATA.map(d => '<div class="card">' + d.desc + '</div>').join('');
    }
    render();
    </script>
    </body>
    </html>
""")


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _make_csv_content(rows: list[dict[str, Any]], columns: list[str] | None = None) -> str:
    """Serializa una lista de dicts a contenido CSV con las columnas dadas."""
    cols = columns if columns is not None else ALL_CSV_COLUMNS
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    """Escribe un CSV en `path`."""
    path.write_text(_make_csv_content(rows, columns), encoding="utf-8")


def _write_template(path: Path, content: str | None = None) -> None:
    """Escribe el template HTML en `path`."""
    path.write_text(content if content is not None else SAMPLE_TEMPLATE_CONTENT, encoding="utf-8")


def _write_html_output(path: Path, content: str | None = None) -> None:
    """Escribe un HTML de salida mínimo en `path` (simula un inventario_autostar.html existente)."""
    # Produce un HTML de más de 10 KB con un DATA real para que las validaciones pasen
    padding = "/* " + "x" * 11_000 + " */"
    html = SAMPLE_TEMPLATE_CONTENT.replace(
        "/*%%DATA%%*/",
        json.dumps(SAMPLE_VEHICLES, ensure_ascii=False),
    ).replace("%%FECHA%%", "20 ago 2026")
    # Aseguramos que supere los 10 KB
    if len(html.encode("utf-8")) <= 10 * 1024:
        html = html.replace("</body>", f"<!-- {padding} -->\n</body>")
    path.write_text(content if content is not None else html, encoding="utf-8")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_csv_path(tmp_path: Path) -> Path:
    """
    Retorna la ruta a un archivo CSV válido con `SAMPLE_VEHICLES` en `tmp_path`.
    Contiene las 19 columnas completas y 3 filas de muestra.
    """
    csv_path = tmp_path / "inventario.csv"
    _write_csv(csv_path, SAMPLE_VEHICLES)
    return csv_path


@pytest.fixture()
def sample_template_path(tmp_path: Path) -> Path:
    """
    Retorna la ruta al archivo template HTML de muestra en `tmp_path`.
    Contiene exactamente un /*%%DATA%%*/ y un %%FECHA%%.
    """
    template_path = tmp_path / "template.html"
    _write_template(template_path)
    return template_path


@pytest.fixture()
def sample_html_output_path(tmp_path: Path) -> Path:
    """
    Retorna la ruta a un App_HTML existente en `tmp_path` (inventario_autostar.html).
    Simula el archivo de salida existente antes de una actualización.
    """
    html_path = tmp_path / "inventario_autostar.html"
    _write_html_output(html_path)
    return html_path


@pytest.fixture()
def backup_dir(tmp_path: Path) -> Path:
    """Retorna la ruta al directorio de backups (creado) dentro de `tmp_path`."""
    bd = tmp_path / "backups"
    bd.mkdir()
    return bd


@pytest.fixture()
def config_dict(tmp_path: Path, sample_csv_path: Path, sample_template_path: Path,
                sample_html_output_path: Path, backup_dir: Path) -> dict[str, Path]:
    """
    Retorna un diccionario de configuración con todas las rutas apuntando a
    artefactos reales dentro de `tmp_path`. Equivalente a lo que retorna
    `load_config()` cuando el config.json está completo y todas las rutas son válidas.
    """
    log_path = tmp_path / "actualizacion.log"
    return {
        "csv_path": sample_csv_path,
        "html_output_path": sample_html_output_path,
        "template_path": sample_template_path,
        "backup_dir": backup_dir,
        "log_path": log_path,
    }


@pytest.fixture()
def config_json_path(tmp_path: Path, config_dict: dict[str, Path]) -> Path:
    """
    Escribe un `config.json` válido en `tmp_path` y retorna su ruta.
    Las rutas son absolutas para evitar ambigüedad en los tests.
    """
    config_data = {k: str(v) for k, v in config_dict.items()}
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data, indent=2, ensure_ascii=False), encoding="utf-8")
    return config_path


@pytest.fixture()
def full_environment(tmp_path: Path) -> dict[str, Path]:
    """
    Configura un entorno completo de prueba con todos los artefactos necesarios:
    - CSV válido con SAMPLE_VEHICLES
    - template.html con placeholders
    - inventario_autostar.html existente (App_HTML)
    - directorio backups/
    - config.json apuntando a todos los artefactos

    Retorna un dict con claves: csv_path, html_output_path, template_path,
    backup_dir, log_path, config_json_path, tmp_path.
    """
    csv_path = tmp_path / "inventario.csv"
    _write_csv(csv_path, SAMPLE_VEHICLES)

    template_path = tmp_path / "template.html"
    _write_template(template_path)

    html_output_path = tmp_path / "inventario_autostar.html"
    _write_html_output(html_output_path)

    bd = tmp_path / "backups"
    bd.mkdir()

    log_path = tmp_path / "actualizacion.log"

    config_data = {
        "csv_path": str(csv_path),
        "html_output_path": str(html_output_path),
        "template_path": str(template_path),
        "backup_dir": str(bd),
        "log_path": str(log_path),
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "csv_path": csv_path,
        "html_output_path": html_output_path,
        "template_path": template_path,
        "backup_dir": bd,
        "log_path": log_path,
        "config_json_path": config_path,
        "tmp_path": tmp_path,
    }


# ---------------------------------------------------------------------------
# Helpers de utilidad exportables para los módulos de test
# ---------------------------------------------------------------------------

def make_csv_content(rows: list[dict[str, Any]], columns: list[str] | None = None) -> str:
    """API pública del helper interno para usarse en módulos de test."""
    return _make_csv_content(rows, columns)


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    """API pública del helper de escritura CSV para usarse en módulos de test."""
    _write_csv(path, rows, columns)
