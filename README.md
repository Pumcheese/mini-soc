# Mini SOC

Aplicación local para detectar patrones de acceso, investigar alertas y documentar conclusiones a partir de registros CSV.

Python 3.11+ · SQLite · JavaScript · HTML/CSS

![Investigación de accesos](docs/panel.jpg)

## Inicio

Desde la carpeta del proyecto, ejecuta lo siguiente y conserva la terminal abierta.

```shell
python app.py
```

En Windows se puede usar `py -3 app.py` o el lanzador de PowerShell.

```powershell
.\iniciar.ps1
```

Abre [127.0.0.1:8765](http://127.0.0.1:8765/). Para detener el servidor, pulsa Ctrl+C.

El proyecto utiliza la biblioteca estándar de Python. El primer arranque carga `datos/demostracion.csv`. Si ya existe una base de datos, recupera el último análisis.

```shell
python app.py --port 8766
python app.py --data-dir ./mis-datos
python -m unittest discover -s tests -v
```

## Uso

1. Importa un CSV o carga la demostración.
2. Ajusta el número de fallos y la ventana de tiempo, y pulsa Analizar.
3. Selecciona una cuenta para consultar los accesos previos, los fallos y el acceso posterior.
4. Documenta la investigación y guarda el estado y el veredicto.
5. Exporta el informe Markdown con las decisiones guardadas.

La tabla permite buscar por cuenta o IP y filtrar por prioridad y estado. La pestaña Registros muestra los eventos originales. Ayuda recoge el formato de importación y los criterios de análisis.

## Demostración

El conjunto de demostración contiene **40 eventos de siete cuentas ficticias**. Con cinco fallos en diez minutos genera cinco alertas.

| Cuenta      | Contexto                                                         | Prioridad  |
| ----------- | ---------------------------------------------------------------- | ---------- |
| bruno       | Acceso posterior desde una IP de los fallos distinta a la previa | Alta       |
| elena       | Fallos desde dos IP y acceso posterior desde una de ellas        | Alta       |
| svc_backup  | Acceso previo IPv4 y fallos y acceso posterior IPv6              | Alta       |
| ana         | Fallos y accesos correctos desde la misma IP                     | Media      |
| diego       | Cinco fallos en ocho minutos desde la IP del acceso previo       | Media      |
| carla, luis | Un fallo por cuenta                                              | Sin alerta |

Las direcciones pertenecen a rangos de documentación. `datos/accesos.csv` conserva un conjunto reducido de 16 eventos para comprobar la regla de forma manual.

## Formato de entrada

CSV UTF-8 con esta cabecera y en este orden.

```csv
fecha_utc,usuario,ip_origen,resultado
2026-11-10T09:00:00Z,ana,192.0.2.10,FALLO
2026-11-10T09:01:00Z,ana,192.0.2.10,EXITO
```

- Fechas ISO 8601 con zona horaria, normalizadas a UTC al importar.
- Direcciones IPv4 o IPv6 válidas.
- Resultados `EXITO` y `FALLO`.
- Hasta 2.000 eventos y 2 MB por petición.

Se admiten filas desordenadas y marca BOM UTF-8. La validación informa del error antes de guardar un análisis nuevo.

## Criterios de detección

**Ventana por cuenta.** Cada fallo actualiza la lista de fallos recientes del usuario, incluyendo el límite temporal exacto. Se genera una alerta cuando el recuento alcanza el umbral. Los cambios de IP y los accesos correctos intermedios conservan el recuento hasta que los fallos salen de la ventana.

**Repetición de alertas.** Un sexto fallo que eleva el recuento de cinco a seis mantiene el patrón. Si el recuento vuelve a bajar y después alcanza cinco, puede producir otra alerta.

**Contexto.** Para cada alerta se busca el último acceso correcto anterior al primer fallo y el primer acceso correcto posterior a la alerta dentro de otra ventana del mismo tamaño. Se asigna prioridad alta si este último usa una IP de los fallos distinta a la previa. Los demás casos tienen prioridad media y muestran el motivo correspondiente.

**Análisis retrospectivo.** El contexto se calcula con el archivo completo y puede incorporar eventos posteriores a la hora de detección. La prioridad orienta la revisión. El analista registra su veredicto y conclusión.

## Persistencia

Los registros, parámetros y decisiones se guardan en `.local/mini-soc.sqlite3`. Repetir los mismos eventos con la misma configuración recupera sus investigaciones. El selector permite abrir los 30 análisis más recientes y la URL conserva el análisis seleccionado.

Para cerrar un caso se exige un veredicto y una conclusión. El guardado comprueba la versión del caso para evitar sobrescribir una edición más reciente de otra pestaña. Si aparece un conflicto, copia las notas pendientes y recarga.

Las notas pendientes permanecen en memoria al cambiar de alerta. La aplicación avisa antes de abandonarlas y exige guardarlas antes de exportar.

## Estructura

```text
app.py                    Servidor HTTP y exportación de informes
almacen.py                Transacciones y versiones de casos en SQLite
detectar_alertas.py        Regla de fallos en ventana temporal
investigar_alertas.py      Validación y recopilación de evidencia
leer_accesos.py            Consulta del CSV reducido por terminal
web/                      Interfaz HTML, CSS y JavaScript
datos/                    Conjuntos de registros ficticios
tests/test_mini_soc.py     Pruebas del detector, persistencia y API
```

El servidor enlaza la interfaz con el detector y SQLite. La detección se puede ejecutar por separado con `python detectar_alertas.py`.

## Alcance

Análisis de archivos locales para uso individual. El servidor escucha en la interfaz de bucle local, valida el origen de las peticiones y sirve los recursos definidos por la aplicación. Los datos introducidos se muestran como texto en la interfaz.

Cada cronología presenta hasta 100 eventos relacionados y avisa cuando se recorta. El conjunto importado completo se consulta en Registros. La ingesta en directo, la autenticación multiusuario y las acciones automáticas de respuesta requerirían ampliar la arquitectura.

Las pruebas utilizan bases de datos temporales. Cubren los límites de tiempo, filas desordenadas y simultáneas, cambios de IP, validación del CSV, persistencia, conflictos de edición y exportación HTTP. Los archivos de ejecución y las bases de datos se excluyen mediante `.gitignore`.
