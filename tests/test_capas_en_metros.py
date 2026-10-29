"""Capas de GreenCityControl en metros (ETRS89 / UTM) en vez de en grados.

GreenCityControl guarda y sirve en EPSG:4326. Para medir en QGIS (un buffer de 10 m
alrededor de cada árbol) la capa tiene que estar en metros: el proveedor transforma al
leer y al guardar, y el servidor no se entera.
"""

import pytest

qgis_core = pytest.importorskip("qgis.core")

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
)

from geosian.core import connections, crs
from geosian.gui import edicion
from tests.test_edicion_atributos import (  # noqa: F401
    CONEXION,
    editar,
    lotes,
    servidor,
)
from tests.test_gui import IfaceFalso

URI = f"geosian://{CONEXION}/map/4/layer/11?geometry_type=points&crs=EPSG:25830"
GRADOS = QgsCoordinateReferenceSystem("EPSG:4326")
UTM30 = QgsCoordinateReferenceSystem("EPSG:25830")


def abrir(uri=URI):
    capa = QgsVectorLayer(uri, "Arbolado", "geosian")
    assert capa.isValid(), capa.dataProvider().error()
    assert edicion.enganchar(capa)
    return capa


def a_metros(lon, lat):
    return QgsCoordinateTransform(GRADOS, UTM30, QgsProject.instance()).transform(QgsPointXY(lon, lat))


def cerca(una, otra, tolerancia):
    return abs(una.x() - otra.x()) < tolerancia and abs(una.y() - otra.y()) < tolerancia


def test_la_capa_se_abre_en_metros(servidor):  # noqa: F811
    capa = abrir()

    assert capa.crs() == UTM30
    assert cerca(capa.getFeature(1001).geometry().asPoint(), a_metros(-3.70, 40.40), 1e-6)


def test_la_extension_de_los_metadatos_va_en_metros(servidor):  # noqa: F811
    extension = abrir().extent()

    assert cerca(QgsPointXY(extension.xMinimum(), extension.yMinimum()), a_metros(-3.72, 40.39), 50)
    assert extension.width() > 1000


def test_un_buffer_de_10_son_10_metros(servidor):  # noqa: F811
    buffer = abrir().getFeature(1001).geometry().buffer(10, 16)

    buffer.transform(QgsCoordinateTransform(UTM30, GRADOS, QgsProject.instance()))

    # 20 m de lado a lado, a 40° de latitud, son unas 2,4 diezmilésimas de grado.
    assert 0.0002 < buffer.boundingBox().width() < 0.00027
    assert cerca(buffer.centroid().asPoint(), QgsPointXY(-3.70, 40.40), 1e-7)


def test_cambiar_un_atributo_no_manda_la_geometria(servidor):  # noqa: F811
    capa = abrir()
    list(capa.getFeatures())

    editar(capa, 1001, codigo="X1")
    assert capa.commitChanges(), capa.commitErrors()

    [cambio] = lotes(servidor)[0]["cambiar"]
    assert "geometry" not in cambio


def test_mover_un_punto_en_metros_llega_en_grados(servidor):  # noqa: F811
    capa = abrir()
    list(capa.getFeatures())
    destino = a_metros(-3.5, 40.5)

    assert capa.startEditing()
    assert capa.changeGeometry(1001, QgsGeometry.fromPointXY(destino))
    assert capa.commitChanges(), capa.commitErrors()

    [cambio] = lotes(servidor)[0]["cambiar"]
    lon, lat = cambio["geometry"]["coordinates"]
    assert abs(lon + 3.5) < 1e-9 and abs(lat - 40.5) < 1e-9
    # Y lo guardado sigue en metros en la capa, no en los grados de la respuesta.
    assert cerca(capa.getFeature(1001).geometry().asPoint(), destino, 1e-3)


def test_un_alta_en_metros_llega_en_grados(servidor):  # noqa: F811
    from qgis.core import QgsFeature

    capa = abrir()
    nuevo = QgsFeature(capa.fields())
    nuevo.setGeometry(QgsGeometry.fromPointXY(a_metros(-3.69, 40.41)))
    nuevo["codigo"] = "A-009"
    assert capa.startEditing()
    assert capa.addFeature(nuevo)
    assert capa.commitChanges(), capa.commitErrors()

    [alta] = lotes(servidor)[0]["crear"]
    lon, lat = alta["geometry"]["coordinates"]
    assert abs(lon + 3.69) < 1e-9 and abs(lat - 40.41) < 1e-9


def test_una_capa_grande_pide_la_zona_en_grados(servidor, monkeypatch):  # noqa: F811
    from geosian.provider import provider as modulo

    monkeypatch.setattr(modulo, "LARGE_LAYER", 2)
    capa = abrir()
    proveedor = capa.dataProvider()
    pedidas = []
    original = proveedor._client.geodata_paginated

    def apuntar(*args, **kwargs):
        pedidas.append(kwargs.get("area"))
        return original(*args, **kwargs)

    monkeypatch.setattr(proveedor._client, "geodata_paginated", apuntar)
    esquina, otra = a_metros(-3.705, 40.395), a_metros(-3.695, 40.405)
    recuadro = QgsRectangle(esquina.x(), esquina.y(), otra.x(), otra.y())

    ids = [f.id() for f in capa.getFeatures(QgsFeatureRequest().setFilterRect(recuadro))]

    assert ids == [1001]
    [area] = [a for a in pedidas if a]
    oeste, sur, este, norte = area
    assert -3.71 < oeste < -3.70 < este < -3.69
    assert 40.39 < sur < 40.40 < norte < 40.41


def test_la_escala_minima_de_una_capa_grande_no_cambia_con_el_sistema(servidor, monkeypatch):  # noqa: F811
    from geosian.provider import provider as modulo

    monkeypatch.setattr(modulo, "LARGE_LAYER", 2)
    en_grados = abrir(URI.replace("&crs=EPSG:25830", "")).dataProvider().suggested_min_scale()
    en_metros = abrir().dataProvider().suggested_min_scale()

    assert en_grados > 0
    # Redondeada a 1, 2 o 5: como mucho, un paso arriba o abajo. En metros, antes
    # tomaba los metros por grados y salía mil veces más cerca.
    assert 0.4 <= en_metros / en_grados <= 2.5


@pytest.mark.parametrize(("lon", "lat", "esperado"), [
    (-3.70, 40.40, "EPSG:25830"),   # Madrid
    (-2.94, 35.29, "EPSG:25830"),   # Melilla
    (-8.54, 42.88, "EPSG:25829"),   # Santiago
    (2.17, 41.38, "EPSG:25831"),    # Barcelona
    (3.65, 39.57, "EPSG:25831"),    # Mallorca
    (-15.43, 28.12, "EPSG:25828"),  # Gran Canaria
    (12.49, 41.89, "EPSG:32633"),   # Roma: fuera de España, WGS 84 / UTM
    (-58.38, -34.60, "EPSG:32721"),  # Buenos Aires: hemisferio sur
])
def test_el_huso_sale_del_sitio(lon, lat, esperado):
    assert crs.en_metros(lon, lat) == esperado


def _panel_con_la_capa(fake, nombre, metros):
    from geosian.gui.browser_dock import ROL_DATOS, GeosianBrowserDock

    connections.save_connection(nombre, fake.url, "a@b.c")
    connections.set_session(nombre, "tok-de-prueba", "jwt")
    connections.set_en_metros(nombre, metros)
    panel = GeosianBrowserDock(IfaceFalso())
    raiz = panel.arbol.topLevelItem(0)
    panel._al_desplegar(raiz)
    mapa = raiz.child(0).child(0)
    panel._al_desplegar(mapa)
    return panel, mapa.child(0).data(0, ROL_DATOS)


@pytest.mark.parametrize(("metros", "esperado"), [(True, "EPSG:25830"), (False, "EPSG:4326")])
def test_la_conexion_decide_si_las_capas_van_en_metros(app, metros, esperado):
    from tests.fake_server import FakeGeosian

    with FakeGeosian() as fake:
        try:
            panel, datos = _panel_con_la_capa(fake, "EnMetros", metros)
            [capa] = panel.añadir_capa(datos)
            assert capa.crs().authid() == esperado
        finally:
            QgsProject.instance().removeAllMapLayers()
            connections.remove_connection("EnMetros")


def test_por_defecto_las_capas_van_en_grados(app):
    connections.save_connection("SinElegir", "https://ejemplo.com", "a@b.c")
    try:
        assert connections.en_metros("SinElegir") is False
    finally:
        connections.remove_connection("SinElegir")


def test_el_mapa_entero_en_metros_se_encuadra_donde_esta(app):
    from geosian.gui.browser_dock import _extension_de
    from tests.fake_server import FakeGeosian

    with FakeGeosian() as fake:
        try:
            panel, datos = _panel_con_la_capa(fake, "Encuadre", True)
            [capa] = panel.añadir_capa(datos)
            extension = _extension_de([capa])
            # En grados, que es lo que esperan el encuadre y la elección del fondo.
            assert -3.73 < extension.xMinimum() < extension.xMaximum() < -3.67
            assert 40.38 < extension.yMinimum() < extension.yMaximum() < 40.43
        finally:
            QgsProject.instance().removeAllMapLayers()
            connections.remove_connection("Encuadre")


def test_la_casilla_de_la_conexion_cambia_el_sistema(app):
    from qgis.PyQt.QtWidgets import QMenu

    from geosian.gui.browser_dock import accion_en_metros

    connections.save_connection("Casilla", "https://ejemplo.com", "a@b.c")
    try:
        menu = QMenu()
        accion = accion_en_metros(menu, "Casilla")
        assert accion.isCheckable() and not accion.isChecked()

        accion.trigger()
        assert connections.en_metros("Casilla") is True

        assert accion_en_metros(QMenu(), "Casilla").isChecked()
    finally:
        connections.remove_connection("Casilla")
