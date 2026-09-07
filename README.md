# Autostar · Inventario Auto-Actualización

Pipeline de actualización diaria para el inventario de vehículos seminuevos de Autostar. Descarga el CSV directamente desde AppSheet, lo transforma al formato JSON que espera la app, y regenera el archivo HTML con los datos frescos — sin servidor, sin base de datos, todo local.

---

## Cómo funciona

```
AppSheet ──► download_csv.py ──► inventario.csv ──► update.py ──► inventario_autostar.html
  (web)        (Playwright)        (disco)          CSV → JSON      (app actualizada)
```

El pipeline completo a las 10 AM:

1. Abre AppSheet automáticamente en un navegador headless.
2. Hace clic en el botón Exportar y descarga el CSV.
3. Valida columnas y limpia los datos (precios, kilómetros, campos vacíos).
4. Deduplica por VIN y normaliza el campo `grupo`.
5. Inyecta el JSON en `template.html` reemplazando el marcador `/*%%DATA%%*/`.
6. Crea backup del HTML anterior y sobrescribe `inventario_autostar.html`.

---

## Requisitos

- **Python 3.10** o superior
- Instalar dependencias:

```bash
pip install -r requirements.txt
playwright install chromium
```

---

## Configuración inicial (primera vez)

### 1. Instalar dependencias

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Guardar la sesión de Google (solo una vez)

```bash
python3 setup_session.py
```

Se abrirá un navegador visible. Inicia sesión con tu cuenta de Google y espera a que AppSheet cargue el inventario. Cierra el navegador cuando lo veas cargado. La sesión se guarda en `session.json` y dura varios meses.

### 3. Verificar que todo funciona

```bash
python3 update.py --dry-run
```

Debe imprimir algo como `[dry-run] Se procesarían 78 vehículos. HTML no modificado.`

---

## Uso

| Comando | Qué hace |
|---------|----------|
| `python3 update.py` | Descarga CSV, procesa y actualiza el HTML |
| `python3 update.py --dry-run` | Descarga CSV, procesa, pero NO sobrescribe el HTML |
| `python3 update.py --skip-download` | Usa el CSV existente en disco, sin descargar |
| `python3 download_csv.py` | Descarga el CSV sin procesar el HTML |
| `python3 download_csv.py --check` | Verifica si la sesión está activa |
| `python3 setup_session.py` | (Re)genera la sesión cuando expira |

---

## Actualización automática (crontab)

Para que el script se ejecute automáticamente todos los días a las 10:00 AM:

**1. Obtén la ruta de Python del entorno virtual:**

```bash
which python3
# o si usas el venv del proyecto:
/Users/javiereli/InventAutoStar/.venv/bin/python3 --version
```

**2. Abre el editor de crontab:**

```bash
crontab -e
```

**3. Agrega esta línea** (ajusta la ruta de python3 según el paso 1):

```
0 10 * * * /Users/javiereli/InventAutoStar/.venv/bin/python3 /Users/javiereli/InventAutoStar/update.py
```

Guarda y cierra. El sistema ejecutará el script automáticamente a las 10:00 AM todos los días, descargando el CSV e actualizando el HTML sin ninguna intervención manual.

> **Nota sobre la sesión:** Si `session.json` expira (raro, suele durar meses), el script usará el CSV del día anterior y registrará un aviso en el log. Cuando esto ocurra, ejecuta `python3 setup_session.py` para renovarla.

---

## Archivos del proyecto

| Archivo / Carpeta | Propósito |
|-------------------|-----------|
| `update.py` | Script principal. Orquesta descarga, transformación y regeneración del HTML. |
| `download_csv.py` | Descarga el CSV desde AppSheet usando Playwright. |
| `setup_session.py` | Login inicial a AppSheet (se ejecuta una sola vez). |
| `session.json` | Cookies de sesión de Google (generado por setup_session.py). **No compartir.** |
| `config.json` | Configuración de rutas del proyecto. |
| `template.html` | Template HTML con marcadores `/*%%DATA%%*/` y `%%FECHA%%`. |
| `inventario_autostar.html` | App HTML generada. Se sobrescribe en cada actualización. |
| `inventario.csv` | CSV descargado de AppSheet. Se regenera automáticamente. |
| `actualizacion.log` | Log de todas las ejecuciones (éxitos, errores, avisos). |
| `backups/` | Copias del HTML anterior. Retención: 7 días. |
| `tests/` | Suite de tests (pytest + hypothesis). |
| `requirements.txt` | Dependencias del proyecto. |

---

## Renovar la sesión cuando expira

La sesión de Google dura típicamente varios meses. Cuando expire, el log mostrará:

```
WARNING [download] Descarga fallida (SessionError: La sesión de Google ha expirado...)
```

Para renovarla:

```bash
python3 setup_session.py
```

El proceso es el mismo que la primera vez: se abre el navegador, inicias sesión, y cierras el navegador.

---

## Logs y backups

### Log de operaciones (`actualizacion.log`)

Cada ejecución registra: descarga del CSV, filas procesadas/omitidas, errores y resultado final. Se rota automáticamente al superar **1 MB** y se conservan máximo **5 archivos rotados**.

### Backups (`backups/`)

Antes de sobrescribir el HTML, se guarda una copia con nombre `inventario_autostar_YYYYMMDD_HHMMSS.html`. Retención: **7 días**. Para rollback manual, copia el backup sobre `inventario_autostar.html`.
