"""Escenarios de regresión de la revisión 1.1; solo datos ficticios y bases temporales."""

import hashlib
import io
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from almacen import Almacen, ConflictoEdicion
from app import crear_servidor, informe
from investigar_alertas import advertencias_datos, investigar, leer_csv

CABECERA = "fecha_utc,usuario,ip_origen,resultado\n"
ESCENARIO = (
    CABECERA
    + """2026-11-10T08:00:00Z,test,192.0.2.1,EXITO
2026-11-10T09:00:00Z,test,198.51.100.1,FALLO
2026-11-10T09:01:00Z,test,198.51.100.1,FALLO
2026-11-10T09:02:00Z,test,198.51.100.1,FALLO
2026-11-10T09:03:00Z,test,198.51.100.1,FALLO
2026-11-10T09:04:00Z,test,198.51.100.1,FALLO
2026-11-10T09:05:00Z,test,192.0.2.1,EXITO
2026-11-10T09:06:00Z,test,198.51.100.1,EXITO
2026-11-10T09:07:00Z,test,192.0.2.1,FALLO
"""
)


class ContextoTests(unittest.TestCase):
    def test_segundo_exito_sospechoso_y_contexto_completo(self):
        caso = investigar(leer_csv(ESCENARIO), 5, 10)[0]
        self.assertEqual(caso["prioridad"], "alta")
        self.assertEqual(caso["acceso_posterior"]["fecha_utc"], "2026-11-10T09:06:00Z")
        self.assertEqual(caso["exitos_posteriores"], 2)
        self.assertEqual(caso["cronologia"][-1]["fecha_utc"], "2026-11-10T09:07:00Z")

    def test_limite_posterior_inclusivo_y_fuera_de_ventana(self):
        base = ESCENARIO.replace("09:06:00Z", "09:14:00Z")
        self.assertEqual(investigar(leer_csv(base), 5, 10)[0]["prioridad"], "alta")
        fuera = base.replace("09:14:00Z", "09:14:00.000001Z")
        self.assertEqual(investigar(leer_csv(fuera), 5, 10)[0]["prioridad"], "media")

    def test_fechas_extremas_representables_y_conversion_fuera_de_rango(self):
        for fecha in ("0001-01-01T00:00:00Z", "9999-12-31T23:59:59Z"):
            with self.subTest(fecha=fecha):
                eventos = leer_csv(CABECERA + f"{fecha},test,192.0.2.1,FALLO\n")
                self.assertEqual(len(investigar(eventos, 1, 1440)), 1)
        with self.assertRaises(ValueError):
            leer_csv(CABECERA + "0001-01-01T00:00:00+01:00,test,192.0.2.1,FALLO\n")

    def test_duplicados_se_conservan_y_advierten(self):
        eventos = leer_csv(CABECERA + "2026-11-10T09:00:00Z,test,192.0.2.1,FALLO\n" * 5)
        self.assertEqual(len(eventos), 5)
        self.assertEqual(len(investigar(eventos, 5, 10)), 1)
        self.assertTrue(
            any("4 filas repetidas" in a for a in advertencias_datos(eventos))
        )

    def test_importar_modulo_terminal_no_imprime(self):
        import importlib
        import leer_accesos

        salida = io.StringIO()
        with redirect_stdout(salida):
            importlib.reload(leer_accesos)
        self.assertEqual(salida.getvalue(), "")


class PersistenciaTests(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.ruta = Path(self.temporal.name) / "test.sqlite3"
        self.almacen = Almacen(self.ruta)

    def tearDown(self):
        self.temporal.cleanup()

    def test_reordenar_empates_no_pierde_notas(self):
        filas = [f"2026-11-10T09:00:00Z,test,192.0.2.{n},FALLO" for n in (2, 1)]
        id1 = self.almacen.analizar(CABECERA + "\n".join(filas), "a.csv", 1, 10)
        caso = self.almacen.obtener()["casos"][0]
        self.almacen.guardar(caso["id"], "en_revision", "pendiente", "No perder", 1)
        id2 = self.almacen.analizar(
            CABECERA + "\n".join(reversed(filas)), "b.csv", 1, 10
        )
        self.assertEqual(id1, id2)
        self.assertEqual(self.almacen.obtener()["casos"][0]["notas"], "No perder")
        self.assertEqual(len(self.almacen.obtener()["fuentes"]), 2)

    def test_base_anterior_conserva_ids_decisiones_y_actualiza_contexto(self):
        # Simula el formato anterior: ID derivado del orden original y evidencia antigua.
        filas = [f"2026-11-10T09:00:00Z,test,192.0.2.{n},FALLO" for n in (2, 1)]
        eventos = [
            dict(zip(["fecha_utc", "usuario", "ip_origen", "resultado"], f.split(",")))
            for f in filas
        ]
        serializado = json.dumps(eventos, ensure_ascii=False, sort_keys=True)
        identidad = hashlib.sha256(f"1|10|{serializado}".encode()).hexdigest()[:24]
        evidencia = investigar(eventos, 1, 10)[0]
        evidencia["prioridad"] = "antigua"
        with closing(sqlite3.connect(self.ruta)) as c:
            with c:
                c.execute("DROP TABLE fuentes")
                c.execute(
                    "INSERT INTO analisis VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        identidad,
                        "antiguo.csv",
                        "2026-11-01T00:00:00Z",
                        1,
                        10,
                        serializado,
                    ),
                )
                c.execute(
                    "INSERT INTO casos VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        identidad + "-1",
                        identidad,
                        json.dumps(evidencia),
                        "en_revision",
                        "inconcluso",
                        "Nota anterior",
                        3,
                        "2026-11-01T01:00:00Z",
                    ),
                )
        self.almacen = Almacen(self.ruta)
        nuevo_id = self.almacen.analizar(
            CABECERA + "\n".join(reversed(filas)), "nuevo.csv", 1, 10
        )
        self.assertEqual(nuevo_id, identidad)
        caso = self.almacen.obtener(nuevo_id)["casos"][0]
        self.assertEqual(
            (caso["notas"], caso["version"], caso["estado"]),
            ("Nota anterior", 3, "en_revision"),
        )
        self.assertEqual(caso["prioridad"], "media")

    def test_procedencia_y_reanalisis_no_inventan_fuente(self):
        identidad = self.almacen.analizar(ESCENARIO, "prueba.csv", 5, 10)
        self.assertEqual(
            self.almacen.obtener()["fuentes"][0]["sha256"],
            hashlib.sha256(ESCENARIO.encode()).hexdigest(),
        )
        self.almacen.analizar(ESCENARIO, "generado.csv", 5, 10, registrar_fuente=False)
        self.assertEqual(len(self.almacen.obtener(identidad)["fuentes"]), 1)

    def test_exporta_nombres_y_notas_como_texto_literal(self):
        texto = (
            CABECERA
            + "2026-11-10T09:00:00Z,![x](https://example.invalid/pixel),192.0.2.1,FALLO\n"
        )
        self.almacen.analizar(texto, "[fuente].csv", 1, 10)
        caso = self.almacen.obtener()["casos"][0]
        self.almacen.guardar(
            caso["id"],
            "en_revision",
            "pendiente",
            "<img src=x>\n# Cerrado\n![x](https://example.invalid)",
            1,
        )
        salida = informe(self.almacen.obtener())
        self.assertNotIn("![x](https://", salida)
        self.assertIn(r"\<img src=x\>", salida)
        self.assertNotIn("\n# Cerrado", salida)
        self.assertIn("\\[fuente\\].csv", salida)

    def test_guardados_simultaneos_rechazan_sobrescritura(self):
        self.almacen.analizar(ESCENARIO, "test.csv", 5, 10)
        caso = self.almacen.obtener()["casos"][0]
        barrera = threading.Barrier(2)
        resultados = []

        def guardar(nota):
            barrera.wait()
            try:
                self.almacen.guardar(caso["id"], "en_revision", "pendiente", nota, 1)
                resultados.append("guardado")
            except ConflictoEdicion:
                resultados.append("conflicto")

        hilos = [threading.Thread(target=guardar, args=(n,)) for n in ("A", "B")]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join(timeout=15)
        self.assertEqual(sorted(resultados), ["conflicto", "guardado"])


class ValidacionHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporal = tempfile.TemporaryDirectory()
        cls.servidor = crear_servidor(0, cls.temporal.name)
        cls.hilo = threading.Thread(target=cls.servidor.serve_forever, daemon=True)
        cls.hilo.start()
        cls.url = f"http://127.0.0.1:{cls.servidor.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()
        cls.hilo.join()
        cls.temporal.cleanup()

    def test_id_invalido_y_fecha_imposible_devuelven_400_sin_cambiar_estado(self):
        with urlopen(self.url + "/api/estado", timeout=5) as r:
            anterior = json.load(r)["id"]
        for datos in (
            {"analisis_id": {}},
            {"analisis_id": []},
            {"analisis_id": "incorrecto"},
            {"csv": CABECERA + "0001-01-01T00:00:00+01:00,a,192.0.2.1,FALLO\n"},
            {"csv": ESCENARIO, "nombre": "a\n# falso"},
        ):
            with self.subTest(datos=datos), self.assertRaises(HTTPError) as error:
                urlopen(
                    Request(
                        self.url + "/api/analizar",
                        data=json.dumps(datos).encode(),
                        headers={"Content-Type": "application/json"},
                    ),
                    timeout=5,
                )
            self.assertEqual(error.exception.code, 400)
        with urlopen(self.url + "/api/estado", timeout=5) as r:
            self.assertEqual(json.load(r)["id"], anterior)


if __name__ == "__main__":
    unittest.main()
