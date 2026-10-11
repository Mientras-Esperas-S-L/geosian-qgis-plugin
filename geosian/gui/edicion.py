"""Engancha la edición de las capas de Geosian a QGIS.

El proveedor no ve la capa, y el lote necesita lo pendiente de la capa entero
antes de la primera escritura (``provider/edicion.py``). Aquí se conectan las
señales de cada capa de Geosian del proyecto: al empezar a editar, al confirmar
y al descartar.
"""

from qgis.core import QgsProject

_vigilando = {"activo": False}


def enganchar(capa):
    """Conecta las señales de edición de ``capa`` con su proveedor. Es idempotente."""
    if capa is None or capa.providerType() != "geosian" or not capa.isValid():
        return False
    if capa.property("geosian_edicion"):
        return True
    proveedor = capa.dataProvider()
    if not hasattr(proveedor, "preparar_lote"):
        return False

    capa.editingStarted.connect(proveedor.empezar_edicion)
    capa.beforeCommitChanges.connect(lambda *_: proveedor.preparar_lote(capa.editBuffer()))
    capa.afterCommitChanges.connect(proveedor.olvidar_lote)
    capa.afterRollBack.connect(proveedor.olvidar_lote)
    capa.editingStopped.connect(proveedor.terminar_edicion)
    capa.setProperty("geosian_edicion", True)
    return True


def _al_anadir(capas):
    for capa in capas:
        enganchar(capa)


def vigilar_proyecto():
    """Engancha las capas que ya hay y las que se añadan."""
    if _vigilando["activo"]:
        return
    for capa in QgsProject.instance().mapLayers().values():
        enganchar(capa)
    QgsProject.instance().layersAdded.connect(_al_anadir)
    _vigilando["activo"] = True


def dejar_de_vigilar():
    if _vigilando["activo"]:
        try:
            QgsProject.instance().layersAdded.disconnect(_al_anadir)
        except TypeError:
            pass
        _vigilando["activo"] = False
