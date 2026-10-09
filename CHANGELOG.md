# Registro de cambios

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).

## [Sin publicar]

### Añadido

- Simbología de GCC a partir del esquema de cada capa, con los tamaños de la
  web, y etiquetas por defecto.
- Vistas de capa: en el panel, con su filtro (traducido a `attr__` como hace la
  web) y su estilo.
- «Añadir el mapa entero»: orden, carpetas, capas apagadas y vistas activas de
  las preferencias del usuario, y un fondo si el proyecto no lo tiene.
- Capas de más de 50.000 elementos por zona, con escala mínima calculada.
- Los LAD de un mapa se piden en paralelo: 50 capas en 1,4 s en vez de 17 s.
- Recargar el complemento recarga también el proveedor.

### Corregido

Encontrado al probarlo por primera vez contra un Geosian real:

- El doble factor no funcionaba. El código iba a `/users/login/verify-2fa`, sin
  la barra final, y la redirección del servidor acababa en «Protocolo
  desconocido». Además viajaba en el campo `otp` y el servidor lo espera en
  `otp_code`.
- Las capas se abrían sin tipo de geometría y el mapa salía en blanco. El
  detalle `/layers/<id>/` no devuelve `tile_metadata`; ahora se toma del listado
  de capas del mapa, que sí lo trae.
- `make install` enlazaba siempre en el perfil de QGIS 3. Ahora pregunta la
  versión al PyQGIS instalado y usa `QGIS3/` o `QGIS4/`.

### Añadido

- Proveedor de datos `geosian://` registrado en QGIS, de solo lectura.
- Cliente de la API con dos transportes: la pila de red de QGIS (respeta proxy y
  certificados) y la biblioteca estándar (pruebas y uso fuera de QGIS).
- Autenticación con usuario y contraseña, incluido el doble factor. El token se
  guarda en el gestor de autenticación de QGIS y, si no hay contraseña maestra,
  solo en memoria.
- Conexiones guardadas por nombre. La URI de las capas referencia la conexión,
  así que un proyecto `.qgs` no lleva dentro ni la dirección ni la credencial.
- Traducción del esquema de atributos (LAD) a campos, tipos, alias, listas de
  valores, obligatoriedad, campos de solo lectura y formularios con pestañas.
- Visibilidad condicional: los once operadores de `visible_if` se traducen a
  expresiones de QGIS.
- Panel de mapas y capas, con carga a demanda y apertura con doble clic.
- Recuento y extensión desde los metadatos de la capa, sin descargar datos.
- Valores únicos servidos desde el esquema cuando el campo declara sus valores
  permitidos, para que la simbología graduada no se descargue la capa entera.
- Batería de 64 pruebas, 25 de ellas contra QGIS real con un servidor que imita
  la API.

### Notas de la versión

- Las capas se abren en modo consulta. La edición es la fase 2 y llega con el
  bloqueo optimista, para no pisar el trabajo de otros.
- Las capas grandes se descargan enteras la primera vez que se piden datos: la
  carga por recuadro visible depende de que la API acepte un filtro espacial.
