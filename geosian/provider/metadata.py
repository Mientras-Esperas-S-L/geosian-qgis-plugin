"""Registro del proveedor en QGIS.

El registro es por proceso: las capas ``geosian://`` solo son válidas si el
complemento está cargado. Un proyecto guardado con estas capas y abierto sin el
complemento las mostrará como no válidas, así que el mensaje de error tiene que
decirlo con claridad.
"""

import sys

from qgis.core import QgsDataProvider, QgsProviderMetadata, QgsProviderRegistry

from .provider import PROVIDER_DESCRIPTION, PROVIDER_KEY

_registered = False


def _crear(uri, providerOptions, flags=QgsDataProvider.ReadFlags()):  # noqa: N803
    """Crea el proveedor con la clase que esté cargada *ahora*.

    QGIS no deja quitar un proveedor del registro. Si el registro guardara la
    clase directamente, recargar o actualizar el complemento seguiría creando
    capas con el código viejo hasta reiniciar QGIS. Buscándola en cada llamada,
    la recarga vale para todo.
    """
    modulo = sys.modules[__name__.rsplit(".", 1)[0] + ".provider"]
    return modulo.GeosianProvider.createProvider(uri, providerOptions, flags)


class GeosianProviderMetadata(QgsProviderMetadata):
    def __init__(self):
        super().__init__(PROVIDER_KEY, PROVIDER_DESCRIPTION, _crear)


def register_provider():
    """Registra el proveedor. Es idempotente."""
    global _registered
    if _registered:
        return True
    registro = QgsProviderRegistry.instance()
    if PROVIDER_KEY in registro.providerList():
        _registered = True
        return True
    _registered = bool(registro.registerProvider(GeosianProviderMetadata()))
    return _registered


def is_registered():
    return _registered
