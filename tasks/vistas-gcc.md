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
- [x] `contour`: rejilla de `cellSize` metros con la suma (o media) de los puntos, isolíneas por
      cada `threshold` con su `color` y `strokeWidth`. Capas pequeñas con sus puntos; grandes
      con los centroides del servidor.

- [x] Contornos sin congelar la ventana: hoy se piden las teselas y se trazan al añadir la
      capa, en el hilo de la ventana (8,1 s en el arbolado de Cáceres, 64 teselas por unos
      árboles sueltos lejos). Calcular en segundo plano y pintar al terminar.

### Fidelidad de lo que ya hay
- [x] Rampas exactas de la web (`colorRamps.js`: 5 colores interpolados a 6, como
      `generatePalette`), con `oranges`, que falta.
- [x] Opacidad de la vista (`point.opacity`, `line.opacity`, `polygon.fillOpacity`) aplicada.
- [x] Atributos de información adicional en el estilo (`additional_info.<tipo>.<campo>` en
      `categorized`, `graduated` y en el peso del calor), pedidos con `include_ai_attr`.
- [x] `graduated` con `colorRamp` y cortes, y `rule_based` con todos los operadores del
      frontal, cotejados con `viewStyleProcessor.js`.
- [x] `icon`: `colored` y `fixedColor`, `sizeMin`/`sizeMax`, color por el modo de la vista o
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
- 10/10 · `contour`. `core/contours.py`: rejilla de `cellSize` metros (suma o media) e
  isolíneas por *marching squares*, cerradas, con las sillas resueltas por el centro.
  `core/mvt.py`: lector mínimo de MVT (propiedades de las celdas; con gzip). Los puntos son los
  centroides de las celdas del servidor (`agg=hex&geom=centroid&cells=96`) a un zoom en que
  cada celda mide la mitad de `cellSize`, como mucho 64 teselas: vale para capas pequeñas y
  grandes, respeta los filtros de la vista, pesa por `weightAttribute` (`&weight=`) y se
  recalcula con el tiempo real. `gui/contornos.py`: capa de líneas en memoria, una por umbral
  con su color, su grosor en píxeles y su leyenda «≥ umbral»; la opacidad de la vista. Las
  bandas (`threshold: [a, b]`) no las crea el editor de la web y se omiten. Pruebas en
  `test_contornos.py` (7), `test_mvt.py` (2, con un codificador aparte) y
  `test_los_contornos_son_isolineas_por_umbral_con_su_color_y_grosor` (fallaba); el servidor
  falso sirve ya teselas. Comprobado con una vista de prueba creada en local («Prueba QGIS ·
  Contornos», id 121, arbolado de Cáceres, los umbrales por omisión del editor): las cuatro
  isolíneas sobre la ciudad (`scratchpad/vistas/contornos-qgis.png`). Tarda 8,1 s en el hilo de
  la ventana: casilla nueva. Suite 237 en QGIS 4 y 234 (+3) en 3.34.
- 10/10 · Contornos sin congelar la ventana. Dos causas: las teselas se pedían y trazaban en
  el hilo de la ventana, y casi todo el tiempo se iba en otra cosa: `extent()` del proveedor con
  una vista baja todos los puntos para ajustar la extensión, y se usaba solo para saber qué
  teselas pedir. Ahora la extensión sale de los metadatos (`metadata_extent()`) y el trazado va
  en una `QgsTask`; la capa entra vacía y se rellena al terminar (también al recalcular con el
  tiempo real). Prueba ampliada en `test_los_contornos_son_isolineas_por_umbral_con_su_color_y_grosor`
  (entra vacía, sin bajar puntos, y se rellena; fallaba). Medido en la QGIS de pruebas, arbolado
  de Cáceres: añadir la capa 8,17 s → 0,07 s; las líneas, a los 0,1 s, con el bucle de la ventana
  sin pasar de 0,026 s por vuelta. Suite 237 en QGIS 4 y 234 (+3) en 3.34.
- 10/10 · Rampas exactas. Las 20 rampas de `COLOR_RAMPS` (`colorRamps.js`) copiadas a
  `resources/rampas.json` (con su origen) y `ramp_colors` como `generatePalette`: equidistantes
  si se piden menos colores que la rampa, interpoladas si más, con el redondeo de JavaScript;
  sin rampa conocida, la de deck.gl. Entran `oranges` (faltaba) y las de categorías. Prueba
  `test_las_rampas_son_las_de_la_web`, con valores sacados con node de la propia función de la
  web (fallaba: la copia anterior tenía 3 colores por rampa). Comprobado en la QGIS de pruebas:
  las seis celdas de los hexágonos de Cáceres con los colores de la web
  (`scratchpad/vistas/hexagonos-qgis.png`). Suite 238.
- 10/10 · Opacidad de la vista. Mirado en la web: `point.opacity` (0,9 si no dice) es la de
  las visualizaciones avanzadas (calor, hexágonos, iconos, contornos, H3: `maps.jsx`); en las
  normales la transparencia va en el color (alfa 230, que el complemento ya respeta) y
  `polygon.fillOpacity` solo cuenta con colores opacos. Faltaba en el calor de capas pequeñas
  y en los iconos. Prueba `test_la_opacidad_de_la_vista_como_la_web` (calor, iconos y una
  normal; fallaba). Comprobado en la QGIS de pruebas: «Tipo de valvula» y los iconos de
  palmeras de Algeciras, 0,9 (`scratchpad/vistas/iconos-qgis.png`). Suite 241 en QGIS 4 y 238
  (+3) en 3.34.

- 10/10 · Atributos de información adicional en el estilo. Una vista que colorea o pesa por
  `additional_info.<tipo>.<campo>` (`views.ai_attribute`: color, `weightAttribute` de calor y
  contornos) pide `include_ai_attr=<tipo>.<campo>` y la capa tiene ese campo con el nombre de
  la web y alias «<parte> · <campo>», así el estilo lo encuentra sin tocarlo. Las listas se
  escriben como `String()` de la web (`["Poda"]` → «Poda»), o no casan con la categoría.
  Prueba `test_una_vista_que_colorea_por_un_campo_de_los_partes` (fallaba; también con un
  valor en lista). **Fallo del backend**: con `data_type` la API devolvía el campo vacío
  (buscaba el modelo con el nombre del LAD y llevaba líneas y polígonos a las tablas simples).
  Arreglado en la rama `fix/include-ai-attr-data-type`, PR greencity-backend#296 sin fusionar,
  con su prueba (fallaba) y la batería en verde salvo una de IoT que depende de la fecha.
  Comprobado en la QGIS de pruebas contra una API temporal con el arreglo (puerto 8012,
  parada al acabar), vista «Poda» del arbolado de Cáceres: 49.551 árboles, 13.160
  «Mantenimiento», 1.182 «Tala», etc., y 34.110 sin parte en «Otros»; contra la API sin el
  arreglo, todos vacíos (`scratchpad/vistas/poda-partes-qgis.png`). Commit 889a0e3. Prueba aparte
  `test_graduado_y_peso_del_calor_por_un_campo_de_los_partes`: el texto del parte se lee como
  número al graduar y al pesar el calor (no falla sin arreglo: cubre lo que ya hacía
  `to_real`). **No comprobado**: `graduated` y calor por un campo de parte con datos reales
  (en local no hay vistas así), y la comparación con la web, que va en el repaso.
  **Tiempo real** (lo preguntaste el 10/10): crear y editar un parte ya avisaban por websocket;
  borrarlo, no, y el árbol seguía con el color del parte borrado. Arreglado en la rama
  `fix/aviso-al-borrar-parte`, PR greencity-backend#297 sin fusionar, con su prueba (fallaba).
  Comprobado de punta a punta en la QGIS de pruebas con la API y el websocket locales con los dos
  arreglos: llegan `create` y `delete`, QGIS vuelve a pedir la capa solo y el árbol pasa de gris
  a «Tala» y otra vez a gris, sin leer nada desde QGIS antes de capturar
  (`scratchpad/vistas/poda-tiempo-real-{antes,creado,borrado}.png`). El parte de prueba se borró.
  Trampa del banco: la batería del backend vacía la caché de Redis (`cache.clear()`) y en
  desarrollo esa base es la misma que la de las suscripciones del websocket; el primer intento
  falló por eso, no por el producto.

- 10/10 · `graduated` y `rule_based` cotejados con la web. El editor de la web no ofrece
  estos dos modos (solo «Color único» y «Por categoría»): solo se crean por la API, y en local
  no había ninguna vista así. Diferencias que había con `buildFastViewColorFn`, todas
  arregladas: el valor justo en un corte caía en el tramo de abajo (los tramos de QGIS
  cierran por arriba; la web, por abajo); lo que no es número no se pintaba (la web lo pinta
  del color por omisión, gris si no lo hay); un tramo sin color tomaba el último (la web, el
  de por omisión); `colorRamp` sin `colors` iba a saltos (la web interpola continuo, con
  `getColorFromRamp`: ahora es un color calculado por expresión, con su borde); en las
  reglas, un valor vacío en una regla anterior anulaba las siguientes (`NOT NULL`), una regla
  sin color se saltaba (la web la pinta de gris y tapa a las siguientes), un filtro sin
  condiciones no casaba (en la web casa siempre), un operador desconocido se ignoraba (en la
  web no casa) y sin `else` lo que no casaba no se pintaba (la web, gris). Tramos y reglas van
  ahora como reglas de QGIS con «Otros». Prueba `test_colores_web.py`: seis casos ficticios
  con los colores sacados con node de la propia función de la web (`tests/colores_web.mjs` →
  `colores_web.json`, frontal main d7ea44e0); fallaban cinco. Comprobado en la QGIS de pruebas
  con tres vistas de prueba creadas en la base local (122 «Prueba QGIS · Graduada», 123
  «· Rampa», 124 «· Reglas», en el arbolado de Cáceres; por `id`, porque sus campos numéricos
  valen todos 1): árbol a árbol, el color de QGIS y el de la función de la web coinciden en
  49.557 de 49.557 en las tres; el cotejo detecta un corte movido una unidad
  (`scratchpad/vistas/vista-12{2,3,4}-qgis.png`). Suite 249 en QGIS 4 y 246 (+3) en 3.34.
  **No igualado a propósito** (rarezas de JavaScript que pintarían mal): `Number(null)` vale 0
  en `>`/`<` y `String(undefined)` es «undefined» en `contains`; un texto vacío en un tramo
  cuenta como 0. **No comprobado**: rampa continua con iconos (el color calculado va a la
  primera capa del símbolo), y la web en pantalla, que va en el repaso.

- 10/10 · `icon`. Ya estaban `colored`/`fixedColor` y el color por modo (el de la vista si es
  categorizada o graduada; si no, el de la capa). Faltaba: (1) **sin `defaultIcon` la web no
  pinta la vista** y QGIS pintaba círculos: ahora no pinta nada y lo anota en el registro
  (`QgsNullSymbolRenderer`); (2) **la web tiene dos caminos y no dimensionan igual**: por
  teselas (`mvtLayerGenerator.js`, solo vistas únicas y categorizadas, `canUseMvtView` de
  `maps.jsx`) el icono va en metros entre `max(8, sizeMin/2)` y `size` px, halo blanco 235; en
  GeoJSON (`createViewIconLayer`: capas que no van por teselas y toda vista graduada o por
  reglas) va a `size` px fijos acotados entre `sizeMin` y `sizeMax`, halo 230. El complemento
  usaba siempre el primero. Ahora pide `include_tile_config` con las capas
  (`client.tile_config`) y decide como `getLayerLoadMode` de la web (`styles.load_mode`:
  `mvt`, `geojson`, `auto` por recuento, `manual` por `lod` del esquema; sin configuración,
  GeoJSON como la web). Pruebas en `test_provider_qgis.py`: `test_el_modo_de_carga_como_la_web`,
  `test_el_tamaño_del_icono_sigue_el_camino_de_la_web` (5 casos),
  `test_vista_de_iconos_sin_icono_no_pinta_nada` y
  `test_el_panel_sabe_si_la_web_lleva_la_capa_por_teselas` (5 casos); fallaban todas. Comprobado
  en la QGIS de pruebas contra la API local (`tile_config` `mvt`): vista de prueba 125
  «Prueba QGIS · Iconos graduados» con iconos a 30 px fijos de cerca y de lejos, y 126 «Prueba
  QGIS · Iconos sin icono» (el estilo de la vista real 52 «listado incidencias», sin su filtro,
  que en local deja 0 elementos) sin nada pintado sobre 49.557 árboles
  (`scratchpad/vistas/iconos-graduados-{cerca,lejos}-qgis.png`, `iconos-sin-icono-qgis.png`).
  Suite 261 en QGIS 4 y 258 (+3) en 3.34. **No comprobado**: la web en pantalla (va en el
  repaso; lo de los dos caminos sale de leer su código); el camino GeoJSON colorea las
  graduadas con `getViewFeatureStyle`, no con la función rápida, y si a un tramo le falta el
  color la web pinta el icono blanco; QGIS lo pinta del color por omisión.

## Hallazgos para decidir

_(lo que no es del plugin o pide una decisión)_
- **Costuras entre teselas en las agregadas**: QGIS recorta cada celda al borde de su
  tesela y se ven líneas finas donde se juntan; la web las pinta sin recorte. Se quitaría
  pidiendo las celdas como polígonos sueltos (proveedor propio que decodifique las teselas)
  en vez de capa de teselas vectoriales. Más trabajo; decidir si compensa.
- **El websocket no comprueba permisos al suscribirse**: `subscribe_map` (`consumers_layer.py`)
  mete en el grupo de cualquier mapa a cualquier usuario autenticado, sin mirar si puede verlo.
  Recibe los avisos de cambios (capa, elemento y usuario que cambió), no los datos. No es del
  complemento ni de las vistas; decidir si va en su propio PR.
