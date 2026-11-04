"""Las condiciones combinadas (el filtro en árbol de GreenCityControl) en el plugin.

Un servidor que no entiende el parámetro `filtro` lo ignoraría y la capa saldría sin
filtrar, sin aviso: el plugin lo comprueba antes, y si no, la capa no abre y lo dice.
"""

import json

import pytest

pytest.importorskip("qgis.core")

from geosian.core import connections
from geosian.core.client import _ADMITE_FILTRO
from tests.fake_server import FakeGeosian

ARBOL = {"todas": True, "condiciones": [{"campo": "especie", "op": "es_uno_de", "valor": ["Tilia platyphyllos"]}]}


@pytest.fixture(autouse=True)
def _sin_recuerdo():
    _ADMITE_FILTRO.clear()
    yield
    _ADMITE_FILTRO.clear()


def _abrir(fake, nombre, admite):
    from qgis.core import QgsVectorLayer

    from geosian.provider.uri import LayerUri

    fake._server.admite_filtro = admite
    connections.save_connection(nombre, fake.url, "a@b.c")
    connections.set_session(nombre, "tok-de-prueba", "jwt")
    uri = LayerUri(nombre, 4, 11, "points", filtro=ARBOL)
    return QgsVectorLayer(str(uri), "Arbolado", "geosian")


def test_con_un_servidor_que_lo_entiende_se_manda_en_cada_peticion(app):
    from geosian.provider.metadata import register_provider

    register_provider()
    with FakeGeosian() as fake:
        try:
            capa = _abrir(fake, "Con árbol", admite=True)
            assert capa.isValid(), str(capa.dataProvider().error())
            fake.peticiones.clear()
            list(capa.getFeatures())
            consultas = [c for r, c in fake.peticiones if r == "/api/v1/geodata/paginated/"]
            assert consultas and all(json.loads(c["filtro"][0]) == ARBOL for c in consultas)
        finally:
            connections.remove_connection("Con árbol")


def test_con_un_servidor_antiguo_la_capa_no_abre_y_lo_dice(app):
    from geosian.provider.metadata import register_provider

    register_provider()
    with FakeGeosian() as fake:
        try:
            capa = _abrir(fake, "Sin árbol", admite=False)
            assert not capa.isValid()
            assert "condiciones combinadas" in str(capa.dataProvider().error())
        finally:
            connections.remove_connection("Sin árbol")
