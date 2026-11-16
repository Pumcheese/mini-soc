"""Análisis y decisiones del analista guardados en SQLite."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from investigar_alertas import investigar, leer_csv


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

    def analizar(self, texto, nombre, umbral, minutos):
        if type(umbral) is not int or not 1 <= umbral <= 100:
            raise ValueError("El umbral debe ser un entero entre 1 y 100.")
        if type(minutos) is not int or not 1 <= minutos <= 1440:
            raise ValueError("La ventana debe ser un entero entre 1 y 1440 minutos.")
        if not isinstance(nombre, str) or not 1 <= len(nombre.strip()) <= 120:
            raise ValueError(
                "El nombre del archivo debe tener entre 1 y 120 caracteres."
            )
        eventos = leer_csv(texto)
        serializado = json.dumps(eventos, ensure_ascii=False, sort_keys=True)
        identidad = f"{umbral}|{minutos}|{serializado}"
        analisis_id = hashlib.sha256(identidad.encode("utf-8")).hexdigest()[:24]
        casos = investigar(eventos, umbral, minutos)
        fecha = ahora()
        with self.conectar() as conexion:
            conexion.execute(
                "INSERT OR IGNORE INTO analisis VALUES (?, ?, ?, ?, ?, ?)",
                (analisis_id, nombre.strip(), fecha, umbral, minutos, serializado),
            )
            for indice, caso in enumerate(casos):
                caso_id = f"{analisis_id}-{indice + 1}"
                conexion.execute(
                    "INSERT OR IGNORE INTO casos (id, analisis_id, evidencia, actualizado) VALUES (?, ?, ?, ?)",
                    (caso_id, analisis_id, json.dumps(caso, ensure_ascii=False), fecha),
                )
            conexion.execute(
                "INSERT OR REPLACE INTO configuracion VALUES ('actual', ?)",
                (analisis_id,),
            )
        return analisis_id

    def obtener(self, analisis_id=None):
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
        casos = []
        for fila in filas:
            casos.append(
                {
                    **json.loads(fila["evidencia"]),
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
            "eventos": json.loads(analisis["eventos"]),
            "casos": casos,
            "historial": [dict(fila) for fila in historial],
        }

    def guardar(self, caso_id, estado, veredicto, notas, version):
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
