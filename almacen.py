"""Análisis y decisiones del analista guardados en SQLite."""

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from functools import lru_cache

from investigar_alertas import advertencias_datos, investigar, leer_csv
from detectar_alertas import clave_evento


ESTADOS = {"nueva", "en_revision", "cerrada"}
VEREDICTOS = {"pendiente", "legitimo", "sospechoso", "inconcluso"}


class ConflictoEdicion(Exception):
    """Otra pestaña ha guardado una versión más reciente del caso."""


def ahora():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class Almacen:
    def __init__(self, ruta):
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        with self.conectar() as conexion:
            conexion.executescript(
                """
                CREATE TABLE IF NOT EXISTS analisis (
                    id TEXT PRIMARY KEY,
                    nombre TEXT NOT NULL,
                    fecha TEXT NOT NULL,
                    umbral INTEGER NOT NULL,
                    minutos INTEGER NOT NULL,
                    eventos TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS casos (
                    id TEXT PRIMARY KEY,
                    analisis_id TEXT NOT NULL REFERENCES analisis(id),
                    evidencia TEXT NOT NULL,
                    estado TEXT NOT NULL DEFAULT 'nueva',
                    veredicto TEXT NOT NULL DEFAULT 'pendiente',
                    notas TEXT NOT NULL DEFAULT '',
                    version INTEGER NOT NULL DEFAULT 1,
                    actualizado TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS configuracion (
                    clave TEXT PRIMARY KEY,
                    valor TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fuentes (
                    analisis_id TEXT NOT NULL REFERENCES analisis(id),
                    sha256 TEXT NOT NULL,
                    nombre TEXT NOT NULL,
                    fecha TEXT NOT NULL,
                    PRIMARY KEY (analisis_id, sha256, nombre)
                );
            """
            )

    @contextmanager
    def conectar(self):
        conexion = sqlite3.connect(self.ruta, timeout=10)
        conexion.row_factory = sqlite3.Row
        conexion.execute("PRAGMA foreign_keys = ON")
        try:
            with conexion:
                yield conexion
        finally:
            conexion.close()

    def analizar(self, texto, nombre, umbral, minutos, registrar_fuente=True):
        if not isinstance(texto, str):
            raise ValueError("El contenido CSV debe ser texto.")
        if type(umbral) is not int or not 1 <= umbral <= 100:
            raise ValueError("El umbral debe ser un entero entre 1 y 100.")
        if type(minutos) is not int or not 1 <= minutos <= 1440:
            raise ValueError("La ventana debe ser un entero entre 1 y 1440 minutos.")
        if not isinstance(nombre, str) or not 1 <= len(nombre.strip()) <= 120:
            raise ValueError(
                "El nombre del archivo debe tener entre 1 y 120 caracteres."
            )
        if any(ord(c) < 32 or ord(c) == 127 for c in nombre):
            raise ValueError("El nombre del archivo contiene caracteres de control.")
        eventos = leer_csv(texto)
        serializado = json.dumps(eventos, ensure_ascii=False, sort_keys=True)
        identidad = f"{umbral}|{minutos}|{serializado}"
        analisis_id = hashlib.sha256(identidad.encode("utf-8")).hexdigest()[:24]
        casos = investigar(eventos, umbral, minutos)
        fecha = ahora()
        with self.conectar() as conexion:
            conexion.execute("BEGIN IMMEDIATE")
            # Compatibilidad con IDs anteriores al desempate determinista: no perder notas.
            if (
                conexion.execute(
                    "SELECT 1 FROM analisis WHERE id = ?", (analisis_id,)
                ).fetchone()
                is None
            ):
                anteriores = conexion.execute(
                    "SELECT id, eventos FROM analisis WHERE umbral = ? AND minutos = ? ORDER BY fecha",
                    (umbral, minutos),
                ).fetchall()
                for anterior in anteriores:
                    normalizado = json.dumps(
                        sorted(json.loads(anterior["eventos"]), key=clave_evento),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    if normalizado == serializado:
                        analisis_id = anterior["id"]
                        break
            conexion.execute(
                "INSERT OR IGNORE INTO analisis VALUES (?, ?, ?, ?, ?, ?)",
                (analisis_id, nombre.strip(), fecha, umbral, minutos, serializado),
            )
            existentes = conexion.execute(
                "SELECT evidencia FROM casos WHERE analisis_id = ?", (analisis_id,)
            ).fetchall()
            firmas = {
                (e["usuario"], e["fecha_utc"])
                for fila in existentes
                for e in [json.loads(fila["evidencia"])]
            }
            for indice, caso in enumerate(casos):
                if (caso["usuario"], caso["fecha_utc"]) in firmas:
                    continue
                caso_id = f"{analisis_id}-{indice + 1}"
                conexion.execute(
                    "INSERT OR IGNORE INTO casos (id, analisis_id, evidencia, actualizado) VALUES (?, ?, ?, ?)",
                    (caso_id, analisis_id, json.dumps(caso, ensure_ascii=False), fecha),
                )
            if registrar_fuente:
                conexion.execute(
                    "INSERT OR IGNORE INTO fuentes VALUES (?, ?, ?, ?)",
                    (
                        analisis_id,
                        hashlib.sha256(texto.encode("utf-8")).hexdigest(),
                        nombre.strip(),
                        fecha,
                    ),
                )
            conexion.execute(
                "INSERT OR REPLACE INTO configuracion VALUES ('actual', ?)",
                (analisis_id,),
            )
        return analisis_id

    def obtener(self, analisis_id=None):
        if analisis_id is not None and (
            not isinstance(analisis_id, str)
            or re.fullmatch(r"[0-9a-f]{24}", analisis_id) is None
        ):
            raise ValueError(
                "El identificador del análisis debe tener 24 caracteres hexadecimales."
            )
        with self.conectar() as conexion:
            if analisis_id is None:
                fila = conexion.execute(
                    "SELECT valor FROM configuracion WHERE clave = 'actual'"
                ).fetchone()
                if fila is None:
                    return None
                analisis_id = fila["valor"]
            analisis = conexion.execute(
                "SELECT * FROM analisis WHERE id = ?", (analisis_id,)
            ).fetchone()
            if analisis is None:
                raise KeyError("El análisis no existe.")
            filas = conexion.execute(
                "SELECT * FROM casos WHERE analisis_id = ? ORDER BY id", (analisis_id,)
            ).fetchall()
            historial = conexion.execute(
                "SELECT id, nombre, fecha, umbral, minutos FROM analisis ORDER BY fecha DESC LIMIT 30"
            ).fetchall()
            fuentes = conexion.execute(
                "SELECT sha256, nombre, fecha FROM fuentes WHERE analisis_id = ? ORDER BY fecha DESC LIMIT 30",
                (analisis_id,),
            ).fetchall()
        eventos = sorted(json.loads(analisis["eventos"]), key=clave_evento)
        evidencia_actual = self.evidencias(
            analisis["eventos"], analisis["umbral"], analisis["minutos"]
        )
        casos = []
        for fila in filas:
            guardada = json.loads(fila["evidencia"])
            casos.append(
                {
                    **evidencia_actual.get(
                        (guardada["usuario"], guardada["fecha_utc"]), guardada
                    ),
                    **{
                        campo: fila[campo]
                        for campo in (
                            "id",
                            "estado",
                            "veredicto",
                            "notas",
                            "version",
                            "actualizado",
                        )
                    },
                }
            )
        casos.sort(
            key=lambda caso: (
                caso["prioridad"] != "alta",
                caso["fecha_utc"],
                caso["id"],
            )
        )
        return {
            "id": analisis["id"],
            "nombre": analisis["nombre"],
            "fecha": analisis["fecha"],
            "umbral": analisis["umbral"],
            "minutos": analisis["minutos"],
            "eventos": eventos,
            "advertencias": advertencias_datos(eventos),
            "fuentes": [dict(fila) for fila in fuentes],
            "version_motor": "1.1",
            "casos": casos,
            "historial": [dict(fila) for fila in historial],
        }

    @staticmethod
    @lru_cache(maxsize=8)
    def evidencias(serializado, umbral, minutos):
        """Recalcula el contexto con el motor actual sin sobrescribir decisiones previas."""
        return {
            (c["usuario"], c["fecha_utc"]): c
            for c in investigar(json.loads(serializado), umbral, minutos)
        }

    def guardar(self, caso_id, estado, veredicto, notas, version):
        if (
            not isinstance(caso_id, str)
            or re.fullmatch(r"[0-9a-f]{24}-[1-9][0-9]*", caso_id) is None
        ):
            raise ValueError("El identificador del caso no es válido.")
        if not isinstance(estado, str) or estado not in ESTADOS:
            raise ValueError("El estado no es válido.")
        if not isinstance(veredicto, str) or veredicto not in VEREDICTOS:
            raise ValueError("El veredicto no es válido.")
        if not isinstance(notas, str) or len(notas) > 10000:
            raise ValueError("Las notas admiten hasta 10.000 caracteres.")
        if type(version) is not int or version < 1:
            raise ValueError("La versión del caso no es válida.")
        if estado == "cerrada" and (veredicto == "pendiente" or not notas.strip()):
            raise ValueError(
                "Para cerrar el caso, elige un veredicto y documenta tu conclusión."
            )
        with self.conectar() as conexion:
            fila = conexion.execute(
                "SELECT analisis_id FROM casos WHERE id = ?", (caso_id,)
            ).fetchone()
            if fila is None:
                raise KeyError("El caso no existe.")
            resultado = conexion.execute(
                "UPDATE casos SET estado = ?, veredicto = ?, notas = ?, version = version + 1, actualizado = ? WHERE id = ? AND version = ?",
                (estado, veredicto, notas, ahora(), caso_id, version),
            )
            if resultado.rowcount != 1:
                raise ConflictoEdicion(
                    "Otra pestaña ha modificado este caso. Copia tus notas y recarga antes de guardar."
                )
        return self.obtener(fila["analisis_id"])
