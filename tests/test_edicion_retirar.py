"""Suprimir en QGIS es retirar en Geosian: el elemento pasa a «no disponible»."""

import pytest

qgis_core = pytest.importorskip("qgis.core")

from qgis.core import QgsVectorDataProvider

from geosian.gui import edicion
from tests.fake_server import TODOS_LOS_PERMISOS
from tests.test_edicion_atributos import (  # noqa: F401
    abrir,
    editar,
    elemento,
    lotes,
    servidor,
)


@pytest.fixture
def preguntas(monkeypatch):
    """Responde «sí» al diálogo de retirar y apunta cuántas veces y con cuántos."""
    hechas = []

    def responder(capa, cuantos):
        hechas.append(cuantos)
        return responder.si

    responder.si = True
    responder.hechas = hechas
    monkeypatch.setattr(edicion, "preguntar_retirada", responder)
    return responder


@pytest.fixture
def capa(servidor, preguntas):  # noqa: F811
    return abrir(servidor)


def suprimir(capa, *fids):
    if not capa.isEditable():
        assert capa.startEditing()
    for fid in fids:
        assert capa.deleteFeature(fid)


def test_con_permiso_de_retirar(capa):
    assert capa.dataProvider().capabilities() & QgsVectorDataProvider.DeleteFeatures


def test_sin_permiso_de_retirar(servidor, preguntas):  # noqa: F811
    servidor.estado.permisos[11] = {**TODOS_LOS_PERMISOS, "can_retire": False}
    capa = abrir(servidor)

    assert not capa.dataProvider().capabilities() & QgsVectorDataProvider.DeleteFeatures


def test_suprimir_retira_con_su_version_tras_preguntar(capa, servidor, preguntas):  # noqa: F811
    list(capa.getFeatures())
    version = servidor.estado.versiones[1002]

    suprimir(capa, 1002)
    assert capa.commitChanges(), capa.commitErrors()

    assert preguntas.hechas == [1]
    [lote] = lotes(servidor)
    assert lote["retirar"] == [{"id": 1002, "expected_updated_at": version}]
    assert not capa.getFeature(1002).isValid()
    assert all(e["properties"]["id"] != 1002 for e in servidor.estado.elementos)


def test_si_dice_que_no_no_se_guarda_nada(capa, servidor, preguntas):  # noqa: F811
    list(capa.getFeatures())
    suprimir(capa, 1002)
    editar(capa, 1001, codigo="cambio")
    preguntas.si = False

    assert not capa.commitChanges()

    assert lotes(servidor) == []
    assert capa.isEditable()
    assert 1002 in capa.editBuffer().deletedFeatureIds()
    assert any("cancelado la retirada" in e for e in capa.commitErrors())


def test_sin_retiradas_no_pregunta(capa, servidor, preguntas):  # noqa: F811
    editar(capa, 1001, codigo="cambio")

    assert capa.commitChanges(), capa.commitErrors()

    assert preguntas.hechas == []


def test_retirar_y_cambiar_otros_en_un_solo_lote(capa, servidor, preguntas):  # noqa: F811
    list(capa.getFeatures())
    suprimir(capa, 1002)
    editar(capa, 1001, codigo="cambio")

    assert capa.commitChanges(), capa.commitErrors()

    [lote] = lotes(servidor)
    assert [r["id"] for r in lote["retirar"]] == [1002]
    assert [c["id"] for c in lote["cambiar"]] == [1001]
    assert elemento(servidor, 1001)["codigo"] == "cambio"


def test_si_otro_lo_cambio_no_se_retira(capa, servidor, preguntas):  # noqa: F811
    list(capa.getFeatures())
    suprimir(capa, 1002)
    servidor.estado.tocar(1002, codigo="de otra")

    assert not capa.commitChanges()

    assert any(e["properties"]["id"] == 1002 for e in servidor.estado.elementos)
    assert 1002 in capa.editBuffer().deletedFeatureIds()
