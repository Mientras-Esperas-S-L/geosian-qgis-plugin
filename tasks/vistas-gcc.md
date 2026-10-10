# Todas las vistas de GCC en QGIS

Encargo del 10/10/2026: «soporte total de todos los tipos de vistas que tenemos en GCC».
Inventario sacado del código de la web y del backend (`LayerViewStyleEditor.jsx`,
`viewStyleProcessor.js`, `viewLayerGenerators.js`, `useMvtLayers.js`, `maps.jsx`,
`serializers/layer.py`, `geodata_tiles.py`, `tile_utils.py`).

## Prompt del bucle

```
/loop Sigue el plan de ~/Projects/geosian/geosian-qgis-plugin/tasks/vistas-gcc.md: coge la
primera casilla abierta que no espere una decisión mía, hazla y compruébala de verdad (QGIS de
pruebas por el mando, con captura de la ventana entera de QGIS, la web local en una pestaña tuya
y la API), con una prueba que falle sin el arreglo. El plugin va en la rama
fix/make-install-qgis4 (push sí; el PR #1 ya está abierto, no fusionar). Si a la API o a la web
les falta algo o tienen un fallo, arréglalo en su repo, en su rama, con pruebas y con su PR,
sin fusionar. Nada de producción. Apunta en el plan lo hecho, lo comprobado y lo que no. Las
casillas «DECIDE» déjalas para el final y pregúntamelas juntas. Cuando solo queden casillas
«DECIDE», para y avísame con las capturas de cada tipo de vista.
```

## Lo que hay en GCC

Dos ejes independientes en `style_config`:

- **`visualization`**: `default` | `icon` | `heatmap` | `hexagon` | `h3hexagon` | `contour`.
  Los cuatro últimos solo se aplican a puntos. Cada uno lleva su configuración en una clave
  con su nombre (`style_config.hexagon`, …). Opacidad de la capa: `point.opacity` (0,9).
- **`mode`** (cómo se colorea, con `default` e `icon`): `single` | `categorized` |
  `graduated` | `rule_based`. El atributo puede ser `additional_info.<tipo>.<campo>`
  (se pide con `include_ai_attr=<tipo>.<campo>`).

Cómo pinta la web las agregadas:

- **Capa pequeña (GeoJSON)**: deck.gl agrega en el navegador (`HexagonLayer` con `radius` en
  metros, `H3HexagonLayer` con `resolution`, `HeatmapLayer`, `ContourLayer` con `cellSize`).
- **Capa grande (MVT)**: el servidor agrega en teselas
  `/api/v1/geodata/tiles/{z}/{x}/{y}.mvt?layer_id=&agg=hex[&geom=centroid&cells=96][&weight=]`,
  con la cabecera `Authorization: Token …`. Capa MVT `agg`, propiedades `count`, `weight`,
  `lng`, `lat`, `density`. Hexágonos de PostGIS (no H3) con lado según el zoom. Color:
  rampa de 6 en escala logarítmica, `t = min(1, ln(1+count)/ln(1+colorMax))`, `colorMax`
  100, alfa 200, opacidad 0,8. Calor y contornos: los centroides de celda alimentan un
  `HeatmapLayer` o `ContourLayer` normal.

Hoy en QGIS: `default` con los cuatro modos, `icon` y `heatmap` aproximado (rampa de dos
colores, sin `intensity` ni `threshold`). `hexagon`, `h3hexagon` y `contour` se pintan como
puntos con aviso.

## Casillas

### Teselas agregadas del servidor
- [x] Teselas autenticadas: un `authcfg` de cabecera (`APIHeader`, `Authorization: Token …`)
      por conexión, nunca la credencial en la URI ni en el proyecto; se renueva al volver a
      entrar. Una capa de teselas vectoriales de `…/tiles/{z}/{x}/{y}.mvt?layer_id=&agg=hex`
      con los filtros de la vista. Si la API no deja (CORS no aplica; ETag, 403 sin
      `MapUser`), se arregla allí.
- [x] `hexagon`: esa capa con relleno por `count`, rampa de 6, escala logarítmica con
      `colorMax`, alfa 200 y la opacidad de la vista; leyenda «Baja densidad / Alta densidad».
- [x] `h3hexagon`: como lo pinta la web sobre una capa grande (los hexágonos del servidor).
- [ ] DECIDE · H3 de verdad en capas pequeñas: la web usa `h3-js` con `resolution` en el
      navegador; QGIS no trae H3 (habría que llevar la biblioteca `h3` o implementar la
      rejilla). Hoy van los hexágonos del servidor, como la web en capas grandes.

- [x] Leyenda de las agregadas: degradado de la rampa con «Baja densidad» y «Alta
      densidad», como la web (hoy la capa de teselas enseña una sola entrada, «Celdas»).
- [x] Tiempo real en las agregadas: un `layer_data_changed` de su capa tiene que repintar
      las teselas (hoy la capa de teselas no se entera).

### Calor y contornos
- [x] `heatmap` en capas pequeñas: el renderizador de calor de QGIS con los parámetros de la
      web (`radiusPixels`, `intensity`, `threshold` como transparencia inicial, rampa de 6,
      `weightAttribute` también de información adicional).
- [x] `heatmap` en capas grandes: los centroides de las celdas del servidor
      (`agg=hex&geom=centroid&cells=96`, peso `weight` o `count`) como puntos de un calor de
      QGIS; si no se puede con teselas, las celdas como polígonos coloreados por `density`
      (lo que hace la web en móvil). Anotar cuál.
- [ ] `contour`: rejilla de `cellSize` metros con la suma (o media) de los puntos, isolíneas por
      cada `threshold` con su `color` y `strokeWidth`. Capas pequeñas con sus puntos; grandes
      con los centroides del servidor.

### Fidelidad de lo que ya hay
- [ ] Rampas exactas de la web (`colorRamps.js`: 5 colores interpolados a 6, como
      `generatePalette`), con `oranges`, que falta.
- [ ] Opacidad de la vista (`point.opacity`, `line.opacity`, `polygon.fillOpacity`) aplicada.
- [ ] Atributos de información adicional en el estilo (`additional_info.<tipo>.<campo>` en
      `categorized`, `graduated` y en el peso del calor), pedidos con `include_ai_attr`.
- [ ] `graduated` con `colorRamp` y cortes, y `rule_based` con todos los operadores del
      frontal, cotejados con `viewStyleProcessor.js`.
- [ ] `icon`: `colored` y `fixedColor`, `sizeMin`/`sizeMax`, color por el modo de la vista o
      el de la capa; sin `defaultIcon`, nada (como la web).

### Repaso
- [ ] Cada tipo lado a lado con la web local, con captura de la ventana entera de QGIS, en
      capas pequeñas y grandes. Si en local falta algún tipo de vista, crear una de prueba
      con nombre ficticio desde el shell de Django local (nunca en devel ni producción).

## Hecho

_(cada vuelta añade una línea: fecha, casilla, prueba, commit y qué se comprobó de verdad)_
- 10/10 · Teselas autenticadas y `hexagon`. `connections.tile_authcfg`: un `authcfg`
  `APIHeader` (`Authorization: Token …`) por conexión, guardado en el gestor de QGIS, que se
  actualiza al volver a entrar y se borra con la conexión; la URI de la capa solo lleva su id.
  `core/aggregated.py` arma la URI de `…/tiles/{z}/{x}/{y}.mvt?layer_id=&agg=hex` con los
  filtros de la vista y la expresión de color (`count`, rampa de 6, escala logarítmica con
  `colorMax`, alfa 200); el panel añade esa capa de teselas en lugar de los puntos, con la
  opacidad de la vista (`point.opacity`). Las pruebas usan ya una base de autenticación
  temporal con su contraseña maestra (`conftest.py`), nunca la del perfil. Pruebas en
  `test_agregadas.py` (4, fallaban). Comprobado en una QGIS de pruebas nueva (perfil
  `vistas`, porque la del perfil `pruebas` tiene una contraseña maestra que no puse yo)
  contra el backend local: vista «Hexágonos densidad (prototipo)» de Cáceres, capa de teselas
  con `authcfg` y sin el token en la fuente, hexágonos coloreados por número de árboles
  (`scratchpad/vistas/hexagonos-qgis.png`). Suite 221 en QGIS 4 y 218 (+3) en 3.34 (en 3.34
  la propiedad se llama `PropertyFillColor`). **No comparado aún con la web**: activar la
  vista en la web local cambia el mapa y la vista guardados de `tester2`; va en el repaso.
- 10/10 · `h3hexagon`: ya entraba con los hexágonos (misma vía; rampa por omisión
  `plasma`, como la web). Prueba `test_h3_va_por_los_hexagonos_del_servidor_como_la_web_en_capas_grandes`
  (no falla sin arreglo: el arreglo es el de los hexágonos). Comprobado con una vista de
  prueba creada en la base local («Prueba QGIS · H3», id 119, en el arbolado de Cáceres):
  capa de teselas con opacidad 0,85 y rampa plasma (`scratchpad/vistas/h3-qgis.png`).
- 10/10 · Leyenda de las agregadas. QGIS no da leyenda a las capas de teselas vectoriales:
  `gui/leyendas.py` pone una propia, un degradado (`QgsColorRampLegendNode`) con la rampa de la
  vista y «Baja densidad» / «Alta densidad», como la web; la rampa va en una propiedad de la
  capa y la leyenda vuelve al abrir el proyecto. Las celdas se pintan ahora con un estilo por
  tramo (seis, con el filtro del tramo) en vez de un color calculado. Trampa: el nodo de
  leyenda creado en Python hay que cedérselo a QGIS (`sip.transferto`) o se cae. Prueba
  `test_la_leyenda_de_las_agregadas_es_el_degradado_de_la_web` (fallaba; también reabre el
  proyecto). Comprobado en la QGIS de pruebas: un nodo de leyenda bajo la capa, con el
  degradado (`scratchpad/vistas/hexagonos-qgis.png`). Suite 223 en QGIS 4 y 220 (+3) en 3.34.
- 10/10 · Tiempo real en las agregadas. La capa agregada guarda de dónde viene (conexión,
  mapa, capa, filtros, `authcfg`) en una propiedad; el concentrador la trata como a las del
  proveedor: se suscribe a su mapa (antes no: la vista sustituye a los puntos y nadie se
  suscribía) y, con un `layer_data_changed` de su capa, la vuelve a pedir con la
  `tile_version` del aviso (`_v`, como la web), conservando estilo y leyenda. Prueba
  `test_las_agregadas_se_suscriben_y_se_repintan_con_el_tiempo_real` (fallaba). Comprobado
  contra el backend local con su ASGI (`qgis-local-ws`, parado al acabar): suscrita al mapa
  19, un `notify_layer_data_changed` de la capa 120 desde el shell de Django (sin tocar datos;
  `tile_version` local de 0 a 1) llega y la fuente pasa a `_v=1`, con sus 6 estilos y su
  leyenda. Suite 224 en QGIS 4 y 221 (+3) en 3.34.
- 10/10 · `heatmap` en capas pequeñas: el renderizador de calor de QGIS con `radiusPixels`, y
  una rampa como la del `HeatmapLayer` de la web: transparente hasta `threshold`, los seis
  colores de la rampa desde ahí y saturando en `1/intensity`; leyenda «Baja densidad» /
  «Alta densidad» (en QGIS 3.34 no se puede cambiar: «Mínimo» / «Máximo»). Peso por
  `weightAttribute` de la capa; el de información adicional va con su casilla. `aggregation:
  MEAN` no tiene equivalente en el calor de QGIS (suma). Prueba
  `test_el_calor_usa_radio_intensidad_umbral_y_la_rampa_entera` (fallaba). Comprobado con la
  vista local «Tipo de valvula» (válvulas de Melilla, 239, como `tester2`, que es quien la ve):
  radio 30, paradas desde 0,05, rampa inferno (`scratchpad/vistas/calor-qgis.png`). Suite 225
  en QGIS 4 y 222 (+3) en 3.34.
- 10/10 · `heatmap` en capas grandes. Antes, de lejos no salía nada (la capa grande solo se
  pinta desde 1:20.000). QGIS no pinta calor sobre teselas vectoriales, así que va lo que la
  web hace en móvil: las celdas finas del servidor (`agg=hex&cells=96`) coloreadas por número
  de puntos con la rampa de la vista, su leyenda y su tiempo real. Las capas pequeñas siguen
  con el calor de QGIS. Prueba `test_el_calor_de_una_capa_grande_va_con_las_celdas_del_servidor`
  (las dos variantes; la grande fallaba). Comprobado con una vista de prueba creada en local
  («Prueba QGIS · Calor», id 120, sobre el arbolado de Nueva York, 1.078.380): a 1:93.000 las
  celdas cubren la ciudad (`scratchpad/vistas/calor-capa-grande-qgis.png`). Dos cosas vistas:
  el mapa base propio solo cubre España (en Nueva York no hay fondo) y QGIS recorta cada
  celda al borde de su tesela, así que se ven costuras finas (la web pinta sin recorte).

## Hallazgos para decidir

_(lo que no es del plugin o pide una decisión)_
- **Costuras entre teselas en las agregadas**: QGIS recorta cada celda al borde de su
  tesela y se ven líneas finas donde se juntan; la web las pinta sin recorte. Se quitaría
  pidiendo las celdas como polígonos sueltos (proveedor propio que decodifique las teselas)
  en vez de capa de teselas vectoriales. Más trabajo; decidir si compensa.
