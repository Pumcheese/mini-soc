"use strict";

const $ = (id) => document.getElementById(id);
const estados = {
  nueva: "Nueva",
  en_revision: "En revisión",
  cerrada: "Cerrada",
};
const titulos = {
  alertas: [
    "Investigación de accesos",
    "Revisa los intentos fallidos y documenta cada caso.",
  ],
  eventos: [
    "Registros de acceso",
    "Los eventos originales, ordenados por fecha y listos para consultar.",
  ],
  ayuda: [
    "Ayuda",
    "Formato de los archivos, criterios de detección y gestión de casos.",
  ],
};
const borradores = new Map();
let analisis = null;
let seleccionado = null;
let ocupado = false;

function elemento(etiqueta, clase, texto) {
  const nodo = document.createElement(etiqueta);
  if (clase) nodo.className = clase;
  if (texto !== undefined) nodo.textContent = texto;
  return nodo;
}

function hora(fecha) {
  return fecha ? `${fecha.slice(11, 19)}` : "Sin datos";
}

function fechaCompleta(fecha) {
  return `${fecha.slice(0, 10)} · ${hora(fecha)} UTC`;
}

function avisar(texto, error = false) {
  $("mensaje").hidden = true;
  $("error").hidden = true;
  const destino = $(error ? "error" : "mensaje");
  destino.textContent = texto;
  destino.hidden = false;
}

async function api(ruta, datos) {
  const opciones =
    datos === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(datos),
        };
  const respuesta = await fetch(ruta, opciones);
  const contenido = await respuesta.json();
  if (!respuesta.ok)
    throw new Error(contenido.error || "No se pudo completar la operación.");
  return contenido;
}

async function realizar(operacion) {
  if (ocupado) return;
  ocupado = true;
  document
    .querySelectorAll("[data-mutation], #historial")
    .forEach((control) => {
      control.disabled = true;
    });
  $("contenido").setAttribute("aria-busy", "true");
  try {
    await operacion();
  } catch (error) {
    avisar(
      error.message || "Comprueba que el servidor local sigue abierto.",
      true,
    );
  } finally {
    ocupado = false;
    document
      .querySelectorAll("[data-mutation], #historial")
      .forEach((control) => {
        control.disabled = false;
      });
    $("contenido").removeAttribute("aria-busy");
  }
}

function permitirCambio() {
  return (
    borradores.size === 0 ||
    window.confirm(
      "Hay notas sin guardar. ¿Quieres cambiar de análisis y descartar esos cambios?",
    )
  );
}

function recibir(datos, mantener = false) {
  if (!mantener) borradores.clear();
  analisis = datos;
  const direccion = new URL(window.location.href);
  direccion.searchParams.set("analisis", analisis.id);
  window.history.replaceState(null, "", direccion);
  if (!analisis.casos.some((caso) => caso.id === seleccionado)) {
    seleccionado = analisis.casos[0]?.id || null;
  }
  $("stat-eventos").textContent = analisis.eventos.length;
  $("stat-alertas").textContent = analisis.casos.length;
  $("stat-altas").textContent = analisis.casos.filter(
    (caso) => caso.prioridad === "alta",
  ).length;
  $("stat-cerradas").textContent = analisis.casos.filter(
    (caso) => caso.estado === "cerrada",
  ).length;
  $("nav-count").textContent = analisis.casos.length;
  $("stat-regla").textContent =
    `${analisis.umbral} ${analisis.umbral === 1 ? "fallo" : "fallos"} / ${analisis.minutos} min`;
  $("fuente-nombre").textContent = analisis.nombre;
  $("fuente-periodo").textContent =
    `${fechaCompleta(analisis.eventos[0].fecha_utc)} — ${fechaCompleta(analisis.eventos.at(-1).fecha_utc)}`;
  $("umbral").value = analisis.umbral;
  $("minutos").value = analisis.minutos;
  $("exportar").href =
    `/api/informe?analisis=${encodeURIComponent(analisis.id)}`;
  const opciones = analisis.historial.map((anterior) => {
    const opcion = elemento(
      "option",
      "",
      `${anterior.nombre} · ${anterior.umbral}/${anterior.minutos} min · ${fechaCompleta(anterior.fecha)}`,
    );
    opcion.value = anterior.id;
    return opcion;
  });
  if (!analisis.historial.some((anterior) => anterior.id === analisis.id)) {
    const opcion = elemento(
      "option",
      "",
      `${analisis.nombre} · ${analisis.umbral}/${analisis.minutos} min`,
    );
    opcion.value = analisis.id;
    opciones.unshift(opcion);
  }
  $("historial").replaceChildren(...opciones);
  $("historial").value = analisis.id;
  mostrarAlertas();
  mostrarDetalle();
  mostrarEventos();
}

function mostrarAlertas() {
  if (!analisis) return;
  const busqueda = $("buscar-alertas").value.trim().toLowerCase();
  const prioridad = $("filtro-prioridad").value;
  const estado = $("filtro-estado").value;
  const visibles = analisis.casos.filter(
    (caso) =>
      (!prioridad || caso.prioridad === prioridad) &&
      (!estado || caso.estado === estado) &&
      `${caso.usuario} ${caso.ips_fallos.join(" ")}`
        .toLowerCase()
        .includes(busqueda),
  );
  $("queue-count").textContent =
    `${visibles.length} / ${analisis.casos.length}`;
  if (!visibles.some((caso) => caso.id === seleccionado))
    seleccionado = visibles[0]?.id || null;
  const filas = visibles.map((caso) => {
    const fila = elemento("tr", seleccionado === caso.id ? "selected" : "");
    const cuenta = elemento("td");
    const boton = elemento("button", "account-link", caso.usuario);
    boton.type = "button";
    boton.setAttribute("aria-pressed", String(seleccionado === caso.id));
    boton.setAttribute(
      "aria-label",
      `Investigar ${caso.usuario}, prioridad ${caso.prioridad}, ${estados[caso.estado]}`,
    );
    cuenta.append(
      boton,
      elemento(
        "small",
        "account-rule",
        `${caso.numero_fallos} ${caso.numero_fallos === 1 ? "fallo" : "fallos"} / ${analisis.minutos} min`,
      ),
    );
    const prioridadCelda = elemento("td");
    prioridadCelda.append(
      elemento(
        "span",
        `badge ${caso.prioridad}`,
        caso.prioridad === "alta" ? "Alta" : "Media",
      ),
    );
    const estadoCelda = elemento("td");
    estadoCelda.append(
      elemento("span", `badge ${caso.estado}`, estados[caso.estado]),
    );
    fila.append(
      cuenta,
      elemento("td", "mono", hora(caso.fecha_utc)),
      prioridadCelda,
      estadoCelda,
    );
    boton.addEventListener("click", () => {
      seleccionado = caso.id;
      mostrarAlertas();
      mostrarDetalle();
    });
    return fila;
  });
  if (!filas.length) {
    const texto = analisis.casos.length
      ? "No hay alertas con estos filtros."
      : "Ningún evento alcanza el umbral dentro de la ventana seleccionada.";
    const fila = elemento("tr");
    const celda = elemento("td", "empty-state", texto);
    celda.colSpan = 4;
    fila.append(celda);
    filas.push(fila);
  }
  $("lista-alertas").replaceChildren(...filas);
}

function mostrarDetalle() {
  const caso = analisis?.casos.find((alerta) => alerta.id === seleccionado);
  $("detalle-vacio").hidden = Boolean(caso);
  $("detalle").hidden = !caso;
  if (!caso) return;
  $("caso-titulo").textContent = `Cuenta ${caso.usuario}`;
  $("caso-fecha").textContent =
    `Alerta generada el ${fechaCompleta(caso.fecha_utc)}`;
  $("caso-prioridad").className = `badge ${caso.prioridad}`;
  $("caso-prioridad").textContent = `Prioridad ${caso.prioridad}`;
  $("caso-motivo").textContent = caso.motivo;
  $("ip-anterior").textContent =
    caso.acceso_anterior?.ip_origen || "Sin registro previo";
  $("hora-anterior").textContent = caso.acceso_anterior
    ? fechaCompleta(caso.acceso_anterior.fecha_utc)
    : "Hace falta más contexto";
  $("fallos-cuenta").textContent =
    `${caso.numero_fallos} ${caso.numero_fallos === 1 ? "intento fallido" : "intentos fallidos"}`;
  $("ips-fallos").textContent = caso.ips_fallos.join(" · ");
  $("ip-posterior").textContent =
    caso.acceso_posterior?.ip_origen || "Sin registro posterior";
  $("hora-posterior").textContent = caso.acceso_posterior
    ? fechaCompleta(caso.acceso_posterior.fecha_utc)
    : `En los ${analisis.minutos} min posteriores a la alerta`;
  const cronologia = caso.cronologia.map((evento) => {
    const fila = elemento("li");
    const tiempo = elemento("time", "", hora(evento.fecha_utc));
    tiempo.dateTime = evento.fecha_utc;
    tiempo.title = fechaCompleta(evento.fecha_utc);
    const punto = elemento(
      "span",
      `event-dot${evento.resultado === "EXITO" ? " success" : ""}`,
    );
    punto.setAttribute("aria-hidden", "true");
    fila.append(
      tiempo,
      punto,
      elemento("span", "event-detail", evento.ip_origen),
      elemento(
        "span",
        `badge ${evento.resultado.toLowerCase()}`,
        evento.resultado === "EXITO" ? "Acceso correcto" : "Intento fallido",
      ),
    );
    return fila;
  });
  $("cronologia").replaceChildren(...cronologia);
  $("cronologia-limite").hidden =
    caso.total_cronologia <= caso.cronologia.length;
  $("cronologia-limite").textContent =
    `Se muestran ${caso.cronologia.length} de ${caso.total_cronologia} eventos relacionados. Consulta el conjunto completo en Registros de acceso.`;
  const valores = borradores.get(caso.id) || caso;
  $("caso-estado").value = valores.estado;
  $("caso-veredicto").value = valores.veredicto;
  $("caso-notas").value = valores.notas;
  actualizarEstadoGuardado();
}

function actualizarEstadoGuardado() {
  const pendiente = borradores.has(seleccionado);
  $("guardado-estado").textContent = pendiente
    ? "Cambios sin guardar"
    : "Guardado local";
  $("guardado-estado").className = `save-state${pendiente ? " dirty" : ""}`;
}

function mostrarEventos() {
  if (!analisis) return;
  const busqueda = $("buscar-eventos").value.trim().toLowerCase();
  const eventos = analisis.eventos.filter((evento) =>
    Object.values(evento).join(" ").toLowerCase().includes(busqueda),
  );
  const filas = eventos.map((evento) => {
    const fila = elemento("tr");
    fila.append(
      elemento("td", "", fechaCompleta(evento.fecha_utc)),
      elemento("td", "", evento.usuario),
      elemento("td", "ip-cell", evento.ip_origen),
    );
    const resultado = elemento("td");
    resultado.append(
      elemento(
        "span",
        `badge ${evento.resultado.toLowerCase()}`,
        evento.resultado === "EXITO" ? "EXITO" : "FALLO",
      ),
    );
    fila.append(resultado);
    return fila;
  });
  $("tabla-eventos").replaceChildren(...filas);
  $("eventos-contador").textContent =
    `${eventos.length} de ${analisis.eventos.length} eventos`;
}

document.querySelectorAll("[data-vista]").forEach((boton) => {
  boton.addEventListener("click", () => {
    const vista = boton.dataset.vista;
    document.querySelectorAll(".view").forEach((panel) => {
      panel.hidden = panel.id !== `vista-${vista}`;
    });
    document.querySelectorAll("[data-vista]").forEach((opcion) => {
      opcion.classList.toggle("active", opcion === boton);
      if (opcion === boton) opcion.setAttribute("aria-current", "page");
      else opcion.removeAttribute("aria-current");
    });
    $("page-title").textContent = titulos[vista][0];
    $("page-subtitle").textContent = titulos[vista][1];
  });
});

["buscar-alertas", "filtro-prioridad", "filtro-estado"].forEach((id) => {
  $(id).addEventListener(id === "buscar-alertas" ? "input" : "change", () => {
    mostrarAlertas();
    mostrarDetalle();
  });
});
$("buscar-eventos").addEventListener("input", mostrarEventos);

$("regla-form").addEventListener("submit", (evento) => {
  evento.preventDefault();
  if (!analisis || !permitirCambio()) return;
  realizar(async () => {
    const datos = await api("/api/analizar", {
      analisis_id: analisis.id,
      umbral: Number($("umbral").value),
      minutos: Number($("minutos").value),
    });
    recibir(datos);
    avisar(
      `Análisis completado. ${datos.casos.length} alertas para ${datos.eventos.length} eventos.`,
    );
  });
});

$("importar").addEventListener("click", () => {
  $("archivo").click();
});
$("archivo").addEventListener("change", () => {
  const archivo = $("archivo").files[0];
  $("archivo").value = "";
  if (!archivo || !permitirCambio()) return;
  realizar(async () => {
    if (archivo.size > 2 * 1024 * 1024)
      throw new Error("El archivo supera los 2 MB.");
    if (!$("regla-form").reportValidity()) return;
    const contenido = await archivo.arrayBuffer();
    const texto = new TextDecoder("utf-8", { fatal: true }).decode(contenido);
    const datos = await api("/api/analizar", {
      csv: texto,
      nombre: archivo.name,
      umbral: Number($("umbral").value),
      minutos: Number($("minutos").value),
    });
    recibir(datos);
    avisar(
      `Importado ${datos.nombre}. ${datos.eventos.length} eventos y ${datos.casos.length} alertas.`,
    );
  });
});

$("demo").addEventListener("click", () => {
  if (!permitirCambio()) return;
  realizar(async () => {
    recibir(await api("/api/demo", { umbral: 5, minutos: 10 }));
    avisar("Demostración cargada. Regla de cinco fallos en diez minutos.");
  });
});

$("historial").addEventListener("change", () => {
  const identidad = $("historial").value;
  if (!permitirCambio()) {
    $("historial").value = analisis.id;
    return;
  }
  realizar(async () => {
    try {
      recibir(
        await api(`/api/estado?analisis=${encodeURIComponent(identidad)}`),
      );
      avisar("Análisis guardado recuperado.");
    } catch (error) {
      $("historial").value = analisis.id;
      throw error;
    }
  });
});

$("caso-form").addEventListener("input", () => {
  const caso = analisis?.casos.find((alerta) => alerta.id === seleccionado);
  if (!caso) return;
  const anterior = borradores.get(caso.id);
  const borrador = {
    id: caso.id,
    estado: $("caso-estado").value,
    veredicto: $("caso-veredicto").value,
    notas: $("caso-notas").value,
    version: anterior?.version || caso.version,
  };
  if (
    borrador.estado === caso.estado &&
    borrador.veredicto === caso.veredicto &&
    borrador.notas === caso.notas
  )
    borradores.delete(caso.id);
  else borradores.set(caso.id, borrador);
  actualizarEstadoGuardado();
});

$("caso-form").addEventListener("submit", (evento) => {
  evento.preventDefault();
  const caso = analisis?.casos.find((alerta) => alerta.id === seleccionado);
  if (!caso) return;
  const datos = borradores.get(caso.id) || {
    id: caso.id,
    estado: caso.estado,
    veredicto: caso.veredicto,
    notas: caso.notas,
    version: caso.version,
  };
  realizar(async () => {
    const respuesta = await api("/api/casos", datos);
    const borradorActual = borradores.get(caso.id);
    if (
      !borradorActual ||
      (borradorActual.estado === datos.estado &&
        borradorActual.veredicto === datos.veredicto &&
        borradorActual.notas === datos.notas)
    ) {
      borradores.delete(caso.id);
    } else {
      borradorActual.version = respuesta.casos.find(
        (alerta) => alerta.id === caso.id,
      ).version;
    }
    recibir(respuesta, true);
    avisar(`Investigación de ${caso.usuario} guardada en este equipo.`);
  });
});

$("exportar").addEventListener("click", (evento) => {
  if (!analisis || borradores.size) {
    evento.preventDefault();
    avisar("Guarda las notas pendientes antes de exportar el informe.", true);
  }
});

window.addEventListener("beforeunload", (evento) => {
  if (borradores.size) {
    evento.preventDefault();
    evento.returnValue = "";
  }
});

realizar(async () => {
  const identidad = new URL(window.location.href).searchParams.get("analisis");
  recibir(
    await api(
      identidad
        ? `/api/estado?analisis=${encodeURIComponent(identidad)}`
        : "/api/estado",
    ),
  );
});
