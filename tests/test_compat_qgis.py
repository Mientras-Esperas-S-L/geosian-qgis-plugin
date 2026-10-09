"""Lo que cambia entre QGIS 3.34 (la mínima) y las nuevas."""

import pytest

pytest.importorskip("qgis.core")

from geosian.core import compat


@pytest.mark.parametrize("forzar_antigua", [False, True])
def test_geometria_desde_geojson(app, monkeypatch, forzar_antigua):
    """``QgsJsonUtils.geometryFromGeoJson`` llegó en 3.36; en 3.34 se pasa por OGR."""
    if forzar_antigua:
        monkeypatch.setattr(compat, "_DESDE_GEOJSON", None)
    punto = compat.geometry_from_geojson({"type": "Point", "coordinates": [-3.7, 40.4]})
    assert punto.asWkt(1) == "Point (-3.7 40.4)"
    poligono = compat.geometry_from_geojson(
        {"type": "MultiPolygon", "coordinates": [[[[0, 0], [1, 0], [1, 1], [0, 0]]]]}
    )
    assert poligono.wkbType() == compat.QgsWkbTypes.MultiPolygon
    assert compat.geometry_from_geojson({"type": "Point"}) is None


@pytest.mark.parametrize(
    "error, texto",
    [
        ("TimeoutError", "no ha respondido en 30 s"),
        ("OperationCanceledError", "no ha respondido en 30 s"),
        ("HostNotFoundError", "no se encuentra el servidor"),
        ("ConnectionRefusedError", "no acepta conexiones"),
        ("ProxyConnectionClosedError", "se ha cortado"),
    ],
)
def test_los_fallos_de_red_se_explican_en_castellano(app, error, texto):
    """Qt da «Operation timed out» o «Host … not found»: al usuario, en castellano."""
    from qgis.PyQt.QtNetwork import QNetworkReply

    from geosian.core.http import network_reason

    codigo = getattr(QNetworkReply.NetworkError, error)
    motivo = network_reason(codigo, "Operation timed out", 30)
    assert texto in motivo.lower()
