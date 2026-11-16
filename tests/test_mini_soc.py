"""Pruebas del detector, la persistencia y el flujo HTTP del laboratorio."""

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from almacen import Almacen, ConflictoEdicion
from app import crear_servidor, eventos_a_csv
from detectar_alertas import detectar_alertas
from investigar_alertas import investigar, leer_csv


RAIZ = Path(__file__).resolve().parents[1]
EJEMPLO = (RAIZ / "datos" / "accesos.csv").read_text(encoding="utf-8")


class DetectorTests(unittest.TestCase):
    def setUp(self):
        self.eventos = leer_csv(EJEMPLO)

    def test_compatibilidad_y_ejercicios(self):
        alertas = detectar_alertas(self.eventos)
        self.assertEqual(
            [(a["usuario"], a["fecha_utc"]) for a in alertas],
            [
                ("ana", "2026-11-10T09:07:30Z"),
                ("bruno", "2026-11-10T09:09:00Z"),
            ],
        )
        self.assertEqual(len(detectar_alertas(self.eventos, 1, 10)), 3)
        self.assertEqual(detectar_alertas(self.eventos, 5, 6), [])
        self.assertEqual(detectar_alertas(reversed(self.eventos)), alertas)

    def test_limite_temporal_inclusivo(self):
        eventos = [
            dict(e)
            for e in self.eventos
            if e["usuario"] == "bruno" and e["resultado"] == "FALLO"
        ]
        eventos[-1]["fecha_utc"] = "2026-11-10T09:12:00Z"
        self.assertEqual(len(detectar_alertas(eventos)), 1)
        eventos[-1]["fecha_utc"] = "2026-11-10T09:12:01Z"
        self.assertEqual(detectar_alertas(eventos), [])

    def test_sexto_fallo_otra_ip_y_acceso_correcto_intermedio(self):
        extra = {
            "fecha_utc": "2026-11-10T09:09:30Z",
            "usuario": "bruno",
            "ip_origen": "203.0.113.15",
            "resultado": "FALLO",
        }
        acceso = {**extra, "fecha_utc": "2026-11-10T09:05:00Z", "resultado": "EXITO"}
        self.assertEqual(
            detectar_alertas(self.eventos + [extra, acceso]),
            detectar_alertas(self.eventos),
        )

    def test_contexto_y_prioridad(self):
        casos = {
            caso["usuario"]: caso for caso in investigar(reversed(self.eventos), 5, 10)
        }
        self.assertEqual(casos["bruno"]["prioridad"], "alta")
        self.assertEqual(casos["ana"]["prioridad"], "media")
        self.assertEqual(casos["bruno"]["acceso_anterior"]["ip_origen"], "192.0.2.20")
        self.assertEqual(
            casos["bruno"]["acceso_posterior"]["ip_origen"], "198.51.100.45"
        )
        self.assertEqual(len(casos["bruno"]["cronologia"]), 7)

    def test_validacion_csv_y_normalizacion(self):
        normalizado = leer_csv(
            "\ufeff" + EJEMPLO.replace("08:30:00Z", "09:30:00+01:00")
        )
        self.assertEqual(normalizado, self.eventos)
        for texto in [
            "usuario,ip\nana,192.0.2.1",
            EJEMPLO.replace("192.0.2.10", "IP_INVALIDA"),
            EJEMPLO.replace("EXITO", "CORRECTO"),
            EJEMPLO.replace("08:30:00Z", "08:30:00"),
            EJEMPLO.splitlines()[0],
        ]:
            with self.subTest(texto=texto[:70]), self.assertRaises(ValueError):
                leer_csv(texto)

    def test_fallos_simultaneos_conservan_evidencia_del_umbral(self):
        eventos = [
            {
                "fecha_utc": "2026-11-10T09:00:00Z",
                "usuario": "ana",
                "ip_origen": f"192.0.2.{numero}",
                "resultado": "FALLO",
            }
            for numero in range(1, 7)
        ]
        casos = investigar(eventos, 5, 10)
        self.assertEqual(len(casos), 1)
        self.assertEqual(len(casos[0]["ips_fallos"]), 5)

    def test_demostracion_cuentas_prioridades_e_ipv6(self):
        eventos = leer_csv(
            (RAIZ / "datos" / "demostracion.csv").read_text(encoding="utf-8")
        )
        casos = {caso["usuario"]: caso for caso in investigar(eventos, 5, 10)}
        self.assertEqual(len(eventos), 40)
        self.assertEqual(len({evento["usuario"] for evento in eventos}), 7)
        self.assertEqual(set(casos), {"ana", "bruno", "diego", "elena", "svc_backup"})
        self.assertEqual(len(casos["elena"]["ips_fallos"]), 2)
        self.assertEqual(
            casos["svc_backup"]["acceso_posterior"]["ip_origen"], "2001:db8::20"
        )
        self.assertEqual(sum(caso["prioridad"] == "alta" for caso in casos.values()), 3)


class AlmacenTests(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.ruta = Path(self.temporal.name) / "soc.sqlite3"
        self.almacen = Almacen(self.ruta)
        self.identidad = self.almacen.analizar(EJEMPLO, "accesos.csv", 5, 10)

    def tearDown(self):
        self.temporal.cleanup()

    def test_notas_sobreviven_reinicio_y_reanalisis(self):
        caso = self.almacen.obtener()["casos"][0]
        self.almacen.guardar(
            caso["id"], "en_revision", "pendiente", "Comprobar acceso con Bruno.", 1
        )
        nuevo = Almacen(self.ruta)
        nuevo.analizar(EJEMPLO, "accesos.csv", 1, 10)
        nuevo.analizar(EJEMPLO, "accesos.csv", 5, 10)
        recuperado = nuevo.obtener()["casos"][0]
        self.assertEqual(recuperado["notas"], "Comprobar acceso con Bruno.")
        self.assertEqual(recuperado["version"], 2)

    def test_cierre_exige_conclusion_y_edicion_concurrente(self):
        caso = self.almacen.obtener()["casos"][0]
        with self.assertRaises(ValueError):
            self.almacen.guardar(caso["id"], "cerrada", "pendiente", "", 1)
        self.almacen.guardar(
            caso["id"],
            "cerrada",
            "inconcluso",
            "Falta confirmar el acceso con la persona.",
            1,
        )
        with self.assertRaises(ConflictoEdicion):
            self.almacen.guardar(caso["id"], "nueva", "pendiente", "Edición antigua", 1)
        self.assertEqual(self.almacen.obtener()["casos"][0]["estado"], "cerrada")

    def test_importacion_invalida_conserva_datos(self):
        with self.assertRaises(ValueError):
            self.almacen.analizar("datos incorrectos", "error.csv", 5, 10)
        self.assertEqual(self.almacen.obtener()["id"], self.identidad)


class ServidorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporal = tempfile.TemporaryDirectory()
        cls.servidor = crear_servidor(0, cls.temporal.name)
        cls.base = f"http://127.0.0.1:{cls.servidor.server_address[1]}"
        cls.hilo = threading.Thread(target=cls.servidor.serve_forever, daemon=True)
        cls.hilo.start()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()
        cls.hilo.join()
        cls.temporal.cleanup()

    def pedir(self, ruta, datos=None, cabeceras=None):
        cuerpo = None if datos is None else json.dumps(datos).encode("utf-8")
        headers = {"Content-Type": "application/json", **(cabeceras or {})}
        with urlopen(
            Request(self.base + ruta, data=cuerpo, headers=headers), timeout=5
        ) as respuesta:
            return respuesta.status, respuesta.read().decode("utf-8"), respuesta.headers

    def test_flujo_completo_guardado_informe_y_cambio_regla(self):
        _, cuerpo, _ = self.pedir("/api/demo", {"umbral": 5, "minutos": 10})
        datos = json.loads(cuerpo)
        self.assertEqual(len(datos["casos"]), 5)
        self.assertEqual(len(datos["eventos"]), 40)
        self.assertEqual(sum(caso["prioridad"] == "alta" for caso in datos["casos"]), 3)
        caso = datos["casos"][0]
        _, cuerpo, _ = self.pedir(
            "/api/casos",
            {
                "id": caso["id"],
                "estado": "en_revision",
                "veredicto": "pendiente",
                "notas": "Revisar la IP del acceso posterior.",
                "version": caso["version"],
            },
        )
        self.assertIn("Revisar la IP", cuerpo)
        _, reporte, headers = self.pedir(f"/api/informe?analisis={datos['id']}")
        self.assertIn("Revisar la IP del acceso posterior.", reporte)
        self.assertIn("attachment", headers["Content-Disposition"])
        _, cuerpo, _ = self.pedir(
            "/api/analizar", {"analisis_id": datos["id"], "umbral": 5, "minutos": 6}
        )
        self.assertEqual(json.loads(cuerpo)["casos"], [])
        _, cuerpo, _ = self.pedir(
            "/api/analizar",
            {
                "csv": eventos_a_csv(leer_csv(EJEMPLO)),
                "nombre": "nuevo.csv",
                "umbral": 1,
                "minutos": 10,
            },
        )
        self.assertEqual(len(json.loads(cuerpo)["casos"]), 3)

    def test_origen_y_rutas(self):
        with self.assertRaises(HTTPError) as resultado:
            self.pedir("/api/demo", {}, {"Origin": "https://otro-sitio.example"})
        self.assertEqual(resultado.exception.code, 403)
        with self.assertRaises(HTTPError) as resultado:
            self.pedir("/datos/accesos.csv")
        self.assertEqual(resultado.exception.code, 404)
        for ruta in ["/", "/app.js", "/estilos.css"]:
            codigo, cuerpo, headers = self.pedir(ruta)
            self.assertEqual(codigo, 200)
            self.assertTrue(cuerpo)
            self.assertIn("default-src 'self'", headers["Content-Security-Policy"])

    def test_datos_invalidos_se_rechazan(self):
        for datos in [
            {"csv": "incorrecto"},
            {"umbral": True},
            {"minutos": 0},
            {"csv": 123},
        ]:
            with self.subTest(datos=datos), self.assertRaises(HTTPError) as resultado:
                self.pedir("/api/analizar", datos)
            self.assertEqual(resultado.exception.code, 400)

    def test_campo_csv_excesivo_muestra_error(self):
        texto = (
            "fecha_utc,usuario,ip_origen,resultado\n2026-11-10T09:00:00Z,"
            + "a" * 140000
            + ",192.0.2.1,FALLO\n"
        )
        with self.assertRaises(HTTPError) as resultado:
            self.pedir("/api/analizar", {"csv": texto})
        self.assertEqual(resultado.exception.code, 400)
        self.assertIn("CSV", resultado.exception.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
