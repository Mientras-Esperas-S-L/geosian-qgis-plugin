"""Los campos calculados del LAD (``computed_value``) en QGIS: los rellena Geosian.

En la web los rellena el formulario; desde QGIS, el servidor al confirmar el lote.
Aquí no se calcula nada: el campo no se teclea, un valor pegado no se manda y lo que
devuelve el servidor se ve en la capa.
"""

import copy

import pytest

qgis_core = pytest.importorskip("qgis.core")

from geosian.core import lad
from tests import fake_server
from tests.test_edicion_altas import nuevo
from tests.test_edicion_atributos import (  # noqa: F401
    abrir,
    editar,
    elemento,
    indice,
    lotes,
    servidor,
)

CODIGOS = {"Platanus x hispanica": "PLH", "Tilia platyphyllos": "TPL"}


@pytest.fixture
def capa(servidor, monkeypatch):  # noqa: F811
    esquema = copy.deepcopy(fake_server.ESQUEMA_ARBOLADO)
    esquema["attributes"].append({
        "name": "cod_especie", "type": "string", "title": "Código de especie",
        "computed_value": {
            "type": "lookup", "key_fields": ["especie"], "value_field": "codigo",
            "data": {nombre: {"codigo": codigo} for nombre, codigo in CODIGOS.items()},
        },
    })
    monkeypatch.setattr(fake_server, "ESQUEMA_ARBOLADO", esquema)

    def calcular(antes, nuevos):
        especie = nuevos.get("especie")
        return {"cod_especie": CODIGOS[especie]} if especie in CODIGOS else {}

    servidor.estado.calcular = calcular
    return abrir(servidor)


def test_el_calculado_no_se_teclea_en_el_formulario(capa):
    # Lo aplica el panel al añadir la capa al proyecto.
    lad.apply_editor_config(capa, capa.dataProvider().schema)

    assert capa.editFormConfig().readOnly(indice(capa, "cod_especie"))
    assert not capa.editFormConfig().readOnly(indice(capa, "especie"))


def test_cambiar_la_especie_trae_el_codigo_de_geosian(capa, servidor):  # noqa: F811
    editar(capa, 1001, especie="Tilia platyphyllos")

    assert capa.commitChanges(), capa.commitErrors()

    assert lotes(servidor)[0]["cambiar"][0]["attributes"] == {"especie": "Tilia platyphyllos"}
    assert capa.getFeature(1001)["cod_especie"] == "TPL"
    assert elemento(servidor, 1001)["cod_especie"] == "TPL"


def test_escribir_el_calculado_no_se_manda(capa, servidor):  # noqa: F811
    editar(capa, 1001, cod_especie="XXX")

    assert not capa.commitChanges()

    assert lotes(servidor) == []
    assert any("campo calculado" in e for e in capa.commitErrors())


def test_un_alta_pegada_no_manda_el_calculado_y_trae_el_de_geosian(capa, servidor):  # noqa: F811
    nuevo(capa, -3.69, 40.41, codigo="N-1", especie="Platanus x hispanica", cod_especie="VIEJO")

    assert capa.commitChanges(), capa.commitErrors()

    assert "cod_especie" not in lotes(servidor)[0]["crear"][0]["attributes"]
    assert capa.getFeature(2001)["cod_especie"] == "PLH"


def test_un_alta_sin_codigo_en_geosian_no_se_queda_con_el_pegado(capa, servidor):  # noqa: F811
    nuevo(capa, -3.69, 40.41, codigo="N-2", cod_especie="VIEJO")

    assert capa.commitChanges(), capa.commitErrors()

    assert capa.getFeature(2001)["cod_especie"] in (None, "") or capa.getFeature(2001).isNull(
        indice(capa, "cod_especie")
    )


def test_lo_demas_que_pone_geosian_tambien_se_ve(capa, servidor):  # noqa: F811
    # Un código REFER, un disparador...: el servidor lo devuelve en «calculados».
    servidor.estado.calcular = lambda antes, nuevos: {"observaciones": "puesto por Geosian"}
    editar(capa, 1001, altura=20.0)
    nuevo(capa, -3.69, 40.41, codigo="N-3")

    assert capa.commitChanges(), capa.commitErrors()

    assert capa.getFeature(1001)["observaciones"] == "puesto por Geosian"
    assert capa.getFeature(2001)["observaciones"] == "puesto por Geosian"


def test_la_superficie_automatica_es_como_un_calculado(servidor, monkeypatch):  # noqa: F811
    esquema = copy.deepcopy(fake_server.ESQUEMA_ARBOLADO)
    esquema["attributes"].append({"name": "copa", "type": "number", "title": "Copa", "autocalculed-surface": True})
    monkeypatch.setattr(fake_server, "ESQUEMA_ARBOLADO", esquema)
    capa = abrir(servidor)
    lad.apply_editor_config(capa, capa.dataProvider().schema)

    assert capa.editFormConfig().readOnly(indice(capa, "copa"))
    editar(capa, 1001, copa=3.0)
    assert not capa.commitChanges()
    assert any("campo calculado" in e for e in capa.commitErrors())
