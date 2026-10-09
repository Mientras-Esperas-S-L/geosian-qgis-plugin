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
- [ ] Tiempo real sin JWT: avisar una vez y ofrecer volver a entrar, no solo el registro.
- [ ] `layer_schema_changed`: recargar campos y formulario de la capa en vez de pedir que se
      vuelva a añadir.
- [ ] Filtros de la web que QGIS no tiene: por información adicional (elementos con partes
      que cumplan algo) y globales de fecha, como parámetros de la URI y desde el panel.
- [ ] Fondos fijos del selector de la web (ortofoto PNOA y los demás que tenga la web),
      añadidos apagados como los propios del mapa.
- [ ] Tabla de capas grandes: `no_geometry` en `/geodata/paginated/` (backend, su PR) y que
      el plugin lo use para la tabla sin recuadro.

### Compatibilidad, rendimiento y robustez
- [ ] QGIS 3.34 LTR (la mínima de `metadata.txt`): pasar la suite en un contenedor de QGIS
      3.34 (`qgis/qgis` de esa versión, con podman) y corregir lo que falle. Si no se puede,
      subir la mínima y anotarlo.
- [ ] Mapas grandes: Nueva York (1 M de puntos) y el Gran Parque de Mijas en local: abrir,
      mover, tabla y ficha sin bloquear QGIS más de 2 s; medir memoria. Anotar cifras.
- [ ] Errores en devel: red cortada a mitad (detener el acceso a la API), servidor lento,
      token revocado; ninguno cuelga QGIS y los mensajes se entienden.

### Entrega
- [ ] `make package`: el zip instala en un perfil limpio de QGIS 4 y de 3.34, con icono,
      licencia, `metadata.txt` completo (versión, changelog, tracker, homepage) y sin ficheros
      de pruebas ni cachés.
- [ ] CI del repo del plugin: GitHub Actions con ruff y pytest dentro del contenedor de QGIS
      (4 y 3.34), en verde en la rama.
- [ ] README de usuario en castellano: instalar, conectar (con doble factor), abrir un mapa,
      vistas, partes, fotos, filtros, etiquetas, fondos, tiempo real y qué no hace aún.
- [ ] Repaso final contra la web en Melilla (local y devel): capas, vistas, ficha, partes,
      fotos, filtros, etiquetas, fondo y estructura, con capturas lado a lado en el scratchpad.

### Para decidir (DECIDE: no se hacen sin el usuario)
- [ ] DECIDE · Hexágonos, contornos y H3: teselas agregadas del servidor como capa de
      teselas vectoriales, o se quedan pintadas con el color de la vista.
- [ ] DECIDE · Vistas encima de todas las capas (como hoy la web) o en el sitio de su capa.
- [ ] DECIDE · Que CT118 o el nginx de CT101 sirvan el `style.json` del fondo para no
      copiarlo en el complemento.
- [ ] DECIDE · Ficha de solo lectura que, como la web, oculte los campos vacíos.
- [ ] DECIDE · Abrir el PR del plugin a `main` y empezar la fase de escritura.

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

## Hallazgos para decidir

_(lo que no es del plugin o pide una decisión)_
