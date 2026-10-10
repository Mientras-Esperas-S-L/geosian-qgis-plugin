"""Complemento de QGIS para Geosian."""


def classFactory(iface):  # nombre exigido por QGIS
    from .plugin import GeosianPlugin

    return GeosianPlugin(iface)
