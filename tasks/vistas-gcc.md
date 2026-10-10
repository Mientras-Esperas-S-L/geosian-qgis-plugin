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
- [ ] `h3hexagon`: como lo pinta la web sobre una capa grande (los hexágonos del servidor).
      DECIDE si en capas pequeñas hace falta H3 de verdad (la web usa `h3-js` con
      `resolution`; QGIS no trae H3 y habría que llevar la biblioteca o implementarla).

- [ ] Leyenda de las agregadas: degradado de la rampa con «Baja densidad» y «Alta
      densidad», como la web (hoy la capa de teselas enseña una sola entrada, «Celdas»).
- [ ] Tiempo real en las agregadas: un `layer_data_changed` de su capa tiene que repintar
      las teselas (hoy la capa de teselas no se entera).

### Calor y contornos
- [ ] `heatmap` en capas pequeñas: el renderizador de calor de QGIS con los parámetros de la
      web (`radiusPixels`, `intensity`, `threshold` como transparencia inicial, rampa de 6,
      `weightAttribute` también de información adicional).
- [ ] `heatmap` en capas grandes: los centroides de las celdas del servidor
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

## Hallazgos para decidir

_(lo que no es del plugin o pide una decisión)_
