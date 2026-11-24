# Funcionamiento y almacenamiento

## Detección

**Ventana por cuenta.** Cada fallo actualiza la lista de fallos recientes del usuario, incluyendo el límite temporal exacto. Se genera una alerta cuando el recuento alcanza el umbral. Los cambios de IP y los accesos correctos intermedios conservan el recuento hasta que los fallos salen de la ventana.

**Repetición de alertas.** Un sexto fallo que eleva el recuento de cinco a seis mantiene el patrón. Si el recuento vuelve a bajar y después alcanza cinco, puede producir otra alerta.

**Contexto.** Se compara el último acceso correcto anterior al primer fallo con todos los éxitos que ocurren después de la alerta, dentro de una ventana del mismo tamaño. La prioridad es alta si alguno usa una IP de los fallos distinta a la previa. Se destaca el primero que cumple ese criterio; si no existe, se muestra el primer éxito de la ventana. La cronología conserva el contexto hasta el final de esa ventana. Un indicio de prioridad alta no confirma una intrusión.

**Análisis retrospectivo.** El contexto se calcula con el archivo completo y puede incorporar eventos posteriores a la hora de detección. La prioridad orienta la revisión. El analista registra su veredicto y conclusión.

## Calidad de los datos

Las filas idénticas se conservan y cuentan en la detección. La interfaz y el informe avisan de repeticiones para que el analista compruebe la fuente. Sin un identificador de evento no se puede distinguir con certeza una duplicación de dos accesos iguales.

Los empates de fecha se ordenan por cuenta, resultado e IP para obtener el mismo análisis al reordenar un CSV. Este desempate no permite conocer el orden real de eventos simultáneos. La comparación de accesos previos y posteriores utiliza instantes estrictamente anteriores y posteriores. Las fracciones de segundo se conservan.

Las ventanas se recortan en los límites representables de fecha. Una conversión a UTC fuera de ese rango se rechaza antes de guardar.

## Persistencia

Los registros, parámetros y decisiones se guardan en `.local/mini-soc.sqlite3`. Repetir los mismos eventos con la misma configuración recupera sus investigaciones. El selector permite abrir los 30 análisis más recientes y la URL conserva el análisis seleccionado.

Para cerrar un caso se exige un veredicto y una conclusión. El guardado comprueba la versión del caso para evitar sobrescribir una edición más reciente de otra pestaña. Si aparece un conflicto, copia las notas pendientes y recarga.

El motor 1.1 recalcula el contexto de los análisis guardados sin sobrescribir sus IDs, notas, estados, versiones ni veredictos. Si la evidencia cambia, revisa la conclusión anterior. No se fusionan análisis antiguos que ya estuvieran duplicados: se mantienen sus decisiones separadas. Antes de actualizar una instalación con investigaciones, conserva una copia de su base de datos con el servidor detenido.

Las nuevas importaciones registran nombre, fecha y SHA-256 del texto UTF-8 recibido. El navegador puede retirar un BOM al decodificar: este hash no garantiza identidad byte a byte con el archivo original. No se guarda el CSV bruto ni se certifica su autenticidad. Los análisis antiguos no tienen un hash de origen recuperable; cambiar la regla no inventa uno. Los registros normalizados no equivalen a una copia forense.

Las notas pendientes permanecen en memoria al cambiar de alerta. La aplicación avisa antes de abandonarlas y exige guardarlas antes de exportar.

