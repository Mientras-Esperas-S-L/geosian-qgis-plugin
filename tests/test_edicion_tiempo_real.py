"""El tiempo real mientras se edita: con cambios sin guardar, la recarga espera."""

import pytest

qgis_core = pytest.importorskip("qgis.core")

from geosian.gui import realtime_hub
from tests.test_edicion_atributos import abrir, editar, elemento, servidor  # noqa: F401


@pytest.fixture
def capa(servidor):  # noqa: F811
    capa = abrir(servidor)
    list(capa.getFeatures())
    return capa


def test_sin_editar_recarga(capa, servidor):  # noqa: F811
    servidor.estado.tocar(1001, codigo="de otra")

    assert realtime_hub.recargar_capa(capa)

    assert capa.getFeature(1001)["codigo"] == "de otra"


def test_con_cambios_sin_guardar_espera(capa, servidor):  # noqa: F811
    editar(capa, 1002, codigo="mío")
    servidor.estado.tocar(1001, codigo="de otra")

    assert not realtime_hub.recargar_capa(capa)

    assert capa.getFeature(1001)["codigo"] == "A-001"
    assert capa.getFeature(1002)["codigo"] == "mío"


def test_al_descartar_recarga_lo_que_esperaba(capa, servidor):  # noqa: F811
    editar(capa, 1002, codigo="mío")
    servidor.estado.tocar(1001, codigo="de otra")
    realtime_hub.recargar_capa(capa)

    assert capa.rollBack()

    assert capa.getFeature(1001)["codigo"] == "de otra"


def test_al_guardar_recarga_lo_que_esperaba(capa, servidor):  # noqa: F811
    editar(capa, 1002, codigo="mío")
    servidor.estado.tocar(1001, codigo="de otra")
    realtime_hub.recargar_capa(capa)

    assert capa.commitChanges(), capa.commitErrors()

    assert capa.getFeature(1001)["codigo"] == "de otra"
    assert capa.getFeature(1002)["codigo"] == "mío"


def test_en_edicion_sin_cambios_lo_que_se_ve_es_la_version_de_partida(capa, servidor):  # noqa: F811
    assert capa.startEditing()
    servidor.estado.tocar(1001, codigo="de otra")
    assert realtime_hub.recargar_capa(capa)
    assert capa.getFeature(1001)["codigo"] == "de otra"

    # Edita sobre lo que ya ve: no es un conflicto.
    editar(capa, 1001, codigo="encima de lo suyo")
    assert capa.commitChanges(), capa.commitErrors()
    assert elemento(servidor, 1001)["codigo"] == "encima de lo suyo"
