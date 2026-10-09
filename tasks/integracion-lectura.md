# QGIS ↔ GCC: integración completa en solo lectura

Plan vivo del bucle (`tasks/integracion-lectura.md` del repo del plugin). Cada vuelta lee este fichero, coge **una** casilla abierta, la cierra
con prueba y deja anotado aquí lo que hizo. Cuando no queden casillas de lectura, el bucle
**para** y se avisa al usuario para repasar antes de empezar la escritura (fase 2).

## Objetivo

Que abrir un mapa de GCC en QGIS, a través de la API de Geosian, se vea y se consulte igual
que en la web: capas, orden, carpetas, estilos del LAD, vistas, etiquetas, fichas, filtros,
información adicional y adjuntos. Solo lectura: QGIS no escribe nada en esta fase.

Se respeta la API. Si a la API le falta algo para integrarse bien (un filtro, un recuento,
un endpoint), se hace en el backend, con pruebas, en su rama y con su PR. No se lee la base
de datos por detrás de la API.

## Entorno (montado el 09/10/2026)

- **Plugin**: `~/Projects/geosian/geosian-qgis-plugin`, rama `fix/make-install-qgis4`
  (o una nueva desde ella). Pruebas: `make test`. Lint: `.venv/bin/python -m ruff check`.
- **QGIS de pruebas** con perfil aparte y mando por ficheros: órdenes Python en
  `<scratchpad>/mando/cmd/NN.py`, salida en `mando/out/NN.txt`, capturas con
  `captura(nombre, widget)`. Ayudas: `recargar.py` (recarga el plugin), `comparar.py`
  (`pintar(bounds, size, nombre)` pinta un recuadro con el orden del panel y PNOA). El
  proveedor se recarga con el plugin. Si un diálogo modal bloquea el mando, matar esa QGIS
  por PID (nunca la del usuario) y relanzarla.
- **Backend local**: contenedor `qgis-local-api` en `localhost:8010` (worktree
  `wt-backend-mapa-vacio`, imagen `drf_geosian:latest`). Cuenta de QGIS
  `qgis.pruebas@ejemplo.local`: no privilegiada, grupo «QGIS pruebas (solo lectura)» en
  los 39 mapas; token en `wt-backend-mapa-vacio/.qgis-token-local`. Tiene copiados los
  ajustes de Melilla (mapa 3) de `tester2`.
- **Frontal local**: `localhost:3000` (worktree `wt-frontend-orden-z`) contra el backend
  local, sesión de `tester2`. El encuadre exacto de la web sale de
  `window.__geosianDeck().getViewports()[0].getBounds()`.
- **Devel** (`api.devel.greencitycontrol.com`) sirve para contrastar con datos reales.
  **Producción no se toca.**

## Cómo es cada vuelta

1. Elegir la primera casilla abierta de la lista.
2. Reproducir en la web y en QGIS el mismo mapa y el mismo encuadre. Mirar el código del
   frontal que lo pinta antes de suponer nada: el criterio es lo que hace la web.
3. Si QGIS difiere, corregir el plugin con una prueba que falle sin el arreglo.
   - Si la causa es la web y no QGIS, no se copia el fallo: se apunta aquí y se pregunta.
   - Si falta algo en la API, hacerlo en el backend (rama, pruebas, PR) y usarlo.
4. Medir con datos grandes cuando toque rendimiento (Nueva York, Pamplona, Mijas).
5. Commit en conventional commits, en castellano, sin firmas automáticas. Push a la rama.
   PR solo en backend o frontal y cuando haya algo que integrar; **nunca fusionar**.
6. Anotar en «Hecho» qué se cerró, con la prueba y el commit, y en «Hallazgos» lo que
   haya que decidir.

## Casillas de lectura

- [ ] Melilla local: comparar una a una las 8 capas y sus vistas activables, a varios zooms.
- [ ] Vistas de información adicional (`context_type = additional_info`): hoy no se abren.
- [ ] Iconos de vista por categoría si el editor los admite; tamaños y halo comparados.
- [ ] Visualizaciones sin equivalente (hexágonos, contornos, H3): decidir aproximación.
- [ ] Tabla de atributos en capas grandes: hoy solo enseña lo descargado. ¿Recuento y
      paginado desde la API?
- [ ] Ficha del elemento: secciones, `visible_if` y valores, comparadas con la web.
- [ ] Información adicional (partes) de un elemento, en solo lectura.
- [ ] Fotos y adjuntos de un elemento, en solo lectura (enlaces firmados de `/media/`).
- [ ] Filtros de la web (panel «Filtros») aplicables a una capa de QGIS.
- [ ] Etiquetas: las que la web permite encender, no solo las de por defecto.
- [ ] Mapa base: equivalente al GEOSIAN vectorial (estilo MapLibre) o, al menos, el que
      tenga elegido el mapa (`basemaps[]`).
- [ ] Estructura publicada del mapa (`map_structure`, modo básico) con grupos anidados.
- [ ] Tiempo real (WebSocket `/ws/layer-data/`): refrescar lo que cambie en la web.
- [ ] Proyecto guardado: reabrir, refrescar credenciales caducadas, mensajes claros.
- [ ] Errores: 401, 403, red caída, capa borrada; ninguno debe colgar QGIS.

## Hecho

_(cada vuelta añade una línea: fecha, casilla, prueba, commit)_

## Hallazgos para decidir

_(lo que no es del plugin o pide una decisión del usuario)_

## Antecedentes

Ya hecho antes de este plan (ver memoria `project_qgis_plugin_diseno`): estilos del LAD,
vistas con filtro `attr__` y estilo (iconos de react-icons incluidos), mapa entero con
orden y carpetas, capas grandes por zona, LAD en paralelo, orden de pintado estricto del
panel, agrupación por espacio de trabajo. PR backend #287 (lista vacía ≠ 403) y frontal
#201 (orden del panel entre tipos de geometría) pendientes de revisión.
