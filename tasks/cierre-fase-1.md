# Cierre de la fase 1 (solo lectura)

La lectura contra el backend local ya está hecha (`tasks/integracion-lectura.md`: casillas,
hecho y hallazgos). Este plan cierra la fase: lo que queda para que el complemento se
integre del todo con GCC en solo lectura y se pueda entregar.

## Prompt del bucle

```
/loop Sigue el plan de ~/Projects/geosian/geosian-qgis-plugin/tasks/cierre-fase-1.md: coge la
primera casilla abierta que no espere una decisión mía, hazla y compruébala de verdad (QGIS de
pruebas por el mando, la web en una pestaña tuya y la API), con una prueba que falle sin el
arreglo. El plugin va en la rama fix/make-install-qgis4 (push sí, PR no). Si a la API o a la
web les falta algo o tienen un fallo, arréglalo en su repo, en su rama, con pruebas y con su
PR, sin fusionar. Nada de producción. Apunta en el plan lo hecho, lo comprobado y lo que no.
Las casillas marcadas «DECIDE» no las hagas: déjalas para el final y pregúntamelas juntas.
Cuando solo queden casillas «DECIDE», para y avísame para repasar antes de abrir el PR del
plugin y empezar la fase de escritura.
```

## Reglas de cada vuelta

- Una casilla por vuelta, de arriba abajo; si una se bloquea, se anota por qué y se sigue.
- Prueba primero: una que falle sin el arreglo (pytest del plugin, de backend o vitest).
- Comprobación real además de las pruebas: QGIS de pruebas (perfil `pruebas`, `MANDO_DIR` y
  `QT_QPA_PLATFORM=offscreen`), la web local o devel en una pestaña propia, y la API.
- Local: backend `qgis-local-api` (`:8010`, código de `wt-backend-mapa-vacio`), web en
  `localhost:3000`. Devel: `api.devel.greencitycontrol.com` con la cuenta de auditoría
  `auditoria.fotos@ejemplo.local`, que solo ve Melilla (mapa 3), token en el scratchpad.
  Para entrar como otra cuenta de devel hace falta su doble factor: no se intenta.
- Nunca: producción, fusionar, borrar datos (desde QGIS todo es lectura), escribir
  credenciales en el chat, `pkill` por patrón, la QGIS del usuario.
- Datos de prueba ficticios; nada de municipios, clientes ni ids reales en las pruebas.

## Casillas

### Contra devel, no solo local
- [x] Conexión «Devel» con la cuenta de auditoría (token por `set_session`, sin JWT): el
      panel lista solo Melilla, se abre entera, fotos por enlace (`embed_images=false`, ya en
      devel) y miniaturas, partes, filtros y etiquetas. Anotar tiempos de apertura.
- [x] Lo prohibido se ve como tal en QGIS: una capa o mapa sin permiso no cuelga ni pide
      volver a entrar; mensaje claro (403 ≠ sesión caducada).
- [x] Tiempo real contra devel (`wss://api.devel…/ws/layer-data/`): necesita JWT. Sacar uno
      para la cuenta de auditoría por el guion de `desplegar.sh devel --manage` (como se creó
      la cuenta) y comprobar que un cambio hecho en la web llega a QGIS.

### Hallazgos pendientes que se pueden cerrar sin decisión
- [x] Etiqueta «ID interno» junto al panel de fotos en QGIS 4 aunque se pida ocultarla.
- [x] Sesión caducada al abrir un proyecto: que no salga el diálogo de QGIS «capas no
      disponibles» con las de Geosian (gestor de capas no disponibles propio que deja pasar
      las demás al de QGIS) y que «Volver a entrar» las recupere.
- [x] Tiempo real sin JWT: avisar una vez y ofrecer volver a entrar, no solo el registro.
- [x] `layer_schema_changed`: recargar campos y formulario de la capa en vez de pedir que se
      vuelva a añadir.
- [x] Filtros de la web que QGIS no tiene: por información adicional (elementos con partes
      que cumplan algo) y globales de fecha, como parámetros de la URI y desde el panel.
- [x] Fondos fijos del selector de la web (ortofoto PNOA y los demás que tenga la web),
      añadidos apagados como los propios del mapa.
- [x] Tabla de capas grandes: `no_geometry` en `/geodata/paginated/` (backend, su PR) y que
      el plugin lo use para la tabla sin recuadro.

### Compatibilidad, rendimiento y robustez
- [x] QGIS 3.34 LTR (la mínima de `metadata.txt`): pasar la suite en un contenedor de QGIS
      3.34 (`qgis/qgis` de esa versión, con podman) y corregir lo que falle. Si no se puede,
      subir la mínima y anotarlo.
- [x] Mapas grandes: Nueva York (1 M de puntos) y el Gran Parque de Mijas en local: abrir,
      mover, tabla y ficha sin bloquear QGIS más de 2 s; medir memoria. Anotar cifras.
- [x] Errores en devel: red cortada a mitad (detener el acceso a la API), servidor lento,
      token revocado; ninguno cuelga QGIS y los mensajes se entienden.

### Entrega
- [x] `make package`: el zip instala en un perfil limpio de QGIS 4 y de 3.34, con icono,
      licencia, `metadata.txt` completo (versión, changelog, tracker, homepage) y sin ficheros
      de pruebas ni cachés.
- [x] CI del repo del plugin: GitHub Actions con ruff y pytest dentro del contenedor de QGIS
      (4 y 3.34), en verde en la rama.
- [x] README de usuario en castellano: instalar, conectar (con doble factor), abrir un mapa,
      vistas, partes, fotos, filtros, etiquetas, fondos, tiempo real y qué no hace aún.
- [x] Repaso final contra la web en Melilla (local y devel): capas, vistas, ficha, partes,
      fotos, filtros, etiquetas, fondo y estructura, con capturas lado a lado en el scratchpad.

### Para decidir (DECIDE: no se hacen sin el usuario)
- [x] DECIDE · Hexágonos, contornos y H3: teselas agregadas del servidor como capa de
      teselas vectoriales, o se quedan pintadas con el color de la vista.
- [x] DECIDE · Vistas encima de todas las capas (como hoy la web) o en el sitio de su capa.
- [x] DECIDE · Que CT118 o el nginx de CT101 sirvan el `style.json` del fondo para no
      copiarlo en el complemento.
- [x] DECIDE · Ficha de solo lectura que, como la web, oculte los campos vacíos.
- [x] DECIDE · Abrir el PR del plugin a `main` y empezar la fase de escritura.

### Decidido el 10/10 (y lo que sale de ahí)
- Hexágonos, contornos y H3: **con las teselas agregadas del servidor**, como la web.
- Vistas: **encima de todas las capas**, como hoy la web (es lo que ya hace).
- `style.json` del fondo: **se queda la copia** en el complemento (no lo descartó).
- Ficha de solo lectura: **los campos vacíos se quedan a la vista**; servirá para editar.
- **PR del plugin abierto a `main`, sin fusionar**, y la fase de escritura empieza
  después de repasar juntos su diseño (borrado lógico, bloqueo optimista, permisos).
- Espera de la definición de una capa: **15 s** (antes 30), propuesto y no descartado.
- Satélite de Google en la web y origen del proxy de la ortofoto: aparte, fuera del
  complemento.
- [ ] Hexágonos, contornos y H3 con las teselas agregadas del servidor
      (`/geodata/tiles/…mvt?agg=hex…`), como capa de teselas vectoriales autenticada y
      coloreada por `count` con la escala de la web.

## Hecho

_(cada vuelta añade una línea: fecha, casilla, prueba, commit y qué se comprobó de verdad)_

- 09/10 · Devel con la cuenta de auditoría (conexión «DevelAuditoria» en la QGIS de
  pruebas). Comprobado en QGIS: el panel solo lista Melilla (mapa 3, 0,27 s); el mapa abre
  en 1,24 s con sus 3 capas (Arbolado 11.950, Tipo de superficie 1.469, Zonas verdes 213),
  fondo GEOSIAN y 11 tablas de partes. Fotos del árbol 61706 por enlace (4 fotos, sin base64,
  0,19 s; miniatura 13 KB, entera 434 KB). Partes del 28735: 1 parte en 0,19 s con su foto y
  autor. Filtro «porte_arboreo = palmera»: 3.840 en 0,96 s, mandado como `attr__`. Etiquetas:
  las cuatro de la web. Sin JWT no hay tiempo real (casilla aparte).
- 09/10 · Capa de un mapa sin permiso. Fallo: se abría **válida y vacía**. En devel la API
  da `[]` en `/layer-attributes/` (no 403) y el 403 del listado de capas del mapa se tomaba
  por «sin metadatos». Ahora la capa no es válida y dice «No tienes permiso para ver la capa
  343 en GCC» (0,45 s, sin marcar la sesión como caducada). Comprobado contra devel. La API
  no filtra nada: cero definiciones y cero elementos. Prueba
  `test_capa_de_un_mapa_sin_permiso_aunque_la_api_de_lista_vacia`.
- 09/10 · Tiempo real contra devel. JWT de la cuenta de auditoría sacado con
  `_generate_jwt_token` por `desplegar.sh devel --manage` (dura 28 días; en el scratchpad,
  600). En QGIS: canal a `wss://api.devel.greencitycontrol.com/ws/layer-data/`, `subscribed`
  al mapa 3. El aviso se mandó con `notify_layer_data_changed` (capa 8, Zonas verdes) desde
  el mismo guion, sin tocar datos: llegó `layer_data_changed` con `tile_version` 1 y la capa
  se recargó y repintó una vez. Sin arreglo: no hacía falta; lo cubre `test_realtime.py`.
  **No comprobado**: el cambio hecho de verdad en la web. La cuenta de auditoría es de solo
  lectura y las demás piden doble factor; el aviso que manda la web es esa misma función.
- 09/10 · Ficha en QGIS 4. Dos fallos. (1) **La ficha no tenía pestañas**: en QGIS 4.2 un
  contenedor sin padre nace como grupo, así que todas las secciones salían apiladas; ahora
  las de primer nivel se marcan como pestaña (`_pestaña`). (2) «ID interno» junto a las
  fotos: QGIS 4 pierde el «sin etiqueta» de los campos al añadir otra pestaña a la copia
  del formulario (la de partes va después); `_add_tab` lo restaura. Prueba
  `test_la_ficha_sale_en_pestanas_y_sin_la_etiqueta_del_id` (fallaba primero por las
  pestañas y, con eso arreglado, por la etiqueta). Comprobado en QGIS contra devel, árbol
  61706: pestañas Información Principal, General, Arbolado, Fotos y archivos e Información
  adicional (Palmeras se oculta por su condición), 4 fotos y sin la etiqueta. Captura
  `mando/cap/190-fotos-61706-pestanas.png`. Las pruebas anteriores no lo veían porque
  miraban la configuración, no la ficha montada.
- 09/10 · Sesión caducada al abrir un proyecto. El gestor propio de capas no disponibles
  **no se puede hacer**: QGIS no expone el suyo (`QgsHandleBadLayersHandler` es de la
  aplicación) y `setBadLayerHandler` lo borra, así que las capas de otras fuentes se
  quedarían sin diálogo. En su lugar, el complemento guarda en el perfil la definición de
  cada capa (esquema, metadatos y vista; ningún elemento), una carpeta por conexión que se
  borra al quitarla (`core/definitions.py`). Sin sesión, la capa abre vacía con sus campos
  y no pide nada a la red hasta recargarla; QGIS no la da por perdida ni pierde la
  configuración de sus campos al guardar. Sin definición guardada (proyecto de otro
  equipo) sigue «no disponible» como antes. De paso: (1) **QGIS se caía al leer un
  proyecto con una capa que no abre**, porque `fields()` devolvía `None`; ahora da campos
  vacíos. (2) El aviso de «Volver a entrar» salía dos veces (primera caducidad y proyecto
  leído) y no se quitaba al entrar. (3) Las pruebas se contagiaban la pausa de 30 s sin
  red. Pruebas: `test_con_la_sesion_caducada_abre_vacia_con_los_campos_que_ya_tenia`,
  `test_al_reabrir_el_proyecto_sin_sesion_qgis_no_da_las_capas_por_perdidas`,
  `test_un_proyecto_con_una_capa_que_no_abre_se_lee_sin_caerse` (se caía sin el arreglo),
  `test_el_aviso_de_volver_a_entrar_no_se_repite_mientras_se_ve`. Comprobado en QGIS
  contra devel con el proyecto de Melilla guardado y un token no válido: abre en 2,7 s,
  14 de 14 capas válidas y vacías, sin diálogo, un solo aviso, formulario con sus
  pestañas. Al volver a entrar (diálogo sustituido por uno que pone la sesión buena):
  11.950 + 1.469 + 213 elementos en 0,9 s, partes del 28735, el aviso desaparece y el mapa
  se pinta con su estilo (`mando/cap/199-recuperado-pintado.png`). **No comprobado**: el
  diálogo de entrada de verdad, porque pide doble factor.
- 09/10 · Tiempo real sin JWT. Antes solo quedaba en el registro. Ahora un aviso por
  conexión (no se repite mientras se ve) con «Volver a entrar»; al entrar se abre un canal
  nuevo y se suscribe a los mapas de las capas que ya estaban (`realtime_hub.reconnect`,
  desde `_pedir_reconexion`). Si el servidor rechaza el JWT (`auth_failed`) se suelta el
  canal y sale el mismo aviso. Con la sesión caducada no se avisa aparte: ya lo hace el de
  la sesión. Pruebas `test_sin_jwt_se_avisa_una_vez_y_al_entrar_se_activa_el_tiempo_real`,
  `test_jwt_rechazado_ofrece_volver_a_entrar_y_suelta_el_canal` y
  `test_con_la_sesion_caducada_no_se_avisa_aparte_del_tiempo_real` (las tres fallaban).
  Comprobado en QGIS contra devel: Melilla con sesión sin JWT da un aviso; el botón (con
  el diálogo sustituido por uno que pone el JWT) suscribe al mapa 3 por
  `wss://api.devel…` y quita el aviso. Un JWT falso: devel lo rechaza y el aviso sale en
  0,26 s. **No comprobado**: el diálogo de entrada de verdad (doble factor).
- 09/10 · `layer_schema_changed`. Antes: aviso de «vuelve a añadirla». Ahora las capas y
  tablas de partes de esa capa vuelven a pedir el esquema (`reload_definition`, que olvida
  el que el cliente guardaba 30 s), recargan sus campos y rehacen la ficha con sus pestañas
  de partes y de fotos (`gui/formulario.py`, que ahora comparten el panel y el tiempo
  real). El estilo no se toca: puede estar retocado a mano. Prueba
  `test_si_cambia_el_esquema_en_gcc_la_capa_coge_los_campos_nuevos` (fallaba). Comprobado
  contra el backend local con su ASGI en el 8011 (`qgis-local-ws`, parado al acabar): un
  campo `prueba_qgis` añadido al LAD de Zonas verdes desde el shell de Django sale en la
  capa (13 campos) y en la ficha sin quitarla; al quitarlo, desaparece (12). Contra devel
  **no**: habría que cambiar un esquema de un cliente. **Queda fuera**: un tipo de parte
  nuevo no crea su tabla; hay que volver a añadir la capa.
- 09/10 · Filtros por partes y fechas. La API ya los tenía en `/geodata/paginated/` (lo
  mismo que manda la web, `MapContext.jsx`): `attr__<tipo>__<campo>[__gte|gt|lte|lt]` para
  «elementos con algún parte que cumpla», y `date_from`, `date_to`, `timezone` y
  `most_recent` para las fechas de los partes. En la URI de la capa: `parte=<tipo>__<campo>
  =<valor>` (repetido = «o» en el mismo campo), `date_from`, `date_to`, `most_recent=1`;
  se guardan con el proyecto. Un tipo de parte que no está en el esquema deja la capa no
  válida con su motivo. Desde el panel: «Filtrar por partes y fechas…» en el menú de la
  capa (`gui/filtro_partes.py`), que reescribe la URI sin tocar estilo ni ficha. No se usa
  `filter_groups` (partes ligados a una sección): la web solo lo arma para eso. Pruebas en
  `test_uri.py` (4), `test_provider_qgis.py` (2) y
  `test_filtrar_por_partes_y_fechas_desde_el_menu_de_la_capa`, todas fallaban. Trampa
  encontrada: **PyQt6 tumba QGIS al conectar una señal a un método con «ñ» en el nombre**
  (`agregar`, no `añadir`). Comprobado contra devel (Melilla, Arbolado): 11.950 sin filtro;
  «Parte de trabajo · poda = Poda general», 949 en 0,5 s; con partes desde 01/01/2026, 3; la
  API directa con los mismos parámetros da 949 y 3; al quitar los filtros vuelve a 11.950
  con sus 84 campos y 5 pestañas. **No comprobado en la web**: la cuenta de auditoría no
  tiene contraseña y las demás piden doble factor.
- 09/10 · Fondos fijos del selector de la web (`MapProviderSelector.jsx`: mapa base,
  satélite, ortofoto IGN y mapa base oscuro). Se añaden apagados la **ortofoto del IGN**
  por el proxy de la aplicación (`<app>/ortofoto/{z}/{x}/{y}`, hasta z20, como la web) con
  las **calles de GEOSIAN encima**, en un grupo que se enciende entero, y el **mapa base
  oscuro**. Los estilos se sacaron del propio módulo de la web en una pestaña propia de
  `localhost:3000` (`createOrtofotoConCallesStyle` sin la capa de la foto, y
  `createOmtDarkStyle`) y viven en `resources/` como el claro. El **satélite de Google no**:
  ver hallazgos. Pruebas `test_estilo_oscuro_y_de_calles_con_las_teselas_de_la_aplicacion`,
  `test_fondos_fijos_del_selector_de_la_web` y la del mapa entero ampliada (fallaban).
  Comprobado en QGIS contra devel (Melilla): los cinco fondos válidos, solo GEOSIAN a la
  vista; el oscuro pinta en 0,2 s con calles, rótulos, mar y edificios
  (`mando/cap/212-oscuro.png`); la ortofoto con calles pinta donde el IGN responde
  (`mando/cap/212-ortofoto-calles.png`), ver hallazgos.
- 10/10 · Tabla de capas grandes sin geometría. Backend: `/geodata/paginated/` acepta
  `no_geometry=true` (los constructores ya lo sabían hacer; faltaba leerlo y no anotar
  `ST_AsGeoJSON`), rama `feat/paginated-no-geometry`, prueba
  `test_paginated_sin_geometria.py` (fallaba), **PR #293** abierto sin fusionar. Plugin: la tabla de
  una capa grande lo pide; lo que llega sin forma se apunta y, si después hace falta la
  forma («ir al elemento»), se vuelve a pedir ese elemento; lo que no la necesita no va a
  la red. Una API sin el cambio lo ignora y manda la forma: sigue funcionando. Prueba
  `test_la_tabla_de_una_capa_grande_pide_sin_geometria` (fallaba). Medido en local con la
  rama en una API temporal (`:8012`, parada al acabar): una página de 5.000 de la capa de
  polígonos 319 de Nueva York, 18,5 MB y 0,82 s → 3,2 MB y 0,22 s; de puntos (327),
  4,1 MB y 1,36 s → 3,6 MB y 0,97 s. En QGIS, la tabla de 50.000 árboles de Nueva York,
  13,1 s → 11,3 s, e «ir al elemento» trae la forma en 0,04 s. Contra devel **no**: hasta
  que se fusione el PR, devel lo ignora.
- 10/10 · QGIS 3.34 LTR. Suite en `docker.io/qgis/qgis:3.34` (3.34.15, Python 3.12, Qt 5) con
  podman: de 23 pasadas y caída a **202 de 202**. Tres cosas: (1) `QgsJsonUtils.
  geometryFromGeoJson` no existe hasta 3.36 y tumbaba QGIS al cargar cualquier capa; ahora
  `core/compat.py` pasa por OGR si falta (prueba `test_compat_qgis.py`, que recorre las dos
  vías). (2) La prueba del panel de fotos pedía el envoltorio al registro desde Python, y
  en 3.34 sip deja inservible el objeto que creó la fábrica; en una ficha de verdad
  (QGIS lo crea desde C++) funciona, así que la prueba monta la ficha. (3) Una prueba creaba
  `QgsField` con `QMetaType`, que 3.34 no acepta; con `QVariant`, como `lad.py`. La mínima
  se queda en 3.34. Comprobado en el contenedor 3.34 contra devel (cuenta de auditoría):
  Arbolado de Melilla válido con 11.950 en 0,56 s, ficha con sus pestañas y las 4 fotos del
  61706, filtro por partes 949, y los fondos GEOSIAN y oscuro se crean. **No comprobado**:
  la interfaz de QGIS 3.34 a la vista (panel, menús), solo en modo sin pantalla.
- 10/10 · Mapas grandes en local (`:8010`). **Nueva York** (arbolado, 1.078.380 puntos, por
  zonas desde 1:20.000): abrir el mapa 0,3-0,8 s; moverse, cuatro encuadres a 1:6.300 en
  0,4-0,9 s cada uno (en los hilos de pintado, sin congelar la ventana), +21 MB con 17.424 en
  caché; ficha 0,01 s. **Fallo**: la tabla de atributos cargaba 50.000 en el hilo de la
  ventana, 14,7 s congelado. Ahora una página (5.000): **1,27 s**, y el aviso de «la tabla
  muestra los primeros 5.000» sale en la barra (antes solo en el registro), una vez por
  capa y al volver al bucle de la ventana. QGIS recién abierto con Nueva York y la tabla:
  689 MB. **Gran Parque de Mijas** (45 capas, 19.396 elementos): abrir 1,5 s; pintar el parque
  entero 2,3 s en hilos de pintado; la tabla en frío de la capa mayor (7.337) 0,89 s; ficha
  0,18 s. Pruebas `test_la_tabla_de_una_capa_grande_no_congela_qgis` y
  `test_la_tabla_recortada_se_avisa_en_la_barra` (fallaban); suite 204 en QGIS 4 y en 3.34.
  Ojo al medir: la QGIS de pruebas se cayó tres veces por un fallo **de mis órdenes**, no
  del complemento (un `QgsVectorLayerCache` sin referencia en Python que se recogía con la
  tabla en uso).
- 10/10 · Errores contra devel, con un proxy CONNECT propio (`scratchpad/proxy_fallos.py`,
  modos normal, cortar y lento N s por bloque) puesto como proxy de Qt en la QGIS de pruebas
  y quitado al acabar. **Red cortada**: dos fallos. Una recarga (tiempo real, «Recargar»)
  vaciaba la capa antes de saber si podía traer lo nuevo: se quedaba en 0; ahora conserva
  lo que tenía y reintenta pasada la pausa (11.950 a la vista en 0,08 s; al volver la red,
  11.950 en 2,7 s). Y el aviso solo iba al registro: ahora sale en la barra «Sin conexión
  con GCC…», como mucho cada 5 min por conexión y desde cualquier hilo (encolado al de la
  ventana). Abrir una capa sin red: no válida al momento con el motivo. **Servidor lento**
  (2 s por bloque): abrir una capa 12,3 s; **sin respuesta**: 30,1 s y luego «GCC no ha
  respondido en 30 s» (antes «Operation timed out», en inglés; ahora en castellano los
  fallos de red habituales). **Token revocado**: la capa sigue con lo último, se marca
  caducada y sale «Volver a entrar» (el texto decía «sin datos», ya no es verdad). Pruebas
  `test_recargar_sin_red_conserva_lo_que_habia`, `test_sin_red_se_avisa_en_la_barra_una_vez`
  y `test_los_fallos_de_red_se_explican_en_castellano` (fallaban); suite 211 en QGIS 4 y 3.34.
- 10/10 · `make package`. Faltaba la **licencia dentro del zip** (el repositorio de
  complementos de QGIS la exige); la descripción prometía escritura y el registro de cambios
  era el del primer día. Ahora el zip lleva solo lo versionado de `geosian/` más `LICENSE`
  (`git ls-files`, sin cachés ni restos), con `BUILD=` para elegir dónde; metadatos al día y
  «Por ahora, solo lectura». Prueba `test_paquete.py` (construye el zip y mira contenido y
  metadatos; fallaba). Comprobado instalando el zip (107 KB, 45 ficheros) en un **perfil
  limpio de QGIS 4** y en otro de **QGIS 3.34** (contenedor, con Xvfb lanzado a mano:
  `xvfb-run` se queda colgado dentro de podman): en los dos, complemento activo, panel creado
  y menú «Geosian». En el contenedor no hay `make`/`git`/`zip`: la prueba del paquete se
  salta ahí (211 pasan y 3 saltadas; 214 en QGIS 4).
- 10/10 · CI del plugin (`.github/workflows/pruebas.yml`): ruff y pytest en `qgis/qgis:3.34` y
  `qgis/qgis:4.2` (4.2.3), en cualquier rama y en los PR. Ruff no tenía configuración en el
  repo y aplicaba las reglas por omisión de cada versión: ahora `pyproject.toml` y versión
  fija (0.16.10) en la CI. Se arreglaron los 43 avisos que había (26 automáticos, revisados
  uno a uno, y 5 a mano) y se ignoran `BLE001` y `S110`, que en un complemento son a
  propósito; `make lint` ya no se traga los errores. Antes de subirlo, la suite en los dos
  contenedores en local: 211 pasan y 3 saltadas (el paquete) en cada uno. **En verde en la
  rama**: ejecución 38006199614 (b96cfad), los tres trabajos.
- 10/10 · README de usuario reescrito: instalar desde el zip, conectar (doble factor,
  credencial cifrada fuera del proyecto, sesión única), abrir mapa, capa y vista, estilo y
  etiquetas, fondos, capas grandes (tabla de 5.000), ficha con fotos y partes, filtros de QGIS
  y por partes y fechas, tiempo real, sesión caducada, sin red y sin permiso, y lo que no hace
  aún; el desarrollo y las reglas de la fase de escritura, al final. Cotejado con el código:
  los nombres de menús y acciones son los que tiene el complemento. Quité lo que no he visto
  funcionar (que una foto nueva llegue sola). **No comprobado**: que alguien de fuera lo siga
  paso a paso.
- 10/10 · Repaso final contra la web local (pestaña propia de `localhost:3000`, sesión de
  `tester2`; en QGIS la conexión «Local» con la clave local de `tester2`, que ya existía, solo
  en memoria). Capturas lado a lado en `scratchpad/repaso/`: **mapa entero** (01: mismas capas,
  mismas vistas activas —arbolado por barrio, mobiliario por tipo—, mismos colores y fondo),
  **ficha** del árbol 470794-ac096465 (02) y sus **partes** (03: los mismos dos, mismos
  usuarios y fechas). **Fallo encontrado**: en QGIS 4, «Zona», «Barrio» y «Marcado como»
  (selección múltiple) salían como «Z, ,, , ,,». Dos causas: los datos guardan a veces un texto
  suelto donde el esquema dice `multiple` (la web acepta las dos formas) y QGIS ponía su
  editor de texto, que en QGIS 4 pinta así una lista. Ahora el valor suelto llega como lista de
  uno y esos campos usan el editor de listas: «Zona Victoria», «Virgen de la Victoria».
  Pruebas `test_una_seleccion_multiple_con_un_valor_suelto_llega_como_lista` y
  `test_la_seleccion_multiple_usa_el_editor_de_listas` (fallaban); suite 216 en QGIS 4 y 213
  (+3 saltadas) en 3.34. Lo demás del repaso ya estaba comprobado en sus casillas (filtros,
  etiquetas, fondos, fotos, tiempo real). **No comprobado contra la web de devel**: la cuenta
  de auditoría no tiene contraseña y las demás piden doble factor; contra la API de devel sí
  (casilla 1). Diferencias que quedan, ya en «para decidir»: la web oculta los campos vacíos
  («Marcado como» sale en QGIS y no en la web) y el pie de la lista de partes de la web dice
  «1-10 de 10» con 2 (PR #202 sin fusionar).
- 10/10 · Espera de la definición: 15 s para `layer-attributes`, el listado de capas y la
  vista (`DEFINITION_TIMEOUT`); los datos siguen con 30 s. Prueba
  `test_la_definicion_de_una_capa_espera_menos_que_los_datos` (fallaba). Comprobado contra
  devel con el proxy mudo: abrir una capa falla a los 14,6 s con «GCC no ha respondido en
  15 s» (antes 30,1 s); proxy quitado al acabar.

## Hallazgos para decidir

_(lo que no es del plugin o pide una decisión)_

- **Satélite de Google en el selector de la web** (`GOOGLE_SATELLITE`, teselas
  `mt*.google.com/vt/lyrs=s`). No lo he copiado al complemento: las condiciones de Google
  no permiten usar sus teselas fuera de su API, y meterlo en un complemento que se
  distribuye lo agrava. La web ya lo hace; decidir si se mantiene allí.
- **El WMTS del IGN falla a ratos y arrastra la ortofoto de la web y de QGIS.** El 09/10 a
  medianoche, `www.ign.es/wmts/pnoa-ma` daba 504 a los 10 s en teselas de Melilla a z17,
  mientras que su TMS (`tms-pnoa-ma.idee.es/1.0.0/pnoa-ma/{z}/{x}/{-y}.jpeg`) daba las mismas
  al momento. Nuestro proxy `/ortofoto` (nginx de CT101) pide al WMTS, y lo cacheado sale
  bien. Cambiar el origen del proxy al TMS, o tenerlo de reserva, es cosa del nginx de
  producción: no lo he tocado.
- **Suite del backend, dos cosas ajenas a #293** (vistas el 10/10): `tests/test_open_feature_info.py`
  se queda colgado en el entorno de pruebas local, también solo (Redis responde bien); y
  ocho pruebas de calendario de tareas y la de reglas IoT fallan igual con el código de
  `main`, corridas a las 00:48 (aún día 9 en UTC): parecen depender de la fecha.
- **Esperas que bloquean la ventana.** Abrir una capa pide su definición en el hilo de la
  ventana (QGIS lo exige: los campos se dan al crear la capa). Con el servidor lento son
  segundos (12 s medidos) y con el servidor mudo, el tiempo de espera entero: 30 s. Se
  puede bajar a 10-15 s para la definición (respuestas pequeñas) y dejar 30 s para los
  datos, que van en los hilos de pintado. No lo he cambiado: es un compromiso entre
  servidores lentos de verdad y QGIS congelado.
