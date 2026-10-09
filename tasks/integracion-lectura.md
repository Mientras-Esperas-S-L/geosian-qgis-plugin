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

Desde el 09/10 el usuario pide que **los fallos de la web que se encuentren se arreglen**,
cada uno en su rama del frontal (o del backend) con su prueba y su PR, sin fusionar, en
vez de solo anotarlos.

## Casillas de lectura

- [x] Melilla local: comparar una a una las 8 capas y sus vistas activables, a varios zooms.
- [x] Vistas de información adicional (`context_type = additional_info`): hoy no se abren.
- [x] Iconos de vista por categoría si el editor los admite; tamaños y halo comparados.
      (no aplica: el editor solo tiene `defaultIcon`; tamaño y halo coinciden)
- [ ] Visualizaciones sin equivalente (hexágonos, contornos, H3): decidir aproximación.
      (PENDIENTE DE DECISIÓN, ver hallazgos; se sigue con lo demás)
- [x] Tabla de atributos en capas grandes: hoy solo enseña lo descargado. ¿Recuento y
      paginado desde la API?
- [x] Ficha del elemento: secciones, `visible_if` y valores, comparadas con la web.
- [x] Información adicional (partes) de un elemento, en solo lectura.
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

- 09/10 · Melilla local, capas base a zoom 13, 14 y 15 contra la web en el mismo encuadre:
  coinciden capas, orden, colores del LAD y tamaños. La única diferencia (árboles sobre el
  riego en el Parque Hernández) era de la web: el PR frontal #201 no tapaba entre tramos por
  la prueba de profundidad. Corregido en ese PR (`1b84121b`), comprobado leyendo el píxel
  del canvas. Banco: `comparar.py` usaba `customLayerOrder()` sin orden propio; corregido.
  Truco útil: `deck.pickMultipleObjects` NO sirve para saber qué se ve encima; leer el píxel
  con `gl.readPixels` tras `deck.redraw()`.

- 09/10 · Vistas 12, 11 y 69 de Melilla local (las 3 que ve la cuenta): coinciden filtro,
  colores por categoría e iconos. Dos ajustes: las vistas se pintan encima de todas las
  capas base, como la web (orden de pintado propio del proyecto), y una vista activa
  sustituye siempre a su capa, también las de icono (`layerBaseVisible` de maps.jsx).
  Prueba `test_vista_activa_sustituye_su_capa_y_se_pinta_encima`.

- 09/10 · Vistas `additional_info`: la web no mira `context_type` al pintar y su editor
  solo crea vistas de elementos; en local no hay ninguna. El plugin las deshabilitaba;
  ahora se abren como las demás. Prueba
  `test_las_vistas_de_informacion_adicional_se_ofrecen_como_las_demas`.

- 09/10 · Tabla de capas grandes: sin recuadro, el proveedor carga por páginas los primeros
  50.000 (`TABLE_CAP`) y avisa del total. Nueva York local: 50.000 de 1.078.380 en 13,6 s.
  Prueba `test_capa_grande_sin_recuadro_carga_hasta_el_tope_y_avisa`.

- 09/10 · Ficha de la palmera 29999 de Melilla local contra la web. Tres arreglos:
  las pestañas condicionales (Arbolado/Palmeras) salían siempre ocultas porque la
  expresión usaba `is_array`, que QGIS no tiene, y no compilaba; ahora `try(array_contains…)`
  y una guarda de «tiene valor» que vale para listas (en QGIS `to_string` de una lista es
  NULL). Los campos `visible: false` ya no salen en el formulario (siguen en la tabla). Y
  hay pestaña «Información Principal» con `schema.main_attributes`, como la web. Pruebas
  `test_schema_qgis.py` (evalúa las expresiones en QGIS), `test_campo_invisible_…` y
  `test_atributos_principales_…`.

- 09/10 · Partes de la palmera 29999 de Melilla local contra la web: mismos 5 tipos
  (los de palmeras y la Ficha GIP), en el mismo orden, y los mismos 2 partes de trabajo,
  el más reciente primero. Cada tipo de parte es una tabla sin geometría
  (`geosian://…/layer/<id>/info/<nombre>`) en el grupo plegado «Información adicional»,
  relacionada con su capa por `geodata_id`; la ficha tiene la pestaña «Información
  adicional» con un grupo por tipo, visible según sus `attribute_dependencies` como en
  `FeatureInfo.jsx`. Los partes de un elemento se piden al abrir su ficha (18 partes en
  0,06 s); abrir Melilla entero sigue en 2 s. La cuenta de QGIS no veía ninguno: la API
  filtra por `AdditionalInformationPermission` y su grupo no tenía; le di `can_view` en
  local a los 9 tipos de Arbolado. Pruebas `test_los_partes_*` y
  `test_los_partes_de_la_capa_salen_en_su_ficha`.

## Hallazgos para decidir

_(lo que no es del plugin o pide una decisión del usuario)_

- La cuenta de QGIS solo ve las vistas públicas o propias: de las 8 vistas de Melilla local
  ve 3 (69, 12, 11). Las privadas de otros usuarios no las ve, igual que en la web. Si se
  quieren comparar todas, hay que hacerlas públicas o crearlas con esa cuenta.
- **Las vistas se pintan encima de TODAS las capas base** en la web (`maps.jsx` pone el
  lote al fondo y añade las vistas después; lo dice un comentario, es a propósito). Una
  vista de una capa baja del panel tapa capas más altas. Choca con el «orden estricto del
  panel». QGIS lo imita de momento. ¿Se queda así o las vistas van en el sitio de su capa?
- Código muerto en la web: `useMvtLayers.js:126-140` dice que las vistas de icono, calor
  y agregación son superposiciones y dejan la base, pero `layerBaseVisible` (maps.jsx
  1695-1710) oculta la base con CUALQUIER vista activa y esa rama nunca se alcanza. Lo que
  se ve es lo segundo. ¿Se corrige el comentario o se quiere de verdad la superposición?
- **Hexágonos, contornos y H3**: local tiene 1 vista de hexágonos y devel ninguna (devel:
  17 de color, 13 de icono, 2 de calor). Propuesta para igualar la web: pedir las teselas
  ya agregadas del servidor (`/geodata/tiles/…mvt?agg=hex…`) como capa de teselas
  vectoriales de QGIS, autenticada con el token en un authcfg de tipo cabecera, y colorear
  por `count` con la misma escala logarítmica. Exacto pero con trabajo; sin decisión, hoy
  se pintan con el color de la vista y se avisa.
- **API, mejora posible**: `/geodata/paginated/` no admite `no_geometry` (solo el listado
  simple, que rechaza más de 100.000). Con él, la tabla de capas grandes bajaría solo
  atributos y tardaría bastante menos. Cambio pequeño en `list_paginated`; no hecho aún.
- `context_type = additional_info` en las vistas no lo usa nada de la web (solo existe en
  el modelo y en el servicio). ¿Se retira o está previsto para algo?
- Iconos de vista: mismo tamaño (metros, mínimo 8 px), pero en la web se ven más
  difuminados; no parece de datos. Sin tocar.
- **Ficha: campos vacíos**. La web, al ver un elemento, no enseña los campos sin valor ni
  las secciones que se quedan sin ninguno (en la palmera, «Plantación zona verde» y
  «Zona plantación, tocón»). QGIS sí: su formulario es por capa y servirá para editar. Se
  deja así salvo que se quiera una ficha de solo lectura aparte.
- **Fallo de la web, arreglado en el PR frontal #202**: en «Registro adicional» el pie decía
  «1-10 de 10» con 2 partes. El total salía de páginas × 10 porque `FeatureInfo` no pasaba
  `totalItems` a `AdditionalInfo` (no era el `useEffect` de la línea 165, como apunté al
  principio).
- Los partes no enseñan aún sus fotos ni adjuntos: es la casilla siguiente.
- El usuario usa a la vez la pestaña de `localhost:3000`: para comparar sin estorbarle,
  abrir una pestaña propia. Activar vistas en la web cambia los ajustes de `tester2`.

## Antecedentes

Ya hecho antes de este plan (ver memoria `project_qgis_plugin_diseno`): estilos del LAD,
vistas con filtro `attr__` y estilo (iconos de react-icons incluidos), mapa entero con
orden y carpetas, capas grandes por zona, LAD en paralelo, orden de pintado estricto del
panel, agrupación por espacio de trabajo. PR backend #287 (lista vacía ≠ 403) y frontal
#201 (orden del panel entre tipos de geometría) pendientes de revisión.
