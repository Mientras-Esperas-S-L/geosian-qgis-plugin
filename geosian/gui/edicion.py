"""Engancha la edición de las capas de Geosian a QGIS.

El proveedor no ve la capa, y el lote necesita lo pendiente de la capa entero
antes de la primera escritura (``provider/edicion.py``). Aquí se conectan las
señales de cada capa de Geosian del proyecto: al empezar a editar, al confirmar
y al descartar.
"""

from qgis.core import QgsProject

_vigilando = {"activo": False}


def preguntar_retirada(capa, cuantos):
    """¿Seguir con una confirmación que retira ``cuantos`` elementos?

    Suprimir en QGIS no borra en Geosian: retira. Se dice con esas palabras antes
    de hacerlo. Las pruebas la sustituyen, porque el diálogo esperaría a alguien.
    """
    from qgis.PyQt.QtWidgets import QMessageBox

    elementos = "un elemento" if cuantos == 1 else f"{cuantos} elementos"
    respuesta = QMessageBox.question(
        None,
        "Retirar en Geosian",
        f"Vas a retirar {elementos} de «{capa.name()}».\n\n"
        "En Geosian no se borran: pasan a «no disponible», quedan en su historial y se "
        "pueden recuperar desde la web.\n\n¿Seguir?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return respuesta == QMessageBox.StandardButton.Yes


def _antes_de_confirmar(capa, proveedor):
    buffer = capa.editBuffer()
    bajas = [fid for fid in buffer.deletedFeatureIds() if fid >= 0]
    if bajas and not preguntar_retirada(capa, len(bajas)):
        proveedor.cancelar_lote(
            "No se ha guardado nada: has cancelado la retirada. Los cambios siguen pendientes."
        )
        return
    proveedor.preparar_lote(buffer)


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
    capa.beforeCommitChanges.connect(lambda *_: _antes_de_confirmar(capa, proveedor))
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
