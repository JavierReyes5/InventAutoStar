"""
update.py — Script de auto-actualización diaria del inventario Autostar.

Descarga el CSV desde AppSheet automáticamente (requiere session.json generado
por setup_session.py), lo transforma al formato JSON que espera
inventario_autostar.html, y regenera el archivo con los datos frescos.

Uso:
    python3 update.py               # descarga CSV y actualiza el HTML
    python3 update.py --dry-run     # descarga CSV pero no sobreescribe el HTML
    python3 update.py --skip-download  # usa el CSV existente sin descargar
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Versión del script
# ---------------------------------------------------------------------------

SCRIPT_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Jerarquía de excepciones personalizadas
# ---------------------------------------------------------------------------


class AutostarError(Exception):
    """Clase base para todas las excepciones del pipeline Autostar."""


class ConfigError(AutostarError):
    """config.json faltante, inválido o con rutas inaccesibles."""


class LockError(AutostarError):
    """Ya hay una ejecución del script en progreso (lock activo)."""


class CSVError(AutostarError):
    """CSV_Fuente faltante, vacío o con columnas inválidas."""


class TemplateError(AutostarError):
    """El placeholder no se encontró exactamente una vez en el template."""


class BackupError(AutostarError):
    """No se pudo crear o verificar la integridad del backup."""


class OutputValidationError(AutostarError):
    """El HTML generado no pasó las validaciones mínimas de contenido o tamaño."""


class WriteError(AutostarError):
    """Error durante la escritura del App_HTML en disco."""

# ---------------------------------------------------------------------------
# Constantes de logging
# ---------------------------------------------------------------------------

LOG_MAX_BYTES = 1_048_576  # 1 MB
LOG_MAX_ROTATED = 5        # máximo de archivos rotados conservados


# ---------------------------------------------------------------------------
# setup_logger
# ---------------------------------------------------------------------------


def setup_logger(log_path: Path) -> logging.Logger:
    """Configura y retorna el logger 'autostar'.

    Si log_path existe y supera 1 MB, lo rota:
      - Lo renombra a {stem}_{YYYYMMDDTHHMMSS}{suffix}
      - Si ya hay ≥ 5 archivos rotados, elimina el más antiguo antes de crear el nuevo
    Crea el archivo de log vacío (y el directorio padre si es necesario).
    Añade un FileHandler (DEBUG) y un StreamHandler/consola (INFO).
    """
    log_path = Path(log_path)

    # --- Rotación si el archivo supera 1 MB ---
    if log_path.exists() and log_path.stat().st_size > LOG_MAX_BYTES:
        # Contar archivos rotados ANTES de añadir el nuevo
        pattern = f"{log_path.stem}_*{log_path.suffix}"
        rotated_files = sorted(log_path.parent.glob(pattern))
        if len(rotated_files) >= LOG_MAX_ROTATED:
            # Eliminar el más antiguo (primero en orden alfabético / cronológico)
            rotated_files[0].unlink()

        timestamp = datetime.now().strftime("%Y-%m-%dT%H%M%S")
        rotated_name = f"{log_path.stem}_{timestamp}{log_path.suffix}"
        rotated_path = log_path.parent / rotated_name
        log_path.rename(rotated_path)

    # --- Crear directorio padre y archivo de log vacío ---
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if not log_path.exists():
        log_path.touch()

    # --- Configurar logger ---
    logger = logging.getLogger("autostar")
    logger.setLevel(logging.DEBUG)

    # Evitar duplicar handlers si el logger ya fue configurado
    if logger.handlers:
        logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-5s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # FileHandler → DEBUG y superior
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # StreamHandler → INFO y superior
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    return logger

# ---------------------------------------------------------------------------
# Constantes de configuración
# ---------------------------------------------------------------------------

REQUIRED_CONFIG_FIELDS = {
    "csv_path",
    "html_output_path",
    "template_path",
    "backup_dir",
    "log_path",
}

CONFIG_DEFAULTS = {
    "csv_path": "./inventario.csv",
    "html_output_path": "./inventario_autostar.html",
    "template_path": "./template.html",
    "backup_dir": "./backups",
    "log_path": "./actualizacion.log",
}

# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


def load_config(script_dir: Path) -> dict:
    """Lee config.json desde script_dir y retorna un dict con Paths resueltos.

    Comportamiento:
    - Si config.json no existe: lo crea con defaults, imprime mensaje y sys.exit(0).
    - Si faltan campos: imprime los nombres faltantes y sys.exit(1).
    - Resuelve todas las rutas relativas contra script_dir.
    - Crea backup_dir si no existe todavía.
    - Si algún directorio padre no existe o no es escribible: imprime campo +
      ruta y sys.exit(1).

    Args:
        script_dir: Directorio donde reside update.py (y config.json).

    Returns:
        Dict con claves: csv_path, html_output_path, template_path,
        backup_dir, log_path — todas como objetos Path resueltos.
    """
    config_path = script_dir / "config.json"

    # ------------------------------------------------------------------ #
    # 1. Si config.json no existe → crearlo con defaults y salir          #
    # ------------------------------------------------------------------ #
    if not config_path.exists():
        config_path.write_text(
            json.dumps(CONFIG_DEFAULTS, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(
            f"[config] Se creó '{config_path}' con valores por defecto.\n"
            "         Edita el archivo para ajustar las rutas a tu entorno "
            "antes de volver a ejecutar el script."
        )
        sys.exit(0)

    # ------------------------------------------------------------------ #
    # 2. Leer y parsear el JSON                                           #
    # ------------------------------------------------------------------ #
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[config] Error al parsear '{config_path}': {exc}")
        sys.exit(1)

    if not isinstance(raw, dict):
        print(f"[config] '{config_path}' debe ser un objeto JSON, no {type(raw).__name__}.")
        sys.exit(1)

    # ------------------------------------------------------------------ #
    # 3. Verificar campos obligatorios                                    #
    # ------------------------------------------------------------------ #
    missing = REQUIRED_CONFIG_FIELDS - raw.keys()
    if missing:
        missing_sorted = sorted(missing)
        print(
            f"[config] Faltan campos obligatorios en '{config_path}': "
            + ", ".join(missing_sorted)
        )
        sys.exit(1)

    # ------------------------------------------------------------------ #
    # 4. Resolver rutas relativas contra script_dir                       #
    # ------------------------------------------------------------------ #
    resolved: dict[str, Path] = {}
    for field in REQUIRED_CONFIG_FIELDS:
        raw_value = raw[field]
        path = Path(raw_value)
        if not path.is_absolute():
            path = script_dir / path
        resolved[field] = path.resolve()

    # ------------------------------------------------------------------ #
    # 5. Crear backup_dir si no existe; verificar accesibilidad           #
    # ------------------------------------------------------------------ #
    backup_dir: Path = resolved["backup_dir"]
    if not backup_dir.exists():
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(
                f"[config] No se pudo crear el directorio 'backup_dir': "
                f"{backup_dir} — {exc}"
            )
            sys.exit(1)

    # Campos cuyo directorio PADRE debe existir y ser escribible
    parent_check_fields = ("csv_path", "html_output_path", "template_path", "log_path")
    for field in parent_check_fields:
        parent = resolved[field].parent
        if not parent.exists() or not parent.is_dir():
            print(
                f"[config] El directorio padre de '{field}' no existe o no es "
                f"accesible: {parent}"
            )
            sys.exit(1)
        if not _is_writable(parent):
            print(
                f"[config] El directorio padre de '{field}' no tiene permisos de "
                f"escritura: {parent}"
            )
            sys.exit(1)

    # backup_dir ya existe (creado o preexistente) — verificar escritura
    if not _is_writable(backup_dir):
        print(
            f"[config] El directorio 'backup_dir' no tiene permisos de escritura: "
            f"{backup_dir}"
        )
        sys.exit(1)

    return resolved


def _is_writable(path: Path) -> bool:
    """Retorna True si path es un directorio escribible."""
    import os

    return os.access(path, os.W_OK)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS: set[str] = {
    "vin", "inv", "desc", "anio", "kms", "color", "precio",
    "tipo", "estatus", "grupo",
}

# ---------------------------------------------------------------------------
# Validación del CSV
# ---------------------------------------------------------------------------


def validate_csv(csv_path: Path, logger: logging.Logger) -> list[dict]:
    """Valida el CSV de entrada y retorna sus filas como lista de dicts.

    Args:
        csv_path: Ruta al archivo CSV exportado desde AppSheet.
        logger:   Logger configurado para registrar advertencias.

    Returns:
        Lista de dicts con las filas crudas del CSV (strings sin transformar).

    Raises:
        CSVError: Si el archivo no existe, está vacío o le faltan columnas
                  obligatorias.
    """
    # 1. Existencia del archivo
    if not csv_path.exists():
        raise CSVError(
            f"CSV no encontrado: '{csv_path}' — archivo no encontrado"
        )

    # 2. Tamaño > 0
    if csv_path.stat().st_size == 0:
        raise CSVError(
            f"CSV vacío: '{csv_path}' — el archivo no contiene datos"
        )

    # 4. Advertencia si el archivo tiene más de 24 horas sin modificarse
    mtime = csv_path.stat().st_mtime
    mtime_dt = datetime.fromtimestamp(mtime)
    age = datetime.now() - mtime_dt
    if age > timedelta(hours=24):
        logger.warning(
            "[csv] El archivo CSV no ha sido actualizado en más de 24 horas. "
            "Última modificación: %s",
            mtime_dt.isoformat(timespec="seconds"),
        )

    # 3. Leer con DictReader y validar columnas obligatorias
    with csv_path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)

        # fieldnames se resuelve al leer la primera fila; forzamos su lectura
        header = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - header
        if missing:
            raise CSVError(
                f"CSV con columnas faltantes: {sorted(missing)}"
            )

        # 5. Retornar todas las filas como lista de dicts
        rows = list(reader)

    return rows

# ---------------------------------------------------------------------------
# filter_and_deduplicate
# ---------------------------------------------------------------------------


def filter_and_deduplicate(
    rows: list[dict],
) -> tuple[list[dict], list[int], list[str]]:
    """Elimina filas con VIN vacío y filas con VIN duplicado.

    Conserva la primera ocurrencia de cada VIN no vacío y preserva el orden
    original de aparición.

    Args:
        rows: Lista de dicts con las filas crudas del CSV (strings sin
              transformar). El índice de fila empieza en 1 (primera fila de
              datos, sin contar el encabezado).

    Returns:
        Tupla de tres elementos:
        - valid_records:      Filas válidas (VIN no vacío, sin duplicados).
        - empty_vin_indices:  Índices 1-based de las filas con VIN vacío.
        - duplicate_vins:     Valores de VIN de las filas descartadas por
                              ser duplicados de una ocurrencia anterior.
    """
    valid_records: list[dict] = []
    empty_vin_indices: list[int] = []
    duplicate_vins: list[str] = []
    seen_vins: set[str] = set()

    for row_index, row in enumerate(rows, start=1):
        vin = row.get("vin", "").strip()

        # 1. VIN vacío → registrar índice y saltar
        if not vin:
            empty_vin_indices.append(row_index)
            continue

        # 2. VIN duplicado → registrar valor y saltar
        if vin in seen_vins:
            duplicate_vins.append(vin)
            continue

        # 3. Primera ocurrencia válida → conservar
        seen_vins.add(vin)
        valid_records.append(row)

    return valid_records, empty_vin_indices, duplicate_vins


# ---------------------------------------------------------------------------
# transform_row
# ---------------------------------------------------------------------------

# Campos opcionales de texto — vacíos se convierten a ""
_OPTIONAL_TEXT_FIELDS = frozenset(
    {"bono", "garantia", "condicion", "link", "foraneo", "cil", "lts", "trans"}
)


def transform_row(raw: dict) -> dict:
    """Transforma una fila cruda del CSV en un objeto JSON del inventario.

    Función pura sin side effects. Aplica las siguientes reglas de coerción:

    - ``precio``: strip + eliminar ``$`` y ``,``; luego ``float()``.
      Si no parseable o negativo → ``0.0``.
    - ``kms``: strip + eliminar ``,``; luego ``int()``.
      Si no parseable o negativo → ``0``.
    - Campos opcionales (``bono, garantia, condicion, link, foraneo, cil, lts, trans``):
      si vacíos o solo espacios → ``""``, de lo contrario ``.strip()``.
    - Todos los demás campos string: ``.strip()``.

    Args:
        raw: Dict con las claves tal como vienen del ``csv.DictReader``.

    Returns:
        Dict con exactamente las claves:
        ``vin, inv, desc, anio, kms, color, precio, bono, garantia, ubicacion,
        grupo, condicion, link, tipo, estatus, foraneo, cil, lts, trans``.
    """
    def _str(key: str) -> str:
        return (raw.get(key) or "").strip()

    def _optional(key: str) -> str:
        value = (raw.get(key) or "").strip()
        return value  # strip() sobre vacío ya produce ""

    def _precio(key: str = "precio") -> float:
        raw_val = (raw.get(key) or "")
        cleaned = raw_val.strip().replace("$", "").replace(",", "")
        try:
            value = float(cleaned)
            if value < 0:
                return 0.0
            return value
        except (ValueError, TypeError):
            return 0.0

    def _kms(key: str = "kms") -> int:
        raw_val = (raw.get(key) or "")
        cleaned = raw_val.strip().replace(",", "")
        try:
            value = int(cleaned)
            if value < 0:
                return 0
            return value
        except (ValueError, TypeError):
            return 0

    return {
        "vin":       _str("vin"),
        "inv":       _str("inv"),
        "desc":      _str("desc"),
        "anio":      _str("anio"),
        "kms":       _kms(),
        "color":     _str("color"),
        "precio":    _precio(),
        "bono":      _optional("bono"),
        "garantia":  _optional("garantia"),
        "ubicacion": _str("ubicacion"),
        "grupo":     _str("grupo"),
        "condicion": _optional("condicion"),
        "link":      _optional("link"),
        "tipo":      _str("tipo"),
        "estatus":   _str("estatus"),
        "foraneo":   _optional("foraneo"),
        "cil":       _optional("cil"),
        "lts":       _optional("lts"),
        "trans":     _optional("trans"),
    }

# ---------------------------------------------------------------------------
# Constantes de normalización de grupo
# ---------------------------------------------------------------------------

VALID_GRUPOS: frozenset[str] = frozenset({"Mexicali", "Tijuana", "Otro"})

# ---------------------------------------------------------------------------
# normalize_grupo
# ---------------------------------------------------------------------------


def normalize_grupo(
    records: list[dict],
) -> tuple[list[dict], list[tuple[str, str]]]:
    """Valida y normaliza el campo ``grupo`` de cada registro.

    Para cada registro cuyo campo ``grupo`` no sea uno de los valores válidos
    (``"Mexicali"``, ``"Tijuana"``, ``"Otro"``), crea una copia con
    ``grupo = "Otro"`` y registra ``(vin, grupo_original)`` en la lista de
    correcciones.  Los registros con ``grupo`` ya válido se incluyen sin
    modificación.

    Args:
        records: Lista de dicts ya transformados (valores string/número).

    Returns:
        Tupla ``(normalized_records, invalids)`` donde:
        - ``normalized_records`` contiene todos los registros con ``grupo``
          garantizado en ``VALID_GRUPOS``.
        - ``invalids`` es una lista de ``(vin, grupo_invalido)`` para cada
          registro que fue corregido, en el orden en que aparecen.

    Note:
        Los dicts de entrada nunca se mutan; se devuelven copias cuando
        es necesario corregir el valor de ``grupo``.
    """
    normalized: list[dict] = []
    invalids: list[tuple[str, str]] = []

    for record in records:
        grupo = record.get("grupo", "")
        if grupo in VALID_GRUPOS:
            normalized.append(record)
        else:
            vin = str(record.get("vin", ""))
            invalids.append((vin, grupo))
            normalized.append({**record, "grupo": "Otro"})

    return normalized, invalids

# ---------------------------------------------------------------------------
# Constantes de template
# ---------------------------------------------------------------------------

PLACEHOLDER = "/*%%DATA%%*/"
FECHA_PLACEHOLDER = "%%FECHA%%"
MONTH_ABBR_ES = ["ene", "feb", "mar", "abr", "may", "jun",
                 "jul", "ago", "sep", "oct", "nov", "dic"]

# ---------------------------------------------------------------------------
# inject_into_template
# ---------------------------------------------------------------------------


def inject_into_template(
    template_content: str,
    json_data: str,
    update_date: date,
) -> str:
    """Inyecta los datos JSON y la fecha en el template HTML.

    1. Cuenta las ocurrencias de ``PLACEHOLDER`` (``/*%%DATA%%*/``) en
       ``template_content``.  Si no hay exactamente una, lanza
       :class:`TemplateError` indicando cuántas se encontraron.
    2. Reemplaza el placeholder por ``json_data``.
    3. Formatea ``update_date`` como ``DD MMM YYYY`` en español usando
       ``MONTH_ABBR_ES`` (DD con cero a la izquierda, MMM en minúsculas,
       YYYY con cuatro dígitos).
    4. Reemplaza ``FECHA_PLACEHOLDER`` (``%%FECHA%%``) por la fecha formateada.
    5. Retorna el HTML resultante.

    Args:
        template_content: Contenido completo del template HTML.
        json_data:        String JSON que sustituirá al placeholder de datos.
        update_date:      Fecha que se mostrará en el footer del HTML.

    Returns:
        HTML con los datos y la fecha inyectados.

    Raises:
        TemplateError: Si ``PLACEHOLDER`` no aparece exactamente una vez.
    """
    # 1. Validar ocurrencias del placeholder de datos
    count = template_content.count(PLACEHOLDER)
    if count != 1:
        raise TemplateError(
            f"Se encontraron {count} ocurrencias del placeholder, "
            "se esperaba exactamente 1"
        )

    # 2. Reemplazar placeholder de datos
    result = template_content.replace(PLACEHOLDER, json_data, 1)

    # 3. Formatear fecha en español
    dd = f"{update_date.day:02d}"
    mmm = MONTH_ABBR_ES[update_date.month - 1]
    yyyy = f"{update_date.year:04d}"
    fecha_str = f"{dd} {mmm} {yyyy}"

    # 4. Reemplazar placeholder de fecha
    result = result.replace(FECHA_PLACEHOLDER, fecha_str)

    # 5. Retornar HTML resultante
    return result


# ---------------------------------------------------------------------------
# validate_output
# ---------------------------------------------------------------------------


def validate_output(html_content: str) -> None:
    """Verifica que el HTML generado contiene datos válidos y tiene tamaño mínimo.

    Checks:
    1. Contiene ``const DATA = [`` seguido de al menos un elemento (array no vacío).
    2. El tamaño del contenido supera los 10 KB (10 240 bytes en UTF-8).

    Args:
        html_content: String con el contenido HTML generado.

    Raises:
        OutputValidationError: Si el array DATA está vacío/ausente o el HTML
                               es demasiado pequeño.
    """
    # --- Check 1: DATA array no vacío ---
    marker = "const DATA = ["
    if marker not in html_content:
        raise OutputValidationError(
            "El array DATA no contiene elementos o no se insertó correctamente"
        )
    # Extraer el contenido entre "[" y el primer "]"
    start_idx = html_content.index(marker) + len(marker)
    end_idx = html_content.find("]", start_idx)
    if end_idx == -1 or html_content[start_idx:end_idx].strip() == "":
        raise OutputValidationError(
            "El array DATA no contiene elementos o no se insertó correctamente"
        )

    # --- Check 2: tamaño mínimo de 10 KB ---
    size = len(html_content.encode("utf-8"))
    if size <= 10 * 1024:
        raise OutputValidationError(
            f"El HTML generado es demasiado pequeño: {size} bytes (mínimo 10240)"
        )


# ---------------------------------------------------------------------------
# create_backup
# ---------------------------------------------------------------------------


def create_backup(html_path: Path, backup_dir: Path) -> Path:
    """Copia el App_HTML actual a backup_dir con sufijo de timestamp.

    Args:
        html_path:  Ruta al archivo HTML original que se va a respaldar.
        backup_dir: Directorio donde se almacenarán los backups.

    Returns:
        Path del archivo de backup creado.

    Raises:
        BackupError: Si el tamaño del backup no coincide con el original.
    """
    # 1. Crear backup_dir si no existe
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    # 2. Determinar nombre del backup con timestamp actual
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"inventario_autostar_{timestamp}.html"
    backup_path = backup_dir / backup_filename

    # 3. Copiar el archivo original al backup
    shutil.copy2(html_path, backup_path)

    # 4. Verificar integridad: comparar tamaños en bytes
    orig_size = Path(html_path).stat().st_size
    backup_size = backup_path.stat().st_size
    if orig_size != backup_size:
        raise BackupError(
            f"Integridad de backup fallida: original={orig_size} bytes, "
            f"backup={backup_size} bytes"
        )

    # 5. Retornar la ruta del backup creado
    return backup_path

# ---------------------------------------------------------------------------
# cleanup_backups
# ---------------------------------------------------------------------------


def cleanup_backups(backup_dir: Path) -> None:
    """Elimina backups cuya marca de tiempo sea anterior al umbral de 7 días.

    El umbral se calcula como:
        ``datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        - timedelta(days=7)``

    Solo se procesan archivos cuyo nombre coincida con el patrón
    ``inventario_autostar_YYYYMMDD_HHMMSS.html``. Los archivos que no
    coincidan con el patrón se omiten silenciosamente.

    Args:
        backup_dir: Directorio donde se almacenan los backups.
    """
    # 1. Si backup_dir no existe, retornar inmediatamente
    if not backup_dir.exists():
        return

    # 2. Calcular umbral: hace 7 días a las 00:00:00
    cutoff = (
        datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        - timedelta(days=7)
    )

    # 3. Buscar todos los archivos de backup con el patrón esperado
    for file in backup_dir.glob("inventario_autostar_*.html"):
        # 4. Extraer la parte del timestamp del nombre del archivo
        stem = file.stem  # e.g. "inventario_autostar_20260120_100012"
        prefix = "inventario_autostar_"
        if not stem.startswith(prefix):
            continue  # patrón inesperado, omitir

        stem_part = stem[len(prefix):]  # e.g. "20260120_100012"

        # 5. Parsear el timestamp
        try:
            file_dt = datetime.strptime(stem_part, "%Y%m%d_%H%M%S")
        except ValueError:
            # Nombre no coincide con el formato esperado — omitir
            continue

        # 6. Eliminar si es anterior al umbral (estrictamente menor)
        if file_dt < cutoff:
            file.unlink()


# ---------------------------------------------------------------------------
# Descarga automática del CSV
# ---------------------------------------------------------------------------


def _download_csv_auto(csv_path: Path, logger: logging.Logger) -> None:
    """Intenta descargar el CSV desde AppSheet usando download_csv.py.

    Si la descarga falla pero ya existe un CSV en disco, registra un aviso
    y continúa (el pipeline usará el CSV anterior).

    Si la descarga falla y NO existe CSV en disco, relanza la excepción
    para abortar el pipeline.

    Args:
        csv_path: Ruta donde se guardará el CSV descargado.
        logger:   Logger activo del pipeline.
    """
    try:
        from download_csv import SessionError, DownloadError, download_csv
        logger.info("[download] Descargando CSV desde AppSheet...")
        download_csv(csv_path, verbose=False)
        logger.info("[download] CSV descargado correctamente → %s", csv_path)
    except ImportError:
        logger.warning(
            "[download] download_csv.py no encontrado. "
            "Usando CSV existente si está disponible."
        )
    except Exception as e:
        error_type = type(e).__name__
        if csv_path.exists() and csv_path.stat().st_size > 0:
            logger.warning(
                "[download] Descarga fallida (%s: %s). "
                "Continuando con CSV existente en disco (puede estar desactualizado).",
                error_type, e,
            )
        else:
            logger.error(
                "[download] Descarga fallida y no hay CSV en disco: %s: %s",
                error_type, e,
            )
            raise CSVError(
                f"No se pudo descargar el CSV y no existe archivo local: {e}"
            )



# ---------------------------------------------------------------------------
# run_pipeline
# ---------------------------------------------------------------------------


def run_pipeline(config: dict, logger: logging.Logger, dry_run: bool = False, skip_download: bool = False) -> None:
    """Orquesta el pipeline completo de actualización del inventario.

    Pasos en orden:
    0. Descargar el CSV desde AppSheet (omitido si skip_download=True).
    1. Log de inicio con versión y ruta del CSV.
    2. Validar el CSV y obtener filas crudas.
    3. Transformar cada fila con transform_row.
    4. Filtrar y deduplicar por VIN.
    5. Loguear filas omitidas por VIN vacío y duplicados.
    6. Normalizar el campo grupo.
    7. Loguear registros con grupo inválido corregido.
    8. Serializar a JSON.
    9. Leer el template HTML.
    10. Inyectar datos y fecha en el template.
    11. Validar el HTML generado.
    12. Si dry_run: imprimir conteo y retornar sin escribir.
    13. Crear backup del App_HTML actual.
    14. Escribir el nuevo HTML en disco.
    15. En caso de WriteError: restaurar backup con verificación de integridad.
    16. Limpiar backups con más de 7 días.
    17. Loguear éxito.

    Args:
        config:  Dict con claves Path: csv_path, html_output_path,
                 template_path, backup_dir, log_path.
        logger:  Logger configurado por setup_logger().
        dry_run: Si True, valida y transforma pero no sobrescribe el HTML.

    Raises:
        CSVError:              Si el CSV es inválido o faltante.
        TemplateError:         Si el placeholder no aparece exactamente una vez.
        BackupError:           Si el backup no puede crearse o verificarse.
        OutputValidationError: Si el HTML generado no pasa las validaciones.
        WriteError:            Si ocurre un error al escribir el App_HTML.
    """
    # --- Paso 0: Descargar CSV desde AppSheet ---
    if not skip_download:
        _download_csv_auto(config["csv_path"], logger)

    # --- Paso 1: Log de inicio ---
    logger.info(
        "[inicio] v%s | csv=%s",
        SCRIPT_VERSION,
        config["csv_path"],
    )

    # --- Paso 2: Validar CSV ---
    raw_rows = validate_csv(config["csv_path"], logger)

    # --- Paso 3: Transformar filas ---
    transformed = [transform_row(r) for r in raw_rows]

    # --- Paso 4: Filtrar y deduplicar ---
    valid_records, empty_indices, dup_vins = filter_and_deduplicate(transformed)

    # --- Paso 5: Loguear omisiones ---
    if empty_indices:
        indices_str = ", ".join(str(i) for i in empty_indices)
        logger.info(
            "[csv] %d filas omitidas por VIN vacío: filas %s",
            len(empty_indices),
            indices_str,
        )
    if dup_vins:
        vins_str = ", ".join(dup_vins)
        logger.info(
            "[csv] %d filas duplicadas omitidas: vins %s",
            len(dup_vins),
            vins_str,
        )

    # --- Paso 7 (+ 6): Normalizar grupo ---
    records, grupo_invalids = normalize_grupo(valid_records)

    # --- Paso 8: Loguear grupos inválidos corregidos ---
    if grupo_invalids:
        details = ", ".join(f"{{vin: {vin}, grupo: \"{grupo}\"}}" for vin, grupo in grupo_invalids)
        logger.warning(
            "[csv] %d registros con grupo inválido corregido a 'Otro': %s",
            len(grupo_invalids),
            details,
        )

    # --- Paso 9: Serializar a JSON ---
    # Serializar solo el contenido del array (sin corchetes externos).
    # El template ya aporta los corchetes: const DATA = [/*%%DATA%%*/]
    # Si se insertar json.dumps(records) completo quedaría [[...]].
    _full = json.dumps(records, ensure_ascii=False)
    json_data = _full[1:-1]  # quitar [ y ] del array

    # --- Paso 10: Leer template ---
    template_content = config["template_path"].read_text(encoding="utf-8")

    # --- Paso 11: Inyectar datos y fecha ---
    html_content = inject_into_template(template_content, json_data, date.today())

    # --- Paso 12: Validar output ---
    validate_output(html_content)

    # --- Paso 13: Dry-run → imprimir y retornar ---
    if dry_run:
        print(f"[dry-run] Se procesarían {len(records)} vehículos. HTML no modificado.")
        return

    # --- Paso 14: Crear backup ---
    backup_path = create_backup(config["html_output_path"], config["backup_dir"])

    # --- Paso 15: Escribir HTML en disco ---
    try:
        config["html_output_path"].write_text(html_content, encoding="utf-8")
    except OSError as e:
        write_err = WriteError(str(e))

        # --- Paso 16: Restaurar backup en caso de WriteError ---
        try:
            backup_content = backup_path.read_bytes()
            config["html_output_path"].write_bytes(backup_content)

            # Verificar integridad
            restored_size = config["html_output_path"].stat().st_size
            backup_size = backup_path.stat().st_size
            if restored_size != backup_size:
                logger.error(
                    "[error] Restauración de backup con integridad fallida: "
                    "backup=%d bytes, restaurado=%d bytes",
                    backup_size,
                    restored_size,
                )
            else:
                logger.info(
                    "[restore] Backup restaurado correctamente: %s",
                    config["html_output_path"],
                )
        except OSError as restore_err:
            logger.error(
                "[error] No se pudo restaurar el backup: %s",
                restore_err,
            )

        logger.error(
            "[error] Error al escribir el App_HTML: %s",
            write_err,
        )
        raise write_err

    # --- Paso 17: Limpiar backups ---
    cleanup_backups(config["backup_dir"])

    # --- Paso 18: Loguear éxito ---
    logger.info(
        "[output] %d vehículos procesados | html=%s",
        len(records),
        config["html_output_path"],
    )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    """Punto de entrada del script de actualización.

    Flujo:
    1. Parsear argumentos CLI (--dry-run).
    2. Determinar script_dir y cargar configuración.
    3. Verificar lock; si existe, loguear advertencia y salir con exit 0.
    4. Crear lock.
    5. Configurar logger.
    6. Ejecutar run_pipeline dentro de try/except/finally para garantizar
       la eliminación del lock al terminar (éxito o error).
    """
    # --- 1. Parsear argumentos ---
    parser = argparse.ArgumentParser(
        description="Actualización diaria del inventario Autostar."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Valida y transforma el CSV sin sobrescribir el HTML.",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Omite la descarga automática y usa el CSV existente en disco.",
    )
    args = parser.parse_args()

    # --- 2. Determinar script_dir y cargar configuración ---
    script_dir = Path(__file__).resolve().parent
    config = load_config(script_dir)  # puede hacer sys.exit(0) o sys.exit(1)

    # --- 3. Verificar lock ---
    lock_path = script_dir / "actualizacion.lock"
    if lock_path.exists():
        # Logger mínimo para registrar la advertencia antes de salir
        _lock_logger = logging.getLogger("autostar_lock")
        _lock_logger.setLevel(logging.WARNING)
        if not _lock_logger.handlers:
            _lh = logging.FileHandler(config["log_path"], encoding="utf-8")
            _lh.setLevel(logging.WARNING)
            _lh.setFormatter(
                logging.Formatter(
                    fmt="%(asctime)s %(levelname)-5s %(message)s",
                    datefmt="%Y-%m-%dT%H:%M:%S",
                )
            )
            _lock_logger.addHandler(_lh)
        _lock_logger.warning("[lock] Ya hay una ejecución en progreso. Saliendo.")
        sys.exit(0)

    # --- 4. Crear lock ---
    lock_path.touch()

    # --- 5. Configurar logger ---
    logger = setup_logger(config["log_path"])

    # --- 6. Ejecutar pipeline con garantía de limpieza del lock ---
    try:
        run_pipeline(config, logger, dry_run=args.dry_run, skip_download=args.skip_download)
    except SystemExit:
        raise
    except AutostarError as e:
        logger.error("[error] %s: %s", type(e).__name__, e)
        sys.exit(1)
    except Exception as e:
        logger.error("[fatal] error inesperado: %s", e, exc_info=True)
        sys.exit(1)
    finally:
        if lock_path.exists():
            lock_path.unlink()


if __name__ == "__main__":
    main()
