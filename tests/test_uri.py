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


def test_el_filtro_de_la_capa_viaja_en_la_uri():
    # QGIS guarda en el proyecto la URI del proveedor: sin el filtro dentro, se pierde.
    uri = LayerUri("Local", 3, 64, geometry_type="points", subset="\"tipo\" = 'papelera' AND x < 5")
    texto = str(uri)
    assert "subset=" in texto and "&x" not in texto.split("subset=")[1]
    assert parse_uri(texto).subset == "\"tipo\" = 'papelera' AND x < 5"
    assert parse_uri("geosian://Local/map/3/layer/64").subset == ""


def test_filtros_de_partes_y_fechas_van_en_la_uri_y_vuelven():
    uri = parse_uri(
        "geosian://Conn/map/3/layer/12?geometry_type=points"
        "&parte=parte_trabajo__poda%3DApeo&parte=parte_trabajo__poda%3DPoda%20general"
        "&parte=parte_trabajo__altura__gte%3D5"
        "&date_from=2026-01-01&date_to=2026-03-31&most_recent=1"
    )
    assert uri.partes == [
        ("parte_trabajo__poda", "Apeo"),
        ("parte_trabajo__poda", "Poda general"),
        ("parte_trabajo__altura__gte", "5"),
    ]
    assert (uri.date_from, uri.date_to, uri.most_recent) == ("2026-01-01", "2026-03-31", True)
    assert parse_uri(str(uri)) == uri


def test_los_filtros_de_partes_y_fechas_se_mandan_como_en_la_web():
    uri = parse_uri(
        "geosian://Conn/map/3/layer/12?parte=parte_trabajo__poda%3DApeo"
        "&parte=parte_trabajo__poda%3DTala&date_from=2026-01-01&most_recent=1"
    )
    params = uri.server_filters(zona_horaria="Europe/Madrid")
    assert params == {
        "attr__parte_trabajo__poda": ["Apeo", "Tala"],
        "date_from": "2026-01-01",
        "timezone": "Europe/Madrid",
        "most_recent": "true",
    }


def test_sin_filtros_de_partes_no_se_manda_nada():
    assert parse_uri("geosian://Conn/map/3/layer/12").server_filters("Europe/Madrid") == {}


def test_un_filtro_de_parte_mal_escrito_no_vale():
    import pytest

    for malo in ("sin_igual", "solo_info%3Dx", "%3Dvalor"):
        with pytest.raises(ValueError):
            parse_uri(f"geosian://Conn/map/3/layer/12?parte={malo}")
