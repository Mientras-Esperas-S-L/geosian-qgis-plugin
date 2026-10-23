"""Lo que se escribe en la barra de mensajes de QGIS.

La barra pinta HTML: un nombre de capa o un error del servidor con etiquetas saldría como
enlace pulsable. Todo lo que va a ella pasa por :func:`seguro`.
"""

import html


def seguro(texto):
    return html.escape(str(texto), quote=False)
