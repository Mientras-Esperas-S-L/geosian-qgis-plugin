# Complemento de Geosian para QGIS

Hace que QGIS trabaje **contra la API de Geosian** en lugar de contra ficheros o
una conexión directa a la base de datos. Las capas que abres son datos vivos del
servidor, y todo lo que pasa por ellas respeta la lógica de negocio de la
plataforma: permisos por capa y grupo, esquemas dinámicos de atributos,
disparadores, historial y avisos en tiempo real.

> **Estado: en desarrollo, fase 1 (lectura).** Se pueden abrir capas y trabajar
> con ellas en modo consulta. La edición llega en la fase 2.

## Cómo funciona

El complemento registra en QGIS un proveedor de datos propio, `geosian://`, que
traduce lo que QGIS pide a llamadas de la API:

```
QGIS  ──>  proveedor "geosian"  ──HTTP──>  /api/v1/…   (permisos, LAD, triggers)
                    ▲
                    └──────────────────────  /ws/layer-data/  (fase 3)
```

No hay copia local que sincronizar ni fichero intermedio: el maestro del dato es
Geosian y QGIS es un cliente más, al mismo nivel que la aplicación web y la de
campo.

## Qué hace hoy

- Conexión al servidor con usuario y contraseña, incluido el doble factor.
- Panel con las conexiones, sus mapas y las capas de cada mapa.
- Apertura de capas con doble clic, una por tipo de geometría.
- Campos, tipos, alias y **formularios generados a partir del esquema de la
  capa**, con sus pestañas, sus listas de valores y su visibilidad condicional.
- Recuento y extensión sin descargar la capa, y valores de los desplegables
  servidos desde el esquema en vez de recorriendo los datos.

## Qué no hace todavía

- Editar. La capa se abre en modo consulta (fase 2).
- Trabajar sin conexión. Es una consecuencia buscada del diseño.
- Fotos, adjuntos y partes de trabajo (fase 4).
- Refresco en vivo por WebSocket (fase 3).

## Reglas que hereda del diseño

Van aquí para que no se pierdan cuando llegue la fase de escritura:

- **Desde QGIS no se borra nada.** Suprimir un elemento lo pasa a
  `no_disponible` con `soft-delete`, nunca ejecuta un borrado real. Así los
  partes y las fotos asociados siguen ahí y cualquier descuido se deshace desde
  la plataforma.
- **Escritura con bloqueo optimista.** Se manda el `updated_at` que se leyó; si
  el servidor responde 409, alguien lo tocó antes y hay que preguntar al
  usuario. El campo ya viaja en las capas y el cliente ya traduce el 409.
- **El identificador estable es `object_id`**, no la clave primaria, que solo es
  única dentro de su tabla de geometría.
- **Nada de escribir en el JSONB `attributes`** con claves reservadas.

## Instalación para desarrollo

```bash
make install     # enlaza el complemento en el perfil de QGIS
```

Después, en QGIS: *Complementos › Administrar e instalar complementos › Instalados*
y activa **Geosian**.

## Uso

1. *Complementos › Geosian › Nueva conexión...*
2. Rellena nombre, servidor (`https://…`), correo y contraseña.
3. Abre el panel *Mapas y capas de Geosian* y despliega la conexión.
4. Doble clic en una capa.

> Al entrar desde QGIS se cierra la sesión que tengas abierta en el navegador.
> La plataforma permite una sola sesión por usuario.

## Desarrollo

```bash
make test        # toda la batería, incluida la que levanta QGIS
make lint
make package     # genera el zip para instalar o publicar
```

Las pruebas no necesitan un Geosian de verdad: `tests/fake_server.py` levanta
uno que responde igual. Sí necesitan **PyQGIS** instalado.

Requisitos: QGIS 3.34 o superior. Probado con QGIS 4.2.

## Licencia

GPL-2.0-or-later. Es la licencia que exige el repositorio de complementos de
QGIS, porque el complemento enlaza con la API de QGIS. Ver [LICENSE](LICENSE).
