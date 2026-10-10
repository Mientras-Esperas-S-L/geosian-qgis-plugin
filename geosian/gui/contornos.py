"""Vistas de contornos: isolíneas por umbral, calculadas con las celdas del servidor.

La web las pinta con el ``ContourLayer`` de deck.gl. Aquí, una capa de líneas en
memoria (EPSG:3857), un elemento por umbral con su color y su grosor. Los puntos son
los centroides de las celdas agregadas del servidor (``agg=hex&geom=centroid&cells=96``)
a un zoom en que cada celda mide la mitad de ``cellSize``; así vale igual para capas
pequeñas y grandes, respeta los filtros de la vista y se puede recalcular con el tiempo
real.
"""

import json

from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsLineSymbol,
    QgsPointXY,
    QgsRendererCategory,
    QgsUnitTypes,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor

from ..core import aggregated, connections, contours, mvt


def crear(nombre, info, estilo):
    """La capa de contornos de una vista, ya calculada. ``None`` si no se puede."""
    capa = QgsVectorLayer("MultiLineString?crs=EPSG:3857", nombre, "memory")
    if not capa.isValid():
        return None
    capa.dataProvider().addAttributes([QgsField("umbral", QVariant.Double)])
    capa.updateFields()
    info = dict(info, tipo="contour", estilo=estilo)
    capa.setCustomProperty(aggregated.PROPIEDAD, json.dumps(info))
    capa.setRenderer(_renderizador(estilo))
    capa.setOpacity(estilo["opacity"])
    recalcular(capa)
    return capa


def recalcular(capa):
    """Vuelve a pedir las celdas y a trazar las isolíneas (también tras un cambio)."""
    info = json.loads(capa.customProperty(aggregated.PROPIEDAD))
    estilo = info["estilo"]
    cliente = connections.client_for(info["conexion"])
    if cliente is None:
        return
    z, teselas = aggregated.contour_tiles(info["bbox"], estilo["cell_size"])
    extra = {"geom": "centroid", "cells": aggregated.CELDAS_DE_CALOR}
    if estilo.get("weight"):
        extra["weight"] = estilo["weight"]
    plantilla = aggregated.tile_url(info["base_url"], info["layer_id"], info["params"], extra)
    urls = [plantilla.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))
            for x, y in teselas]
    celdas = []
    for cuerpo in cliente.tiles(urls):
        if cuerpo:
            celdas.extend(mvt.decode(cuerpo).get(aggregated.CAPA_MVT, []))
    puntos = aggregated.cell_points(celdas, por_peso=bool(estilo.get("weight")))
    rejilla = contours.grid(puntos, estilo["cell_size"], estilo["aggregation"])

    proveedor = capa.dataProvider()
    proveedor.truncate()
    nuevos = []
    for umbral, _, _ in estilo["contours"]:
        segmentos = contours.isolines(rejilla, umbral)
        if not segmentos:
            continue
        elemento = QgsFeature(capa.fields())
        elemento.setGeometry(QgsGeometry.fromMultiPolylineXY(
            [[QgsPointXY(*a), QgsPointXY(*b)] for a, b in segmentos]
        ))
        elemento["umbral"] = float(umbral)
        nuevos.append(elemento)
    proveedor.addFeatures(nuevos)
    capa.updateExtents()
    capa.triggerRepaint()


def _renderizador(estilo):
    categorias = []
    for umbral, color, ancho in estilo["contours"]:
        simbolo = QgsLineSymbol.createSimple({})
        simbolo.setColor(QColor(*color))
        simbolo.setWidth(float(ancho))
        simbolo.setWidthUnit(QgsUnitTypes.RenderPixels)
        etiqueta = f"≥ {umbral:g}"
        categorias.append(QgsRendererCategory(float(umbral), simbolo, etiqueta))
    return QgsCategorizedSymbolRenderer("umbral", categorias)
