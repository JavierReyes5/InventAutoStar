# Requirements Document

## Introduction

El sistema actual de inventario Autostar ("Piso de unidades") es un archivo HTML estático cuyo inventario de vehículos seminuevos está hardcodeado en un array JSON (`const DATA = [...]`). Los vendedores y clientes ven datos potencialmente desactualizados cada vez que el archivo no se regenera manualmente.

Esta funcionalidad añade un pipeline de actualización automática diaria: a las 10:00 AM cada día, el sistema descargará el CSV exportado desde AppSheet, lo transformará al formato JSON requerido por el HTML, y sobreescribirá el archivo `inventario_autostar.html` con los datos frescos, manteniendo exactamente la misma interfaz visual y funcionalidad de filtrado.

---

## Glossary

- **App_HTML**: El archivo `inventario_autostar.html` que contiene la UI completa del inventario (estilos, filtros, tarjetas de vehículos) y el array `DATA`.
- **AppSheet**: Plataforma de base de datos del inventario; expone un botón "Exportar" que descarga un CSV con el inventario actualizado. URL: `https://www.appsheet.com/start/31f455dc-18f8-4f0a-b0e6-e1b71432627f`
- **CSV_Fuente**: Archivo CSV descargado desde AppSheet que contiene las columnas: `vin, inv, desc, anio, kms, color, precio, bono, garantia, ubicacion, grupo, condicion, link, tipo, estatus, foraneo, cil, lts, trans`.
- **JSON_Inventario**: Array JavaScript `DATA` embebido dentro del App_HTML; contiene los registros de todos los vehículos seminuevos.
- **Script_Actualizacion**: Script de línea de comandos (Python o Node.js) que orquesta la descarga del CSV, la transformación a JSON y la regeneración del App_HTML.
- **Scheduler**: Componente del sistema operativo (cron en macOS/Linux) que ejecuta el Script_Actualizacion automáticamente a las 10:00 AM todos los días.
- **Template_HTML**: Versión del archivo HTML donde el bloque `const DATA = [...]` ha sido reemplazado por un marcador de posición (`/*%%DATA%%*/`), permitiendo la inserción programática del JSON_Inventario actualizado.
- **Backup**: Copia del App_HTML anterior al proceso de actualización, guardada con marca de tiempo para permitir rollback manual.
- **Log_Actualizacion**: Archivo de texto que registra cada ejecución del Script_Actualizacion con su resultado (éxito o error).

---

## Requirements

### Requerimiento 1: Descarga del CSV desde AppSheet

**User Story:** Como administrador del inventario, quiero que el sistema descargue automáticamente el CSV exportado de AppSheet, para que los datos del inventario siempre reflejen la información más reciente sin intervención manual.

#### Criterios de Aceptación

1. WHEN el Script_Actualizacion se ejecuta, THE Script_Actualizacion SHALL leer la ruta local del CSV_Fuente desde un archivo de configuración o variable de entorno, no como valor hardcodeado en el código fuente.
2. WHEN el CSV_Fuente no existe en la ruta configurada, THEN THE Script_Actualizacion SHALL registrar en el Log_Actualizacion un mensaje de error que incluya la ruta configurada y el motivo del fallo, y SHALL terminar sin modificar el App_HTML.
3. WHEN el CSV_Fuente tiene una fecha de modificación anterior a las 24 horas previas a la ejecución, THEN THE Script_Actualizacion SHALL registrar una advertencia en el Log_Actualizacion indicando que el CSV puede estar desactualizado (incluyendo la fecha de modificación del archivo), y SHALL continuar con el proceso de actualización.
4. WHEN el Script_Actualizacion abre el CSV_Fuente, THE Script_Actualizacion SHALL validar que el encabezado contiene al menos las columnas obligatorias: `vin, inv, desc, anio, kms, color, precio, tipo, estatus, grupo`.
5. IF el CSV_Fuente no contiene alguna de las columnas obligatorias, THEN THE Script_Actualizacion SHALL registrar los nombres de las columnas faltantes en el Log_Actualizacion y SHALL terminar sin modificar el App_HTML.
6. IF el CSV_Fuente existe pero está vacío o tiene tamaño cero bytes, THEN THE Script_Actualizacion SHALL registrar en el Log_Actualizacion que el archivo está vacío y SHALL terminar sin modificar el App_HTML.

---

### Requerimiento 2: Transformación de CSV a JSON

**User Story:** Como desarrollador del sistema, quiero que el CSV de AppSheet se transforme correctamente al formato JSON esperado por el App_HTML, para que los datos se muestren correctamente en la interfaz.

#### Criterios de Aceptación

1. WHEN el Script_Actualizacion procesa el CSV_Fuente, THE Script_Actualizacion SHALL convertir cada fila en un objeto JSON con las propiedades: `vin, inv, desc, anio, kms, color, precio, bono, garantia, ubicacion, grupo, condicion, link, tipo, estatus, foraneo, cil, lts, trans`.
2. WHEN una celda del CSV_Fuente para el campo `precio` está vacía, contiene solo espacios en blanco, o contiene un valor que no puede interpretarse como número decimal (incluyendo valores con símbolos de moneda o separadores de miles no estándar), THE Script_Actualizacion SHALL asignar el valor `0.0` al campo `precio` del objeto JSON correspondiente.
3. WHEN una celda del CSV_Fuente para el campo `kms` está vacía, contiene solo espacios en blanco, o contiene un valor que no puede interpretarse como número entero no negativo, THE Script_Actualizacion SHALL asignar el valor `0` al campo `kms` del objeto JSON correspondiente.
4. WHEN una celda del CSV_Fuente para cualquier campo de texto opcional (`bono, garantia, condicion, link, foraneo, cil, lts, trans`) está vacía, THE Script_Actualizacion SHALL asignar una cadena vacía `""` al campo correspondiente del objeto JSON.
5. THE Script_Actualizacion SHALL producir un JSON_Inventario serializado como un array JSON válido, sin comentarios, que pueda ser parseado por `JSON.parse()` sin errores.
6. WHEN el CSV_Fuente contiene filas con el campo `vin` vacío, THE Script_Actualizacion SHALL omitir esas filas del JSON_Inventario y SHALL registrar en el Log_Actualizacion el número total de filas omitidas y el índice de cada fila omitida (número de fila en el CSV_Fuente, contando desde 1 sin incluir la fila de encabezado).
7. IF el CSV_Fuente no está disponible, está vacío, o no contiene una fila de encabezado válida con al menos las columnas requeridas, THEN THE Script_Actualizacion SHALL detener el procesamiento sin generar el JSON_Inventario y SHALL registrar en el Log_Actualizacion la causa del error indicando cuál condición no se cumplió.
8. WHEN el CSV_Fuente contiene más de una fila con el mismo valor no vacío en el campo `vin`, THE Script_Actualizacion SHALL conservar únicamente la primera ocurrencia de ese `vin` en el JSON_Inventario, omitir las filas duplicadas subsecuentes, y SHALL registrar en el Log_Actualizacion el número total de filas duplicadas omitidas y el valor de `vin` de cada una.

---

### Requerimiento 3: Regeneración del archivo HTML

**User Story:** Como administrador del inventario, quiero que el archivo HTML se regenere automáticamente con los datos frescos, para que la app muestre el inventario actualizado sin necesidad de editar el archivo manualmente.

#### Criterios de Aceptación

1. THE Script_Actualizacion SHALL mantener un Template_HTML separado del App_HTML, donde el bloque `const DATA = [...]` contiene exactamente un marcador de posición `/*%%DATA%%*/` y ningún otro contenido dinámico fuera de ese bloque.
2. WHEN el Script_Actualizacion ejecuta la regeneración, THE Script_Actualizacion SHALL crear un Backup del App_HTML actual con el sufijo de marca de tiempo en formato `YYYYMMDD_HHMMSS` antes de sobrescribir el archivo, verificando que el Backup resultante sea idéntico en tamaño de bytes al App_HTML original antes de continuar.
3. WHEN el Script_Actualizacion regenera el App_HTML, THE Script_Actualizacion SHALL reemplazar exactamente el marcador `/*%%DATA%%*/` en el Template_HTML con el JSON_Inventario generado, produciendo un App_HTML funcionalmente idéntico en estructura HTML, CSS y JavaScript al original.
4. WHEN la regeneración del App_HTML se completa sin errores, THE Script_Actualizacion SHALL actualizar la línea del footer en el App_HTML generado con la fecha de la última actualización en formato `DD MMM YYYY` en español, donde DD es el día con dos dígitos, MMM es la abreviatura del mes en español (ene, feb, mar, abr, may, jun, jul, ago, sep, oct, nov, dic) y YYYY es el año con cuatro dígitos.
5. IF el Script_Actualizacion no encuentra exactamente una ocurrencia del marcador `/*%%DATA%%*/` en el Template_HTML, THEN THE Script_Actualizacion SHALL abortar la regeneración sin modificar el App_HTML y SHALL registrar el error en el Log_Actualizacion indicando la cantidad de ocurrencias encontradas.
6. IF ocurre cualquier error durante la escritura del App_HTML, THEN THE Script_Actualizacion SHALL restaurar el Backup creado en el paso 2, verificar que el App_HTML restaurado sea idéntico en tamaño de bytes al Backup, y SHALL registrar el error en el Log_Actualizacion.
7. THE Script_Actualizacion SHALL conservar los Backups de los últimos 7 días calendario y SHALL eliminar los Backups cuya marca de tiempo sea anterior a las 00:00:00 del día que resulta de restar 7 días a la fecha actual al momento de ejecutar la limpieza.

---

### Requerimiento 4: Programación automática diaria (Scheduler)

**User Story:** Como administrador del inventario, quiero que la actualización ocurra automáticamente todos los días a las 10:00 AM, para no depender de ejecutar el script manualmente.

#### Criterios de Aceptación

1. THE Script_Actualizacion SHALL poder ejecutarse desde la línea de comandos como un comando único sin parámetros requeridos, utilizando los valores del archivo de configuración.
2. IF el sistema operativo es macOS o Linux, THEN el README del proyecto SHALL incluir instrucciones para agregar la entrada de crontab `0 10 * * * /ruta/absoluta/al/script` para ejecutar el Script_Actualizacion a las 10:00 AM todos los días.
3. WHEN el Script_Actualizacion inicia su ejecución, THE Script_Actualizacion SHALL crear un archivo de lock llamado `actualizacion.lock` en el directorio de trabajo del script.
4. WHEN el Script_Actualizacion termina (con éxito o con error), THE Script_Actualizacion SHALL eliminar el archivo `actualizacion.lock` del directorio de trabajo del script.
5. IF el archivo `actualizacion.lock` existe cuando el Scheduler intenta ejecutar el Script_Actualizacion, THEN THE Script_Actualizacion SHALL registrar en el Log_Actualizacion una advertencia indicando que ya hay una ejecución en progreso, y SHALL terminar con código de salida 0 sin realizar ninguna acción adicional.

---

### Requerimiento 5: Registro de operaciones (Logging)

**User Story:** Como administrador del sistema, quiero que cada ejecución quede registrada en un log, para poder diagnosticar problemas y confirmar que las actualizaciones se realizaron correctamente.

#### Criterios de Aceptación

1. THE Script_Actualizacion SHALL escribir una entrada en el Log_Actualizacion al inicio de cada ejecución con: marca de tiempo en formato ISO 8601, versión del script, y ruta absoluta del CSV_Fuente procesado.
2. WHEN el Script_Actualizacion completa una actualización exitosa, THE Script_Actualizacion SHALL registrar en el Log_Actualizacion: número de vehículos procesados, número de filas omitidas con sus números de fila correspondientes, y ruta absoluta del App_HTML generado.
3. IF el Script_Actualizacion termina con error, THEN THE Script_Actualizacion SHALL registrar en el Log_Actualizacion: el tipo de error, el mensaje de error completo, y el nombre del paso en el que falló, y SHALL finalizar la ejecución sin sobrescribir el App_HTML existente.
4. IF el tamaño del Log_Actualizacion supera 1 MB al iniciar una ejecución, THEN THE Script_Actualizacion SHALL renombrar el archivo actual agregando un sufijo de marca de tiempo en formato ISO 8601 y crear un nuevo archivo Log_Actualizacion vacío antes de escribir la entrada de inicio.
5. THE Log_Actualizacion SHALL almacenarse en la misma carpeta que el App_HTML, con el nombre `actualizacion.log`.
6. THE Script_Actualizacion SHALL conservar un máximo de 5 archivos de log rotados; si al rotar ya existen 5 archivos rotados previos, el más antiguo deberá eliminarse antes de crear el nuevo archivo de log vacío.

---

### Requerimiento 6: Configuración del sistema

**User Story:** Como administrador del sistema, quiero poder configurar las rutas y parámetros del sistema desde un único archivo, para poder adaptar el sistema sin modificar el código fuente.

#### Criterios de Aceptación

1. WHEN el Script_Actualizacion se ejecuta, THE Script_Actualizacion SHALL leer su configuración desde un archivo `config.json` ubicado en la misma carpeta que el script, con los campos: `csv_path` (ruta al CSV_Fuente), `html_output_path` (ruta al App_HTML), `template_path` (ruta al Template_HTML), `backup_dir` (carpeta de backups), `log_path` (ruta al Log_Actualizacion).
2. WHEN el archivo `config.json` no existe, THE Script_Actualizacion SHALL crear un `config.json` con los siguientes valores por defecto: `csv_path: "./inventario.csv"`, `html_output_path: "./inventario_autostar.html"`, `template_path: "./template.html"`, `backup_dir: "./backups"`, `log_path: "./actualizacion.log"`, SHALL imprimir en consola un mensaje indicando que se creó el archivo de configuración con valores por defecto y que el usuario debe ajustar las rutas antes de ejecutar nuevamente, y SHALL terminar sin realizar el proceso de actualización.
3. IF el archivo `config.json` existe pero le falta alguno de los cinco campos requeridos (`csv_path`, `html_output_path`, `template_path`, `backup_dir`, `log_path`), THEN THE Script_Actualizacion SHALL imprimir en consola los nombres de los campos faltantes y SHALL terminar sin realizar el proceso de actualización.
4. WHEN cualquier ruta en `config.json` es relativa, THE Script_Actualizacion SHALL resolverla relativa a la ubicación del archivo `config.json`.
5. IF cualquier ruta resuelta en `config.json` apunta a una ubicación inaccesible (directorio padre inexistente o sin permisos de escritura), THEN THE Script_Actualizacion SHALL imprimir en consola el nombre del campo y la ruta inaccesible, y SHALL terminar sin realizar el proceso de actualización.
6. WHERE el Script_Actualizacion se invoca con el argumento `--dry-run`, THE Script_Actualizacion SHALL ejecutar las etapas de lectura del CSV_Fuente, transformación a JSON y validación del JSON_Inventario, pero NO SHALL sobrescribir el App_HTML, e SHALL imprimir en consola el número de vehículos que se procesarían.

---

### Requerimiento 7: Paridad visual y funcional del HTML generado

**User Story:** Como usuario de la app, quiero que el HTML regenerado automáticamente sea visualmente idéntico y funcionalmente equivalente al original, para que la experiencia no cambie al actualizar los datos.

#### Criterios de Aceptación

1. THE Script_Actualizacion SHALL preservar sin modificación todos los bloques de CSS, HTML estructural y código JavaScript del Template_HTML al generar el App_HTML, con excepción del valor del array `DATA` y la fecha del footer.
2. WHEN el JSON_Inventario generado se inserta en el App_HTML, THE Script_Actualizacion SHALL verificar que el archivo resultante contiene la cadena `const DATA = [` seguida de un array JSON con al menos un elemento.
3. IF la verificación del criterio 2 falla, THEN THE Script_Actualizacion SHALL abortar la escritura del App_HTML y SHALL registrar el error en el Log_Actualizacion indicando que el array DATA no se insertó correctamente.
4. THE Script_Actualizacion SHALL verificar que el tamaño del App_HTML generado es mayor a 10 KB, como guardia mínima contra truncamiento accidental del archivo.
5. IF la verificación del criterio 4 falla (tamaño ≤ 10 KB), THEN THE Script_Actualizacion SHALL abortar la escritura del App_HTML y SHALL registrar el error en el Log_Actualizacion indicando el tamaño real del archivo generado.
6. THE Script_Actualizacion SHALL validar, antes de insertar el JSON_Inventario en el Template_HTML, que todos los registros del JSON_Inventario tienen el campo `grupo` con uno de los valores: `"Mexicali"`, `"Tijuana"`, u `"Otro"`.
7. IF algún registro del JSON_Inventario tiene un valor de `grupo` diferente a `"Mexicali"`, `"Tijuana"` o `"Otro"`, THEN THE Script_Actualizacion SHALL registrar en el Log_Actualizacion el VIN del registro y el valor de `grupo` inválido encontrado, y SHALL asignar el valor `"Otro"` a ese campo antes de continuar con la inserción.
