# Escenarios de investigación

Los registros son ficticios. Una alerta identifica un patrón que merece revisión; no demuestra quién utilizó una cuenta.

| Escenario | Resultado esperado | Qué debe comprobar el analista |
| --- | --- | --- |
| Cinco fallos en diez minutos, desde la IP habitual | Alerta media | Si la persona olvidó la contraseña o reconoce esos intentos. |
| Fallos desde otra IP y éxito posterior desde esa IP | Alerta alta si existe un acceso previo desde otra IP | Si hubo VPN, cambio de red o un acceso no reconocido. |
| Primero éxito habitual y después éxito desde la IP sospechosa | Alerta alta; ambos éxitos quedan en la ventana de contexto | No dar el caso por legítimo tras revisar solo el primer éxito. |
| Cinco filas idénticas | Alerta y aviso de duplicados | Si la exportación se repitió o si son eventos reales distintos. No se eliminan filas automáticamente. |
| Eventos simultáneos | Orden reproducible y aviso | La fecha por sí sola no permite deducir qué evento ocurrió primero. |
| IP sospechosa sin acceso previo con el que comparar | Alerta media con explicación de contexto insuficiente | Buscar más registros. La prioridad media no significa que el acceso sea seguro. |
| Intentos lentos que no alcanzan el umbral | Puede no haber alerta | Limitación de la regla temporal. |
| Un intento por cada una de muchas cuentas | Puede no haber alerta | No hay regla de password spraying entre cuentas. |

## Ejemplo de conclusión

Se observan cinco fallos desde 198.51.100.45 y después un acceso correcto desde esa IP. El acceso previo era de 192.0.2.20. Mantengo el caso en revisión hasta confirmar si el usuario reconoce el acceso y si cambió de red. La IP y el recuento son indicios; no permiten atribuir el acceso.

## Qué conservar

El CSV original en una ubicación segura, el informe con los parámetros y las fechas, y las comprobaciones que justifican la conclusión. El hash registrado por Mini SOC corresponde al texto recibido y no sustituye el original. La aplicación no incorpora cadena de custodia ni conserva el historial completo de notas.
