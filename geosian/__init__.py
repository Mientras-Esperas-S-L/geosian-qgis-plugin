"""Complemento de QGIS para Geosian."""


def classFactory(iface):  # noqa: N802 (nombre exigido por QGIS)
    from .plugin import GeosianPlugin

    return GeosianPlugin(iface)
