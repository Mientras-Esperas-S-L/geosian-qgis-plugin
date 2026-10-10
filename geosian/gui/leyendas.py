"""Leyendas que QGIS no da solo: la de las vistas agregadas.

Una capa de teselas vectoriales no trae leyenda en el panel de capas. Para las vistas
de hexágonos se pone la de la web: el degradado de la rampa con «Baja densidad» y
«Alta densidad». La rampa se guarda en la capa, para ponerla otra vez al reabrir el
proyecto.
"""

import json

from qgis.core import (
    QgsColorRampLegendNode,
    QgsColorRampLegendNodeSettings,
    QgsGradientColorRamp,
    QgsGradientStop,
    QgsMapLayerLegend,
    QgsProject,
)
from qgis.PyQt import sip
from qgis.PyQt.QtGui import QColor

PROPIEDAD = "geosian/leyenda_densidad"
EXTREMOS = ("Baja densidad", "Alta densidad")

# QGIS se queda con la leyenda, pero el objeto de Python tiene que seguir vivo.
_vivas = {}
_vigilando = {"activo": False}


class _LeyendaDensidad(QgsMapLayerLegend):
    def __init__(self, rampa):
        super().__init__()
        self._rampa = [tuple(c) for c in rampa]

    def createLayerTreeModelLegendNodes(self, nodo):
        colores = [QColor(*c[:3]) for c in self._rampa]
        n = len(colores)
        paradas = [QgsGradientStop(i / (n - 1), colores[i]) for i in range(1, n - 1)]
        rampa = QgsGradientColorRamp(colores[0], colores[-1], False, paradas)
        ajustes = QgsColorRampLegendNodeSettings()
        ajustes.setMinimumLabel(EXTREMOS[0])
        ajustes.setMaximumLabel(EXTREMOS[1])
        leyenda = QgsColorRampLegendNode(nodo, rampa, ajustes, 0, 1)
        # El nodo es de QGIS: sin esto, Python lo libera al volver y QGIS se cae.
        sip.transferto(leyenda, None)
        return [leyenda]


def poner_leyenda_de_densidad(capa, rampa):
    """Pone a ``capa`` el degradado de ``rampa`` (colores ``(r, g, b[, a])``)."""
    capa.setCustomProperty(PROPIEDAD, json.dumps([list(c) for c in rampa]))
    leyenda = _LeyendaDensidad(rampa)
    clave = capa.id()
    _vivas[clave] = leyenda
    capa.willBeDeleted.connect(lambda: _vivas.pop(clave, None))
    capa.setLegend(leyenda)


def _al_anadir_capas(capas):
    for capa in capas:
        guardada = capa.customProperty(PROPIEDAD)
        if guardada:
            try:
                poner_leyenda_de_densidad(capa, json.loads(guardada))
            except (TypeError, ValueError):
                continue


def vigilar_proyecto():
    """Al abrir un proyecto, las capas agregadas recuperan su leyenda."""
    if not _vigilando["activo"]:
        QgsProject.instance().layersAdded.connect(_al_anadir_capas)
        _vigilando["activo"] = True


def dejar_de_vigilar():
    if _vigilando["activo"]:
        try:
            QgsProject.instance().layersAdded.disconnect(_al_anadir_capas)
        except TypeError:
            pass
        _vigilando["activo"] = False
