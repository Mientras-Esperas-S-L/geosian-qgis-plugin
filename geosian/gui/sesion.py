"""Sesiones caducadas: avisar y recuperar las capas al volver a entrar.

Al reabrir un proyecto con la sesión caducada, sus capas de Geosian quedan «no
disponibles» (``provider.py`` lo anota en ``connections.mark_expired``). QGIS
conserva su estilo, su formulario y su sitio en el árbol, así que basta con
volver a crear el proveedor cuando haya sesión.
"""

from qgis.core import Qgis, QgsDataProvider, QgsProject
from qgis.PyQt.QtWidgets import QPushButton

from ..core import connections
from ..provider.uri import parse_uri


def expired():
    return connections.expired()


def clear_expired(nombre=None):
    connections.clear_expired(nombre)


def repair_layers(nombre):
    """Vuelve a abrir las capas no disponibles de una conexión. Devuelve cuántas."""
    reparadas = 0
    pendientes = 0
    for capa in QgsProject.instance().mapLayers().values():
        if capa.providerType() != "geosian" or capa.isValid():
            continue
        try:
            if parse_uri(capa.source()).connection != nombre:
                continue
        except ValueError:
            continue
        capa.setDataSource(capa.source(), capa.name(), "geosian", QgsDataProvider.ProviderOptions())
        if capa.isValid():
            reparadas += 1
        else:
            pendientes += 1
    if not pendientes:
        connections.clear_expired(nombre)
    return reparadas


def offer_reconnect(iface, pedir):
    """Un aviso con «Volver a entrar» por cada conexión con la sesión caducada.

    Args:
        pedir: lo que abre el diálogo de la conexión; recibe su nombre.
    """
    for nombre in sorted(connections.expired()):
        aviso = iface.messageBar().createMessage(
            "Geosian",
            f"La sesión de «{nombre}» ha caducado: sus capas están sin datos hasta "
            "volver a entrar.",
        )
        boton = QPushButton("Volver a entrar")
        boton.clicked.connect(lambda _=False, n=nombre: pedir(n))
        aviso.layout().addWidget(boton)
        iface.messageBar().pushWidget(aviso, Qgis.Warning)
