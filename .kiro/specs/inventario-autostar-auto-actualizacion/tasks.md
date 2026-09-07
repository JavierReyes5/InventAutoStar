# Implementation Plan: Inventario Autostar — Auto-Actualización Diaria

## Overview

Implementar el pipeline de actualización automática diaria del inventario Autostar. El sistema consiste en un script Python 3 (`update.py`) que lee un CSV exportado desde AppSheet, lo transforma al formato JSON requerido por `inventario_autostar.html`, y regenera el archivo HTML con los datos frescos. Se incluyen gestión de configuración, logging, backups, lock de concurrencia y una suite de tests con pytest + hypothesis.

---

## Tasks

- [x] 1. Configurar estructura del proyecto y dependencias
  - Crear el directorio `tests/` en `/Users/javiereli/InventAutoStar/`
  - Crear `requirements.txt` con las dependencias: `pytest`, `hypothesis`, `pytest-cov`
  - Crear `tests/conftest.py` con fixtures compartidos: `tmp_path`-based environment, CSV de muestra mínimo, contenido de template de muestra
  - _Requirements: 6.1_

- [x] 2. Implementar excepciones personalizadas y estructura base del script
  - [x] 2.1 Crear `update.py` con la jerarquía de excepciones (`AutostarError`, `ConfigError`, `LockError`, `CSVError`, `TemplateError`, `BackupError`, `OutputValidationError`, `WriteError`) y la constante `SCRIPT_VERSION = "1.0.0"`
    - Definir todas las clases de excepción que heredan de `AutostarError`
    - _Requirements: 4.1_

- [x] 3. Implementar `load_config()`
  - [x] 3.1 Escribir la función `load_config(script_dir: Path) -> dict` en `update.py`
    - Si `config.json` no existe: crearlo con los cinco valores por defecto, imprimir mensaje en consola y hacer `sys.exit(0)`
    - Si existe pero faltan campos: imprimir nombres de campos faltantes y hacer `sys.exit(1)`
    - Resolver rutas relativas contra `script_dir`
    - Verificar que los directorios padre de cada ruta existan y sean accesibles; si no, imprimir campo y ruta inaccesible y hacer `sys.exit(1)`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [ ]* 3.2 Escribir property test para `load_config` — Property 11
    - **Property 11: Campos faltantes de config.json siempre reportados**
    - Para cualquier subconjunto de los 5 campos requeridos ausentes, el script debe imprimir exactamente los campos faltantes y terminar sin actualizar HTML
    - **Validates: Requirements 6.3**

  - [ ]* 3.3 Escribir unit tests para `load_config`
    - Test: config.json no existe → se crea con defaults y termina
    - Test: config.json con todos los campos → retorna dict con Paths resueltos
    - Test: ruta inaccesible → imprime campo y termina
    - _Requirements: 6.2, 6.4, 6.5_

- [x] 4. Implementar `setup_logger()`
  - [x] 4.1 Escribir la función `setup_logger(log_path: Path) -> logging.Logger` en `update.py`
    - Si el archivo de log supera 1 MB: renombrarlo con sufijo ISO 8601
    - Si ya hay ≥ 5 archivos rotados previos: eliminar el más antiguo antes de crear el nuevo
    - Crear un nuevo log vacío; configurar formato `YYYY-MM-DDTHH:MM:SS LEVEL [fase] mensaje`
    - _Requirements: 5.1, 5.4, 5.5, 5.6_

  - [ ]* 4.2 Escribir property test para `setup_logger` — Property 13
    - **Property 13: Rotación de logs conserva máximo 5 archivos rotados**
    - Para cualquier N ≥ 5 archivos rotados existentes, después de una nueva rotación deben existir exactamente 5
    - **Validates: Requirements 5.6**

  - [ ]* 4.3 Escribir unit tests para `setup_logger`
    - Test: log < 1 MB → no rota
    - Test: log > 1 MB → rota y crea nuevo vacío
    - Test: 5 rotados existentes → elimina el más antiguo antes de crear el nuevo
    - _Requirements: 5.4, 5.6_

- [x] 5. Implementar `validate_csv()`
  - [x] 5.1 Escribir la función `validate_csv(csv_path: Path) -> list[dict]` en `update.py`
    - Si la ruta no existe: lanzar `CSVError` con la ruta y el motivo
    - Si el archivo tiene tamaño cero: lanzar `CSVError` indicando que está vacío
    - Abrir con `csv.DictReader`; verificar que el encabezado contiene las 10 columnas obligatorias (`vin, inv, desc, anio, kms, color, precio, tipo, estatus, grupo`)
    - Si faltan columnas: lanzar `CSVError` con los nombres de las columnas faltantes
    - Si la fecha de modificación del CSV es anterior a 24 horas: loguear `WARNING` con la fecha de modificación y continuar
    - Retornar lista de dicts con las filas crudas
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

  - [ ]* 5.2 Escribir property test para `validate_csv` — Property 1
    - **Property 1: Columnas faltantes siempre detectadas**
    - Para cualquier subconjunto de columnas en el encabezado, si falta alguna obligatoria, debe reportar exactamente las faltantes y abortar
    - **Validates: Requirements 1.4, 1.5**

  - [ ]* 5.3 Escribir unit tests para `validate_csv`
    - Test: CSV inexistente → CSVError con ruta
    - Test: CSV vacío (0 bytes) → CSVError
    - Test: CSV con todas las columnas → retorna filas
    - Test: CSV modificado hace >24h → WARNING en log y continúa
    - _Requirements: 1.2, 1.3, 1.6_

- [x] 6. Implementar `transform_row()`, `filter_and_deduplicate()` y `normalize_grupo()`
  - [x] 6.1 Escribir la función pura `transform_row(raw: dict) -> dict` en `update.py`
    - Coercionar `precio` a `float` (→ `0.0` si no parseable, limpiando `$` y `,`)
    - Coercionar `kms` a `int` (→ `0` si no parseable o negativo)
    - Campos opcionales vacíos (`bono, garantia, condicion, link, foraneo, cil, lts, trans`) → `""`
    - Aplicar `.strip()` a todos los campos string
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [ ]* 6.2 Escribir property test para `transform_row` — Property 2
    - **Property 2: Precio inválido normalizado a 0.0**
    - Para cualquier string en `precio` que no sea parseable como decimal, `transform_row` debe retornar `precio == 0.0`
    - **Validates: Requirements 2.2**

  - [ ]* 6.3 Escribir property test para `transform_row` — Property 3
    - **Property 3: Kilometraje inválido normalizado a 0**
    - Para cualquier string en `kms` que no sea parseable como entero no negativo, `transform_row` debe retornar `kms == 0`
    - **Validates: Requirements 2.3**

  - [ ]* 6.4 Escribir property test para `transform_row` — Property 4
    - **Property 4: Campos opcionales vacíos producen string vacío**
    - Para cualquier combinación de campos opcionales vacíos, el objeto resultante debe tener `""` en esos campos
    - **Validates: Requirements 2.4**

  - [ ]* 6.5 Escribir property test para `transform_row` — Property 5
    - **Property 5: JSON producido siempre es parseable**
    - Para cualquier fila con al menos vin no vacío y columnas obligatorias presentes, `json.dumps([transform_row(row)])` debe ser parseable por `json.loads()` sin excepción
    - **Validates: Requirements 2.5**

  - [x] 6.6 Escribir la función `filter_and_deduplicate(rows: list[dict]) -> tuple[list[dict], list[int], list[str]]` en `update.py`
    - Omitir filas con `vin` vacío o solo espacios; registrar sus índices (1-based, sin contar encabezado)
    - Conservar solo la primera ocurrencia de cada `vin`; registrar `vin` de duplicados omitidos
    - _Requirements: 2.6, 2.8_

  - [ ]* 6.7 Escribir property test para `filter_and_deduplicate` — Property 6
    - **Property 6: Filas con VIN vacío siempre omitidas y registradas**
    - Para cualquier CSV con N filas de vin vacío en posiciones arbitrarias, el resultado no debe contener ninguna y los índices omitidos deben ser exactamente N
    - **Validates: Requirements 2.6**

  - [ ]* 6.8 Escribir property test para `filter_and_deduplicate` — Property 7
    - **Property 7: VINs duplicados: solo la primera ocurrencia**
    - Para cualquier CSV con K filas del mismo vin no-vacío, el resultado debe contener exactamente una ocurrencia (la primera) y el log debe reportar K-1 duplicados
    - **Validates: Requirements 2.8**

  - [x] 6.9 Escribir la función `normalize_grupo(records: list[dict]) -> tuple[list[dict], list[tuple[str, str]]]` en `update.py`
    - Validar que `grupo` ∈ `{"Mexicali", "Tijuana", "Otro"}`
    - Si no, corregir a `"Otro"` y retornar lista de `(vin, grupo_invalido)` para logging
    - _Requirements: 7.6, 7.7_

  - [ ]* 6.10 Escribir property test para `normalize_grupo` — Property 8
    - **Property 8: Grupo siempre en valores válidos**
    - Para cualquier conjunto de registros con valores arbitrarios en `grupo`, el resultado debe tener todos los registros con `grupo` ∈ `{"Mexicali", "Tijuana", "Otro"}`
    - **Validates: Requirements 7.6, 7.7**

- [x] 7. Checkpoint — Verificar transformaciones
  - Asegurarse de que todos los tests de las tareas 3–6 pasan. Preguntar al usuario si surge alguna duda.

- [x] 8. Implementar `inject_into_template()` y `validate_output()`
  - [x] 8.1 Escribir la función `inject_into_template(template_content: str, json_data: str, update_date: date) -> str` en `update.py`
    - Contar ocurrencias de `/*%%DATA%%*/`; si no es exactamente 1, lanzar `TemplateError` con el conteo
    - Reemplazar `/*%%DATA%%*/` con `json_data`
    - Reemplazar el placeholder `%%FECHA%%` en el footer con la fecha en formato `DD MMM YYYY` usando `MONTH_ABBR_ES`
    - _Requirements: 3.1, 3.3, 3.4, 3.5_

  - [ ]* 8.2 Escribir property test para `inject_into_template` — Property 9
    - **Property 9: Formato de fecha del footer**
    - Para cualquier fecha válida del calendario, el footer generado debe usar exactamente `DD MMM YYYY` con cero a la izquierda, abreviatura española correcta y año de 4 dígitos
    - **Validates: Requirements 3.4**

  - [ ]* 8.3 Escribir property test para `inject_into_template` — Property 10
    - **Property 10: Estructura del template preservada**
    - Para cualquier template válido con exactamente un placeholder, el HTML generado debe contener todos los bloques de CSS, HTML estructural y JavaScript originales
    - **Validates: Requirements 7.1, 3.3**

  - [x] 8.4 Escribir la función `validate_output(html_content: str) -> None` en `update.py`
    - Verificar que el HTML contiene `const DATA = [` seguido de al menos un elemento (`[` no vacío inmediatamente)
    - Verificar que `len(html_content.encode("utf-8")) > 10 * 1024`
    - Si alguna falla: lanzar `OutputValidationError` con detalle
    - _Requirements: 7.2, 7.3, 7.4, 7.5_

  - [ ]* 8.5 Escribir unit tests para `validate_output`
    - Test: HTML válido con DATA y tamaño > 10 KB → no lanza
    - Test: HTML sin `const DATA = [` → `OutputValidationError`
    - Test: HTML con `DATA = []` vacío → `OutputValidationError`
    - Test: HTML con tamaño ≤ 10 KB → `OutputValidationError`
    - _Requirements: 7.2, 7.3, 7.4, 7.5_

- [x] 9. Implementar `create_backup()` y `cleanup_backups()`
  - [x] 9.1 Escribir la función `create_backup(html_path: Path, backup_dir: Path) -> Path` en `update.py`
    - Crear `backup_dir` si no existe
    - Copiar `html_path` a `backup_dir/inventario_autostar_YYYYMMDD_HHMMSS.html`
    - Verificar que el backup resultante tiene el mismo tamaño en bytes que el original; si no, lanzar `BackupError`
    - Retornar la ruta del backup creado
    - _Requirements: 3.2_

  - [x] 9.2 Escribir la función `cleanup_backups(backup_dir: Path) -> None` en `update.py`
    - Parsear la marca de tiempo del nombre de cada archivo de backup
    - Calcular el umbral: `(datetime.now().replace(hour=0,minute=0,second=0,microsecond=0)) - timedelta(days=7)`
    - Eliminar todos los backups cuya marca de tiempo sea anterior al umbral
    - _Requirements: 3.7_

  - [ ]* 9.3 Escribir property test para `cleanup_backups` — Property 12
    - **Property 12: Backups de más de 7 días siempre eliminados**
    - Para cualquier conjunto de backups con marcas de tiempo arbitrarias, después de `cleanup_backups` deben permanecer exactamente los que están dentro de los últimos 7 días
    - **Validates: Requirements 3.7**

  - [ ]* 9.4 Escribir unit tests para `create_backup`
    - Test: backup_dir no existe → se crea y el backup se guarda
    - Test: backup resultante tiene el tamaño correcto
    - Test: error de copia → `BackupError`
    - _Requirements: 3.2_

- [x] 10. Crear `template.html`
  - [x] 10.1 Crear el archivo `template.html` en `/Users/javiereli/InventAutoStar/` a partir de `inventario_autostar.html`
    - Reemplazar `const DATA = [...];` por `const DATA = [/*%%DATA%%*/];`
    - Reemplazar el contenido de la fecha en el footer (`20 ago 2026`) por `%%FECHA%%`, dejando la línea como: `<footer>Datos cargados de AppSheet · %%FECHA%% · Los precios y disponibilidad pueden cambiar; verifica antes de ofertar al cliente.</footer>`
    - Verificar que el marcador `/*%%DATA%%*/` aparece exactamente una vez en el archivo
    - _Requirements: 3.1, 7.1_

- [x] 11. Implementar el orquestador principal `run_pipeline()` y el bloque `main`
  - [x] 11.1 Escribir la función `run_pipeline(config: dict, logger: logging.Logger) -> None` en `update.py`
    - Loguear entrada de inicio (timestamp ISO 8601, versión, ruta CSV)
    - Ejecutar en secuencia: `validate_csv` → transformar filas con `transform_row` → `filter_and_deduplicate` → `normalize_grupo` → serializar JSON → `inject_into_template` → `validate_output` → `create_backup` → escribir `html_output_path` → `cleanup_backups` → rotar logs si aplica → loguear éxito
    - Loguear filas omitidas (vacíos y duplicados) y grupos inválidos corregidos con los detalles requeridos
    - Implementar rollback: si la escritura falla, restaurar el backup con verificación de integridad de bytes
    - _Requirements: 2.6, 2.8, 3.2, 3.4, 3.6, 5.1, 5.2, 5.3, 7.6, 7.7_

  - [x] 11.2 Escribir el bloque `main` en `update.py`
    - Determinar `script_dir = Path(__file__).resolve().parent`
    - Llamar `load_config(script_dir)`; si retorna sin error, continuar
    - Verificar `actualizacion.lock`: si existe, loguear advertencia y `sys.exit(0)`
    - Crear `actualizacion.lock`
    - Llamar `setup_logger(config["log_path"])`
    - Envolver `run_pipeline` en `try/except/finally` para garantizar la eliminación del lock
    - Soportar argumento `--dry-run`: ejecutar validación + transformación, imprimir conteo de vehículos, sin sobrescribir HTML
    - _Requirements: 4.1, 4.3, 4.4, 4.5, 6.6_

- [x] 12. Checkpoint — Verificar flujo completo
  - Asegurarse de que todos los tests de las tareas 8–11 pasan. Preguntar al usuario si surge alguna duda.

- [ ] 13. Escribir tests de integración
  - [ ]* 13.1 Escribir tests end-to-end en `tests/test_integration.py`
    - Test: CSV válido con N vehículos → HTML generado contiene exactamente N registros en `DATA`
    - Test: `--dry-run` → HTML no se modifica
    - Test: lock existente → exit 0 sin modificar HTML
    - Test: CSV inexistente → exit 1 sin modificar HTML
    - Test: error de escritura → backup restaurado, HTML original intacto
    - _Requirements: 1.2, 3.6, 4.5, 6.6_

- [x] 14. Crear `config.json` y actualizar el `README`
  - [x] 14.1 Crear `config.json` en `/Users/javiereli/InventAutoStar/` con los valores por defecto apuntando a las rutas reales del proyecto
    - `csv_path`: `"./inventario.csv"`
    - `html_output_path`: `"./inventario_autostar.html"`
    - `template_path`: `"./template.html"`
    - `backup_dir`: `"./backups"`
    - `log_path`: `"./actualizacion.log"`
    - _Requirements: 6.1, 6.2_

  - [x] 14.2 Crear o actualizar `README.md` con las instrucciones de crontab para macOS/Linux
    - Incluir la entrada de crontab: `0 10 * * * /ruta/absoluta/al/python3 /Users/javiereli/InventAutoStar/update.py`
    - Incluir instrucciones para instalar dependencias (`pip install -r requirements.txt`) y cómo ajustar `config.json`
    - _Requirements: 4.2_

- [x] 15. Checkpoint final — Suite completa de tests
  - Ejecutar `pytest tests/ -v --cov=update --cov-report=term-missing` y verificar que todos los tests pasan. Preguntar al usuario si surge alguna duda.

---

## Notes

- Las tareas marcadas con `*` son opcionales y pueden omitirse para un MVP más rápido, pero se recomienda implementarlas para garantizar la corrección del pipeline.
- El orden de las tareas refleja dependencias reales: las excepciones y la configuración deben existir antes de cualquier otra función.
- La tarea 10 (crear `template.html`) puede hacerse en paralelo con las tareas 3–9.
- Los property tests usan `hypothesis`; cada propiedad tiene su número y el requisito que valida anotado directamente en el código.
- Para ejecutar los tests en modo watch durante desarrollo: `pip install pytest-watch && ptw tests/` (ejecutar manualmente en la terminal).
- El script debe ejecutarse con `python3 update.py` desde el directorio del proyecto o con ruta absoluta en el crontab.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["2.1"] },
    { "id": 1, "tasks": ["3.1", "4.1", "5.1", "10.1"] },
    { "id": 2, "tasks": ["3.2", "3.3", "4.2", "4.3", "5.2", "5.3", "6.1", "6.6", "6.9"] },
    { "id": 3, "tasks": ["6.2", "6.3", "6.4", "6.5", "6.7", "6.8", "6.10", "8.1", "9.1", "9.2"] },
    { "id": 4, "tasks": ["8.2", "8.3", "8.4", "9.3", "9.4"] },
    { "id": 5, "tasks": ["8.5", "11.1"] },
    { "id": 6, "tasks": ["11.2"] },
    { "id": 7, "tasks": ["13.1", "14.1", "14.2"] }
  ]
}
```
