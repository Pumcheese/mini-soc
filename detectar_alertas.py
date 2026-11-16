import csv
from datetime import datetime, timedelta
from pathlib import Path


UMBRAL_FALLOS = 5
VENTANA_MINUTOS = 10


def detectar_alertas(eventos, umbral=UMBRAL_FALLOS, minutos=VENTANA_MINUTOS):
    if type(umbral) is not int or umbral < 1:
        raise ValueError("El umbral debe ser un entero positivo.")
    if type(minutos) is not int or minutos < 1:
        raise ValueError("La ventana debe ser un número entero positivo de minutos.")
    ventana = timedelta(minutes=minutos)
    fallos_por_usuario = {}
    alertas = []
    eventos_ordenados = sorted(
        eventos, key=lambda evento: datetime.fromisoformat(evento["fecha_utc"])
    )

    for evento in eventos_ordenados:
        if evento["resultado"] != "FALLO":
            continue

        usuario = evento["usuario"]
        fecha = datetime.fromisoformat(evento["fecha_utc"])
        limite = fecha - ventana
        fallos_anteriores = fallos_por_usuario.get(usuario, [])
        fallos_recientes = [fallo for fallo in fallos_anteriores if fallo >= limite]
        fallos_recientes.append(fecha)
        fallos_por_usuario[usuario] = fallos_recientes

        if len(fallos_recientes) == umbral:
            alertas.append(
                {
                    "usuario": usuario,
                    "fecha_utc": evento["fecha_utc"],
                    "numero_fallos": len(fallos_recientes),
                }
            )

    return alertas


if __name__ == "__main__":
    ruta_csv = Path(__file__).resolve().parent / "datos" / "accesos.csv"
    with ruta_csv.open(encoding="utf-8", newline="") as archivo:
        alertas = detectar_alertas(csv.DictReader(archivo))

    for alerta in alertas:
        print(
            f"ALERTA | {alerta['fecha_utc']} | {alerta['usuario']} | "
            f"{alerta['numero_fallos']} fallos en los últimos "
            f"{VENTANA_MINUTOS} minutos"
        )
    print(f"Total de alertas: {len(alertas)}")
