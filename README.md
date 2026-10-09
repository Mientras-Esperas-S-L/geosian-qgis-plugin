# Complemento de Geosian para QGIS

Abre en QGIS los mapas y capas de Geosian (GreenCityControl) tal y como los ves en la
web: con tus permisos, sus fichas, sus partes, sus fotos, sus vistas y sus fondos. Las
capas no son una copia: son los datos del servidor, y lo que cambia en GCC llega solo.

> **Esta versión solo lee.** Puedes consultar, filtrar, imprimir y analizar, pero no
> editar. La edición llegará en la siguiente fase.

Funciona con **QGIS 3.34 o posterior**, también con QGIS 4.

## Instalar

1. Descarga el fichero `geosian-<versión>.zip`.
2. En QGIS: *Complementos › Administrar e instalar complementos › Instalar a partir de ZIP*,
   elige el fichero y pulsa *Instalar complemento*.
3. En la pestaña *Instalados*, comprueba que **Geosian** está marcado.

Aparece el menú *Complementos › Geosian*.

## Conectar

1. *Complementos › Geosian › Nueva conexión...*
2. Pon un nombre (por ejemplo, «Producción»), la dirección del servidor
   (`https://api.greencitycontrol.com`), tu correo y tu contraseña.
3. Si tu cuenta tiene doble factor, QGIS te pide el código de la aplicación, como la web.

La credencial se guarda cifrada en el gestor de autenticación de QGIS, no en el proyecto:
puedes mandar un `.qgz` a un compañero sin mandarle tu sesión.

> Al entrar desde QGIS se cierra la sesión que tengas abierta en el navegador. La
> plataforma permite una sola sesión por usuario.

## Abrir un mapa

Abre el panel *Complementos › Geosian › Mapas y capas de Geosian* y despliega la conexión:
salen tus mapas y, dentro, sus capas y sus vistas.

- **Clic derecho en un mapa › Añadir el mapa entero**: las capas en el orden y las carpetas
  del panel de GCC, apagadas las que tienes apagadas allí y con la vista activa de cada una.
- **Doble clic en una capa** (o clic derecho › *Añadir al proyecto*): solo esa capa.
- Una **vista** se abre con su filtro y su estilo, como en la web.

Cada capa se pinta con el estilo de la web: los mismos colores por atributo, los mismos
tamaños y las etiquetas que la web enciende sola. Para cambiar la etiqueta, clic derecho en
la capa del panel de capas de QGIS › *Etiqueta (como en la web)*.

### Fondos

Si el proyecto no tiene fondo, se añaden los del selector de la web: el **mapa base de
Geosian** encendido y, apagados, la **ortofoto del IGN** con las calles encima, el **mapa
base oscuro** y los fondos propios del mapa. Para cambiar de fondo, enciende el que quieras
en el panel de capas.

### Capas grandes

Las capas de más de 50.000 elementos se pintan a partir de una escala y solo se descarga la
zona que ves. Su **tabla de atributos** muestra los primeros 5.000, y QGIS te lo avisa:
para ver otros, filtra la tabla por «Mostrar objetos visibles en el mapa» y muévete.

## La ficha de un elemento

Con la herramienta de identificar o desde la tabla, la ficha sale con las mismas pestañas
que en la web, sus listas de valores y los campos que dependen de otros.

- **Fotos y archivos**: miniaturas de las fotos (doble clic para verla en grande) y la lista
  de archivos (doble clic para abrirlo). Se piden a la API con tu sesión; nadie las ve solo
  por saber la dirección.
- **Información adicional**: los partes del elemento, por tipo, cada uno con su ficha, sus
  fotos y sus archivos. Solo aparecen los tipos que corresponden a ese elemento, como en la
  web (por ejemplo, los partes de palmeras solo en las palmeras). Los partes de cada tipo
  están también como tablas sin geometría en el grupo plegado «Información adicional», al
  final del mapa.

## Filtrar

- **Filtro de QGIS** (clic derecho en la capa › *Filtrar...*): lo que se pueda se resuelve en
  el servidor y el resto en QGIS. Se guarda con el proyecto.
- **Por partes y por fechas** (clic derecho en la capa › *Filtrar por partes y fechas…*),
  como el panel de filtros de la web: elementos con algún parte que cumpla cada condición
  (por ejemplo, «Parte de trabajo · poda = Poda general»), y partes entre dos fechas o solo el
  más reciente. También se guarda con el proyecto.

## Al día con GCC

Lo que cambia en la web (un elemento, un parte, los campos de una capa) se recarga solo en
QGIS, sin volver a abrir nada.

Si la sesión caduca o la red se cae, las capas no se pierden: siguen mostrando lo último que
llegó y QGIS te avisa en su barra.

- **Sesión caducada**: pulsa *Volver a entrar* en el aviso (o clic derecho en la conexión del
  panel). Las capas se recuperan solas.
- **Sin red**: QGIS lo vuelve a intentar cada 30 segundos.
- **Sin permiso**: la capa no se abre y te dice cuál es; pídeselo a quien administre el mapa.

Un proyecto guardado se abre igual otro día: si la sesión ha caducado, las capas que ya se
abrieron en este equipo salen vacías, con sus campos y su estilo, hasta que vuelvas a entrar.

## Qué no hace todavía

- **Editar**: ni elementos ni partes (siguiente fase).
- **Hexágonos, contornos y H3** de las vistas: se pintan con el color de la vista, sin
  agregar.
- El **satélite de Google** del selector de la web: sus condiciones no permiten usarlo fuera
  de su API.
- Un **tipo de parte nuevo** creado en GCC no aparece hasta que vuelves a añadir la capa (los
  campos nuevos, sí).
- **Trabajar sin conexión**: el dato vive en Geosian, a propósito.

## Para desarrollo

```bash
make venv        # entorno con el PyQGIS del sistema, pytest y ruff
make install     # enlaza el complemento en el perfil de QGIS
make test        # la batería entera; levanta un Geosian de mentira (tests/fake_server.py)
make lint
make package     # build/geosian-<versión>.zip, el que se instala
```

La integración continua (`.github/workflows/pruebas.yml`) pasa ruff y las pruebas en QGIS
3.34 y 4.2 en cada rama.

Reglas del diseño para la fase de escritura:

- **Desde QGIS no se borra nada.** Suprimir un elemento lo pasa a `no_disponible`
  (`soft-delete`), así los partes y fotos siguen ahí y el descuido se deshace en la web.
- **Bloqueo optimista**: se manda el `updated_at` que se leyó; un 409 es que alguien lo tocó
  antes, y hay que preguntar.
- **El identificador estable es `object_id`**: la clave primaria solo es única dentro de su
  tipo de geometría.
- **Nada de claves reservadas** en el JSON de `attributes`.

## Licencia

GPL-2.0-or-later, la que exige el repositorio de complementos de QGIS porque el complemento
enlaza con su API. Ver [LICENSE](LICENSE).
