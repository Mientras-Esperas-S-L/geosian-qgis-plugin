"""Descarga y caché en disco de los iconos de las vistas.

Cada librería de ``react-icons`` pesa entre 1 y 7 MB, así que se baja una sola
vez por sesión y solo cuando una vista la usa. De ella se guarda en disco el
SVG de cada icono pedido, que pesa unos cientos de bytes; la librería no se
guarda. Si no hay red o el icono no existe, se devuelve ``None`` y la vista se
pinta con círculos, que es mejor que no pintarla.
"""

import os

from . import icons
from .errors import GeosianError
from .http import default_transport


class IconStore:
    def __init__(self, carpeta=None, transport=None):
        self._carpeta = carpeta
        self._transport = transport
        self._librerias = {}

    @property
    def carpeta(self):
        if self._carpeta is None:
            from qgis.core import QgsApplication

            self._carpeta = os.path.join(
                QgsApplication.qgisSettingsDirPath(),
                "geosian",
                "iconos",
                icons.REACT_ICONS_VERSION,
            )
        return self._carpeta

    def path(self, lib, nombre):
        """Ruta del SVG del icono, bajándolo si hace falta. ``None`` si no hay."""
        url = icons.library_url(lib)
        if url is None or not nombre:
            return None
        ruta = os.path.join(self.carpeta, f"{lib}-{nombre}.svg")
        if os.path.exists(ruta):
            return ruta

        modulo = self._libreria(lib, url)
        arbol = icons.extract_tree(modulo, nombre)
        if arbol is None:
            return None
        os.makedirs(self.carpeta, exist_ok=True)
        with open(ruta, "w", encoding="utf-8") as fichero:
            fichero.write(icons.tree_to_svg(arbol))
        return ruta

    def _libreria(self, lib, url):
        if lib not in self._librerias:
            texto = ""
            try:
                transporte = self._transport or default_transport()
                respuesta = transporte.request("GET", url, {}, timeout=60)
                if respuesta.status == 200:
                    texto = respuesta.body.decode("utf-8", errors="replace")
            except GeosianError:
                texto = ""
            self._librerias[lib] = texto
        return self._librerias[lib]


_tienda = None


def default_store():
    global _tienda
    if _tienda is None:
        _tienda = IconStore()
    return _tienda
