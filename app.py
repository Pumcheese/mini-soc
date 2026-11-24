"""Servidor HTTP local e informes de investigación del Mini SOC."""

import argparse
import csv
import io
import json
import logging
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from almacen import Almacen, ConflictoEdicion


RAIZ = Path(__file__).resolve().parent
CSV_DEMO = RAIZ / "datos" / "demostracion.csv"
MAX_BYTES = 2 * 1024 * 1024
ARCHIVOS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/estilos.css": ("estilos.css", "text/css; charset=utf-8"),
}
ESTADOS = {"nueva": "Nueva", "en_revision": "En revisión", "cerrada": "Cerrada"}
VEREDICTOS = {
    "pendiente": "Pendiente",
    "legitimo": "Actividad legítima",
    "sospechoso": "Actividad sospechosa",
    "inconcluso": "Inconcluso",
}


def texto_markdown(texto):
    """Exporta texto literal, incluidos HTML y sintaxis de enlaces importados."""
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    lineas = []
    for linea in texto.split("\n"):
        literal = re.sub(r"([\\`*_{}\[\]()<>#+!:|~])", r"\\\1", linea)
        literal = re.sub(r"^(\s*)([-=])", r"\1\\\2", literal)
        literal = re.sub(r"^(\s*\d+)\.(\s)", r"\1\\.\2", literal)
        lineas.append(literal)
    return "\n".join(lineas)


def informe(analisis):
    lineas = [
        "# Mini SOC · Informe de investigación",
        "",
        f"Archivo analizado — {texto_markdown(analisis['nombre'])}",
        f"Motor de contexto — {analisis.get('version_motor', '1.0')}",
        f"Análisis creado — {analisis['fecha']}",
        f"Regla — {analisis['umbral']} fallos en {analisis['minutos']} minutos por cuenta",
        f"Eventos — {len(analisis['eventos'])}",
        f"Alertas — {len(analisis['casos'])}",
        "",
        "La prioridad se calcula a partir de los registros. El veredicto recoge la decisión del analista.",
        "",
    ]
    for aviso in analisis.get("advertencias", []):
        lineas.extend([f"Aviso — {texto_markdown(aviso)}", ""])
    lineas.extend(
        [
            "## Procedencia",
            "",
            "SHA-256 del texto UTF-8 recibido; no acredita autenticidad ni conserva el archivo original.",
            "",
        ]
    )
    for fuente in analisis.get("fuentes", []):
        lineas.append(
            f"- {texto_markdown(fuente['nombre'])} · {fuente['fecha']} · `{fuente['sha256']}`"
        )
    if not analisis.get("fuentes"):
        lineas.append(
            "Análisis anterior al registro de procedencia. El hash original no está disponible."
        )
    lineas.extend(
        [
            "",
            "El contexto se recalcula con el motor actual; las decisiones guardadas no se modifican.",
            "",
        ]
    )
    for caso in analisis["casos"]:
        lineas.extend(
            [
                f"## Cuenta {texto_markdown(caso['usuario'])}",
                "",
                f"Alerta — {caso['fecha_utc']}",
                f"Prioridad — {caso['prioridad']}",
                f"Motivo — {caso['motivo']}",
                f"Estado — {ESTADOS[caso['estado']]}",
                f"Veredicto — {VEREDICTOS[caso['veredicto']]}",
                f"Última actualización — {caso['actualizado']}",
                f"Acceso posterior destacado — {caso['acceso_posterior']['fecha_utc'] + ' · ' + caso['acceso_posterior']['ip_origen'] if caso['acceso_posterior'] else 'Sin registro en la ventana'}",
                f"Accesos correctos posteriores en la ventana — {caso.get('exitos_posteriores', 0)}",
                "",
                "### Evidencia",
                "",
            ]
        )
        for evento in caso["cronologia"]:
            lineas.append(
                f"- {evento['fecha_utc']} · {texto_markdown(evento['usuario'])} · {evento['ip_origen']} · {evento['resultado']}"
            )
        if caso["total_cronologia"] > len(caso["cronologia"]):
            lineas.append(
                f"Se muestran {len(caso['cronologia'])} de {caso['total_cronologia']} eventos relacionados."
            )
        lineas.extend(
            [
                "",
                "### Conclusión del analista",
                "",
                (
                    texto_markdown(caso["notas"])
                    if caso["notas"]
                    else "Pendiente de documentar."
                ),
                "",
            ]
        )
    return "\n".join(lineas)


def eventos_a_csv(eventos):
    salida = io.StringIO(newline="")
    escritor = csv.DictWriter(
        salida, fieldnames=["fecha_utc", "usuario", "ip_origen", "resultado"]
    )
    escritor.writeheader()
    escritor.writerows(eventos)
    return salida.getvalue()


def crear_servidor(puerto=8765, directorio_datos=None):
    directorio = Path(directorio_datos) if directorio_datos else RAIZ / ".local"
    almacen = Almacen(directorio / "mini-soc.sqlite3")
    if almacen.obtener() is None:
        almacen.analizar(CSV_DEMO.read_text(encoding="utf-8"), CSV_DEMO.name, 5, 10)

    class Manejador(BaseHTTPRequestHandler):
        def responder(
            self,
            contenido,
            tipo="application/json; charset=utf-8",
            codigo=200,
            descarga=None,
        ):
            if tipo.startswith("application/json"):
                contenido = json.dumps(contenido, ensure_ascii=False)
            cuerpo = (
                contenido if isinstance(contenido, bytes) else contenido.encode("utf-8")
            )
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            )
            if descarga:
                self.send_header(
                    "Content-Disposition", f'attachment; filename="{descarga}"'
                )
            self.end_headers()
            self.wfile.write(cuerpo)

        def comprobar_origen(self):
            puerto_real = self.server.server_address[1]
            hosts = {f"127.0.0.1:{puerto_real}", f"localhost:{puerto_real}"}
            if self.headers.get("Host") not in hosts:
                raise PermissionError("Usa la dirección local que muestra la terminal.")
            origen = self.headers.get("Origin")
            if origen and origen not in {f"http://{host}" for host in hosts}:
                raise PermissionError("La petición debe proceder del panel local.")

        def atender(self, operacion):
            try:
                self.comprobar_origen()
                operacion()
            except ValueError as error:
                self.responder({"error": str(error)}, codigo=400)
            except OverflowError:
                self.responder(
                    {
                        "error": "La fecha o la ventana temporal está fuera del rango admitido."
                    },
                    codigo=400,
                )
            except csv.Error:
                self.responder(
                    {
                        "error": "CSV inválido. Revisa las comillas, los separadores y la longitud de los campos."
                    },
                    codigo=400,
                )
            except KeyError:
                self.responder(
                    {"error": "El análisis o caso solicitado no existe."}, codigo=404
                )
            except PermissionError as error:
                self.responder({"error": str(error)}, codigo=403)
            except ConflictoEdicion as error:
                self.responder({"error": str(error)}, codigo=409)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except sqlite3.Error:
                logging.exception("No se pudo completar la operación de SQLite")
                self.responder(
                    {
                        "error": "No se pudo guardar o leer la base de datos. Inténtalo de nuevo."
                    },
                    codigo=503,
                )

        def do_GET(self):
            self.atender(self.leer)

        def leer(self):
            url = urlsplit(self.path)
            parametros = parse_qs(url.query)
            analisis_id = parametros.get("analisis", [None])[0]
            if url.path in ARCHIVOS:
                nombre, tipo = ARCHIVOS[url.path]
                self.responder((RAIZ / "web" / nombre).read_bytes(), tipo)
            elif url.path == "/api/estado":
                self.responder(almacen.obtener(analisis_id))
            elif url.path == "/api/informe":
                self.responder(
                    informe(almacen.obtener(analisis_id)),
                    "text/markdown; charset=utf-8",
                    descarga="informe-mini-soc.md",
                )
            elif url.path == "/api/ejemplo":
                self.responder(
                    CSV_DEMO.read_bytes(),
                    "text/csv; charset=utf-8",
                    descarga=CSV_DEMO.name,
                )
            else:
                self.responder({"error": "Ruta no encontrada."}, codigo=404)

        def do_POST(self):
            self.atender(self.escribir)

        def escribir(self):
            if self.headers.get_content_type() != "application/json":
                raise ValueError("La petición debe enviar JSON.")
            longitud = int(self.headers.get("Content-Length", "0"))
            if not 0 < longitud <= MAX_BYTES:
                raise ValueError("La petición debe contener entre 1 byte y 2 MB.")
            datos = json.loads(self.rfile.read(longitud).decode("utf-8"))
            if not isinstance(datos, dict):
                raise ValueError("El cuerpo debe ser un objeto JSON.")
            ruta = urlsplit(self.path).path
            if ruta in {"/api/analizar", "/api/demo"}:
                umbral = datos.get("umbral", 5)
                minutos = datos.get("minutos", 10)
                if ruta == "/api/demo":
                    texto = CSV_DEMO.read_text(encoding="utf-8")
                    nombre = CSV_DEMO.name
                elif "csv" in datos:
                    texto = datos["csv"]
                    nombre = datos.get("nombre", "importacion.csv")
                else:
                    anterior = almacen.obtener(datos.get("analisis_id"))
                    texto = eventos_a_csv(anterior["eventos"])
                    nombre = anterior["nombre"]
                if not isinstance(texto, str):
                    raise ValueError("El contenido CSV debe ser texto.")
                identidad = almacen.analizar(
                    texto,
                    nombre,
                    umbral,
                    minutos,
                    registrar_fuente=ruta == "/api/demo" or "csv" in datos,
                )
                self.responder(almacen.obtener(identidad))
            elif ruta == "/api/casos":
                identidad = datos.get("id")
                if not isinstance(identidad, str):
                    raise ValueError("Indica el identificador del caso.")
                self.responder(
                    almacen.guardar(
                        identidad,
                        datos.get("estado"),
                        datos.get("veredicto"),
                        datos.get("notas"),
                        datos.get("version"),
                    )
                )
            else:
                self.responder({"error": "Ruta no encontrada."}, codigo=404)

        def log_message(self, formato, *argumentos):
            logging.info(formato, *argumentos)

    return ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)


def main():
    argumentos = argparse.ArgumentParser(
        description="Análisis local de registros de acceso"
    )
    argumentos.add_argument(
        "--port", type=int, default=8765, help="Puerto local, por defecto 8765"
    )
    argumentos.add_argument(
        "--data-dir", type=Path, help="Carpeta para la base de datos local"
    )
    argumentos.add_argument(
        "--verbose",
        action="store_true",
        help="Mostrar códigos HTTP de las peticiones locales",
    )
    opciones = argumentos.parse_args()
    logging.basicConfig(
        level=logging.INFO if opciones.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )
    if not 1 <= opciones.port <= 65535:
        argumentos.error("El puerto debe estar entre 1 y 65535.")
    try:
        servidor = crear_servidor(opciones.port, opciones.data_dir)
    except (OSError, sqlite3.Error) as error:
        argumentos.exit(
            1,
            f"No se pudo iniciar el panel: {error}\nPrueba otro puerto con --port 8766.\n",
        )
    print(f"Mini SOC disponible en http://127.0.0.1:{opciones.port}", flush=True)
    print("Para detenerlo, pulsa Ctrl+C en esta terminal.", flush=True)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
