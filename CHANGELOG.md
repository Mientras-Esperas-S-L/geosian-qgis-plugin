# Registro de cambios

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).

## [Sin publicar]

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
