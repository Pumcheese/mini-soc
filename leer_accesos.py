import csv
from pathlib import Path


ruta_csv = Path(__file__).resolve().parent / "datos" / "accesos.csv"

with ruta_csv.open(encoding="utf-8", newline="") as archivo:
    eventos = csv.DictReader(archivo)

    print("Fecha (UTC)           Usuario  IP de origen     Resultado")
    for evento in eventos:
        fecha = evento["fecha_utc"]
        usuario = evento["usuario"]
        ip = evento["ip_origen"]
        resultado = evento["resultado"]
        print(f"{fecha:<21} {usuario:<8} {ip:<16} {resultado}")
