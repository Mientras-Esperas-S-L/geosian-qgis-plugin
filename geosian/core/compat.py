"""Lo que cambia entre QGIS 3.34 (la mínima de ``metadata.txt``) y las nuevas.

Cada función usa la API nueva si existe y, si no, la vía que funciona en 3.34.
"""

import json

from qgis.core import QgsGeometry, QgsJsonUtils, QgsWkbTypes  # noqa: F401

# Desde QGIS 3.36. En las pruebas se pone a None para recorrer la vía de 3.34.
_DESDE_GEOJSON = getattr(QgsJsonUtils, "geometryFromGeoJson", None)


def geometry_from_geojson(geojson):
    """Una geometría GeoJSON (``dict``) como ``QgsGeometry``, o ``None`` si no vale."""
    texto = json.dumps(geojson)
    if _DESDE_GEOJSON is not None:
        geometria = _DESDE_GEOJSON(texto)
    else:
        from osgeo import ogr

        ogr_geom = ogr.CreateGeometryFromJson(texto)
        if ogr_geom is None:
            return None
        geometria = QgsGeometry()
        geometria.fromWkb(bytes(ogr_geom.ExportToIsoWkb()))
    if geometria is None or geometria.isNull():
        return None
    return geometria
