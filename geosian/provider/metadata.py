"""Registro del proveedor en QGIS.

El registro es por proceso: las capas ``geosian://`` solo son válidas si el
complemento está cargado. Un proyecto guardado con estas capas y abierto sin el
complemento las mostrará como no válidas, así que el mensaje de error tiene que
decirlo con claridad.
"""

from qgis.core import QgsProviderMetadata, QgsProviderRegistry

from .provider import PROVIDER_DESCRIPTION, PROVIDER_KEY, GeosianProvider

_registered = False


class GeosianProviderMetadata(QgsProviderMetadata):
    def __init__(self):
        super().__init__(
            PROVIDER_KEY,
            PROVIDER_DESCRIPTION,
            GeosianProvider.createProvider,
        )


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
