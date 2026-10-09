"""Fotos y adjuntos de un elemento o de un parte, sin QGIS delante.

La API los da de dos formas, y aquí se igualan:

- El detalle de un elemento (``/geodata/<id>/``) manda las fotos incrustadas en
  base64 (``data``) y los ficheros solo con ``id`` y ``name``. Con
  ``embed_images=false`` manda en su lugar el enlace a cada foto y a su
  miniatura (``url``, ``thumbnail_url``), que es como lo pide el complemento.
- El listado de partes (``/additional-information/``) manda las fotos como
  enlace (``url``), sin el contenido.

Las fotos y los ficheros se piden siempre a la API con el token, nunca a
``/media/``: allí los enlaces van firmados y caducan.
"""

import base64
import binascii


class MediaItem:
    """Una foto o un fichero."""

    __slots__ = ("created_at", "data", "field_name", "id", "kind", "main", "name", "thumb_url", "url")

    def __init__(self, id, kind, name="", url=None, data=None, main=False,
                 created_at=None, field_name=None, thumb_url=None):
        self.id = id
        self.thumb_url = thumb_url
        self.kind = kind
        self.name = name
        self.url = url
        self.data = data
        self.main = main
        self.created_at = created_at
        self.field_name = field_name

    def __repr__(self):
        return f"<MediaItem {self.kind} {self.id}>"


def items_from(registro, image_url=None, file_url=None):
    """Fotos (la portada primero) y luego ficheros de un elemento o de un parte.

    Args:
        registro: el detalle del elemento o el parte, como venga de la API.
        image_url: plantilla con ``{id}`` para pedir una foto que no traiga
            enlace propio.
        file_url: lo mismo para los ficheros.
    """
    if not isinstance(registro, dict):
        return []

    fotos = []
    for foto in registro.get("pictures") or []:
        if not isinstance(foto, dict) or foto.get("id") is None:
            continue
        datos = None
        if foto.get("data"):
            datos = _decode_data_url(foto["data"])
            if datos is None:
                continue
        url = foto.get("url") or (image_url.format(id=foto["id"]) if image_url else None)
        if datos is None and not url:
            continue
        fotos.append(
            MediaItem(
                foto["id"],
                "image",
                name=foto.get("name") or "",
                url=url,
                data=datos,
                thumb_url=foto.get("thumbnail_url"),
                main=bool(foto.get("main_image")),
                created_at=foto.get("created_at"),
                field_name=foto.get("field_name"),
            )
        )
    # sorted es estable: tras la portada, el orden de la API.
    fotos.sort(key=lambda f: not f.main)

    ficheros = []
    for fichero in registro.get("files") or []:
        if not isinstance(fichero, dict) or fichero.get("id") is None:
            continue
        url = fichero.get("url") or (file_url.format(id=fichero["id"]) if file_url else None)
        if not url:
            continue
        ficheros.append(
            MediaItem(
                fichero["id"],
                "file",
                name=fichero.get("name") or f"fichero-{fichero['id']}",
                url=url,
                created_at=fichero.get("created_at"),
                field_name=fichero.get("field_name"),
            )
        )
    return fotos + ficheros


def _decode_data_url(texto):
    """Bytes de un ``data:…;base64,…``, o ``None`` si no se puede leer."""
    _, _, cuerpo = str(texto).partition("base64,")
    try:
        return base64.b64decode(cuerpo, validate=True)
    except (binascii.Error, ValueError):
        return None
