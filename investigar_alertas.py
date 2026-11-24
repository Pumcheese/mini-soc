"""Valida registros y reúne la evidencia de las alertas del detector."""

import csv
import io
from collections import Counter
from datetime import datetime, timezone
from ipaddress import ip_address

from detectar_alertas import clave_evento, desplazar_fecha, detectar_alertas


CAMPOS = ["fecha_utc", "usuario", "ip_origen", "resultado"]
MAX_EVENTOS = 2000


def leer_csv(texto):
    lector = csv.DictReader(io.StringIO(texto.lstrip("\ufeff"), newline=""))
    if lector.fieldnames != CAMPOS:
        raise ValueError("La cabecera debe ser fecha_utc,usuario,ip_origen,resultado.")

    eventos = []
    for numero, fila in enumerate(lector, start=2):
        if len(eventos) >= MAX_EVENTOS:
            raise ValueError(f"El archivo admite como máximo {MAX_EVENTOS} eventos.")
        if None in fila or any(fila[campo] is None for campo in CAMPOS):
            raise ValueError(f"Fila {numero}: debe contener exactamente cuatro campos.")
        evento = {campo: fila[campo].strip() for campo in CAMPOS}
        try:
            fecha = datetime.fromisoformat(evento["fecha_utc"])
            if fecha.tzinfo is None or fecha.utcoffset() is None:
                raise ValueError("falta la zona horaria")
            evento["fecha_utc"] = (
                fecha.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            )
            evento["ip_origen"] = str(ip_address(evento["ip_origen"]))
        except (ValueError, OverflowError) as error:
            raise ValueError(
                f"Fila {numero}: revisa la fecha con zona horaria y la IP."
            ) from error
        if not evento["usuario"] or len(evento["usuario"]) > 80:
            raise ValueError(
                f"Fila {numero}: el usuario debe tener entre 1 y 80 caracteres."
            )
        if any(ord(caracter) < 32 for caracter in evento["usuario"]):
            raise ValueError(
                f"Fila {numero}: el usuario contiene caracteres de control."
            )
        if evento["resultado"] not in {"EXITO", "FALLO"}:
            raise ValueError(f"Fila {numero}: el resultado debe ser EXITO o FALLO.")
        eventos.append(evento)

    if not eventos:
        raise ValueError("El CSV necesita al menos un evento.")
    return sorted(eventos, key=clave_evento)


def advertencias_datos(eventos):
    """Informa sin eliminar registros que podrían representar accesos distintos."""
    repetidos = sum(
        n - 1 for n in Counter(tuple(e[c] for c in CAMPOS) for e in eventos).values()
    )
    fechas = Counter(e["fecha_utc"] for e in eventos)
    avisos = []
    if repetidos:
        avisos.append(
            f"Hay {repetidos} filas repetidas. Se conservan y cuentan en la regla; revisa si la fuente está duplicada."
        )
    if any(n > 1 for n in fechas.values()):
        avisos.append(
            "Hay eventos simultáneos. El orden de presentación es determinista y no acredita el orden real de los accesos."
        )
    return avisos


def investigar(eventos, umbral, minutos):
    eventos = sorted(eventos, key=clave_evento)
    por_usuario = {}
    for evento in eventos:
        por_usuario.setdefault(evento["usuario"], []).append(evento)

    casos = []
    for alerta in detectar_alertas(eventos, umbral, minutos):
        fecha_alerta = datetime.fromisoformat(alerta["fecha_utc"])
        limite = desplazar_fecha(fecha_alerta, -minutos)
        fin_ventana = desplazar_fecha(fecha_alerta, minutos)
        actividad = por_usuario[alerta["usuario"]]
        fallos = [
            evento
            for evento in actividad
            if evento["resultado"] == "FALLO"
            and limite <= datetime.fromisoformat(evento["fecha_utc"]) <= fecha_alerta
        ][:umbral]
        primer_fallo = datetime.fromisoformat(fallos[0]["fecha_utc"])
        anteriores = [
            evento
            for evento in actividad
            if evento["resultado"] == "EXITO"
            and datetime.fromisoformat(evento["fecha_utc"]) < primer_fallo
        ]
        posteriores = [
            evento
            for evento in actividad
            if evento["resultado"] == "EXITO"
            and fecha_alerta
            < datetime.fromisoformat(evento["fecha_utc"])
            <= fin_ventana
        ]
        anterior = anteriores[-1] if anteriores else None
        ips_fallos = sorted({evento["ip_origen"] for evento in fallos})
        sospechosos = [
            evento
            for evento in posteriores
            if anterior
            and evento["ip_origen"] != anterior["ip_origen"]
            and evento["ip_origen"] in ips_fallos
        ]
        # Destaca el primer éxito que cumple el criterio, aunque antes haya otro legítimo.
        posterior = (sospechosos or posteriores or [None])[0]
        ip_distinta = bool(
            anterior and any(ip != anterior["ip_origen"] for ip in ips_fallos)
        )
        acceso_nuevo = bool(
            anterior
            and posterior
            and posterior["ip_origen"] != anterior["ip_origen"]
            and posterior["ip_origen"] in ips_fallos
        )
        prioridad = "alta" if acceso_nuevo else "media"
        if acceso_nuevo:
            motivo = "Acceso correcto posterior desde una IP de los fallos, distinta a la del acceso previo."
        elif ip_distinta:
            motivo = "Los fallos incluyen una IP distinta a la del último acceso correcto previo."
        elif anterior:
            motivo = "Los fallos proceden de la misma IP que el último acceso correcto previo."
        else:
            motivo = "Falta un acceso correcto anterior con el que comparar las IP."

        cronologia = ([anterior] if anterior else []) + [
            evento
            for evento in actividad
            if primer_fallo
            <= datetime.fromisoformat(evento["fecha_utc"])
            <= fin_ventana
        ]
        casos.append(
            {
                **alerta,
                "prioridad": prioridad,
                "motivo": motivo,
                "ips_fallos": ips_fallos,
                "acceso_anterior": anterior,
                "acceso_posterior": posterior,
                "exitos_posteriores": len(posteriores),
                "fin_ventana": fin_ventana.isoformat().replace("+00:00", "Z"),
                "cronologia": cronologia[:100],
                "total_cronologia": len(cronologia),
            }
        )
    return casos
