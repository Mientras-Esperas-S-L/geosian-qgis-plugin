"""Pruebas de la URI del proveedor. No necesitan QGIS."""

import pytest

from geosian.provider.uri import LayerUri, build_uri, parse_uri


def test_uri_minima():
    uri = parse_uri("geosian://Produccion/map/4/layer/11")
    assert uri.connection == "Produccion"
    assert uri.map_id == 4
    assert uri.layer_id == 11
    assert uri.geometry_type is None
    assert uri.crs == "EPSG:4326"


def test_uri_con_parametros():
    uri = parse_uri(
        "geosian://Produccion/map/4/layer/11?geometry_type=multi_polygons&view=7"
    )
    assert uri.geometry_type == "multi_polygons"
    assert uri.view_id == 7


def test_ida_y_vuelta():
    original = "geosian://Produccion/map/4/layer/11?geometry_type=points"
    assert str(parse_uri(original)) == original


def test_nombre_con_espacios():
    uri = parse_uri("geosian://Ayuntamiento%20de%20Ejemplo/map/1/layer/2")
    assert uri.connection == "Ayuntamiento de Ejemplo"
    # Y vuelve a salir escapado, para que la URI siga siendo válida.
    assert "Ayuntamiento%20de%20Ejemplo" in str(uri)


def test_build_uri():
    assert (
        build_uri("Prod", 4, 11, geometry_type="points")
        == "geosian://Prod/map/4/layer/11?geometry_type=points"
    )


@pytest.mark.parametrize(
    "mala",
    [
        "",
        "postgres://host/dbname",
        "geosian://",
        "geosian://Prod/map/4",
        "geosian://Prod/layer/11",
        "geosian://Prod/map/abc/layer/11",
    ],
)
def test_uris_invalidas(mala):
    with pytest.raises(ValueError):
        parse_uri(mala)


def test_igualdad():
    a = LayerUri("Prod", 1, 2, "points")
    b = parse_uri("geosian://Prod/map/1/layer/2?geometry_type=points")
    assert a == b
