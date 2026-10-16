"""Dar de alta elementos desde QGIS y confirmarlos en Geosian, todo o nada."""

import pytest

qgis_core = pytest.importorskip("qgis.core")

from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsVectorDataProvider

from tests.fake_server import TODOS_LOS_PERMISOS
from tests.test_edicion_atributos import (  # noqa: F401
    abrir,
    editar,
    elemento,
    lotes,
    servidor,
)


@pytest.fixture
def capa(servidor):  # noqa: F811
    return abrir(servidor)


def nuevo(capa, x, y, **valores):
    if not capa.isEditable():
        assert capa.startEditing()
    feature = QgsFeature(capa.fields())
    for nombre, valor in valores.items():
        feature[nombre] = valor
    feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
    assert capa.addFeature(feature)
    return feature


def test_con_permiso_de_alta(capa):
    assert capa.dataProvider().capabilities() & QgsVectorDataProvider.AddFeatures


def test_sin_permiso_de_alta(servidor):  # noqa: F811
    servidor.estado.permisos[11] = {**TODOS_LOS_PERMISOS, "can_create": False}
    capa = abrir(servidor)

    assert not capa.dataProvider().capabilities() & QgsVectorDataProvider.AddFeatures


def test_un_alta_entra_con_su_id_real(capa, servidor):  # noqa: F811
    nuevo(capa, -3.69, 40.41, codigo="N-1", especie="Tilia platyphyllos", altura=3.0)

    assert capa.commitChanges(), capa.commitErrors()

    [lote] = lotes(servidor)
    [alta] = lote["crear"]
    assert alta["geometry"] == {"type": "Point", "coordinates": [-3.69, 40.41]}
    assert alta["attributes"] == {"codigo": "N-1", "especie": "Tilia platyphyllos", "altura": 3.0}
    assert int(alta["ref"]) < 0
    creado = capa.getFeature(2001)
    assert creado.isValid()
    assert creado["codigo"] == "N-1"
    assert creado["object_id"] == "OBJ-2001"
    assert elemento(servidor, 2001)["especie"] == "Tilia platyphyllos"


def test_altas_y_cambios_en_un_solo_lote(capa, servidor):  # noqa: F811
    list(capa.getFeatures())
    nuevo(capa, -3.69, 40.41, codigo="N-1")
    nuevo(capa, -3.68, 40.42, codigo="N-2")
    editar(capa, 1001, codigo="cambiado")

    assert capa.commitChanges(), capa.commitErrors()

    [lote] = lotes(servidor)
    assert sorted(a["attributes"]["codigo"] for a in lote["crear"]) == ["N-1", "N-2"]
    assert [c["id"] for c in lote["cambiar"]] == [1001]
    assert {f["codigo"] for f in capa.getFeatures()} >= {"N-1", "N-2", "cambiado"}


def test_editar_el_alta_antes_de_confirmar_va_en_el_alta(capa, servidor):  # noqa: F811
    nuevo(capa, -3.69, 40.41, codigo="borrador")
    provisional = next(iter(capa.editBuffer().addedFeatures()))
    editar(capa, provisional, codigo="definitivo")

    assert capa.commitChanges(), capa.commitErrors()

    [lote] = lotes(servidor)
    assert lote["cambiar"] == []
    assert lote["crear"][0]["attributes"]["codigo"] == "definitivo"


def test_lo_que_pone_geosian_no_se_manda(capa, servidor):  # noqa: F811
    # Como al pegar un elemento copiado de otra capa: trae id, object_id y fecha.
    nuevo(capa, -3.69, 40.41, codigo="pegado", id=1001, object_id="OBJ-1001", updated_at="2026-01-01")

    assert capa.commitChanges(), capa.commitErrors()

    assert lotes(servidor)[0]["crear"][0]["attributes"] == {"codigo": "pegado"}


def test_si_el_lote_falla_el_alta_sigue_pendiente(capa, servidor):  # noqa: F811
    list(capa.getFeatures())
    nuevo(capa, -3.69, 40.41, codigo="N-1")
    editar(capa, 1001, codigo="mío")
    servidor.estado.tocar(1001)

    assert not capa.commitChanges()

    assert len(capa.editBuffer().addedFeatures()) == 1
    assert not any(e["properties"].get("codigo") == "N-1" for e in servidor.estado.elementos)


def test_un_alta_sin_geometria_no_se_manda(capa, servidor):  # noqa: F811
    assert capa.startEditing()
    feature = QgsFeature(capa.fields())
    feature["codigo"] = "sin forma"
    assert capa.addFeature(feature)

    assert not capa.commitChanges()

    assert lotes(servidor) == []
    assert any("sin geometría" in e for e in capa.commitErrors())
