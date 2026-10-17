"""Cambiar la geometría desde QGIS y confirmarla en Geosian, todo o nada."""

import pytest

qgis_core = pytest.importorskip("qgis.core")

from qgis.core import QgsGeometry, QgsPointXY, QgsVectorDataProvider

from tests.test_edicion_atributos import (  # noqa: F401
    abrir,
    editar,
    elemento,
    indice,
    lotes,
    servidor,
)


@pytest.fixture
def capa(servidor):  # noqa: F811
    return abrir(servidor)


def mover(capa, fid, x, y):
    if not capa.isEditable():
        assert capa.startEditing()
    assert capa.changeGeometry(fid, QgsGeometry.fromPointXY(QgsPointXY(x, y)))


def test_con_permiso_de_edicion_cambia_geometrias(capa):
    capacidades = capa.dataProvider().capabilities()
    assert capacidades & QgsVectorDataProvider.ChangeGeometries
    assert capacidades & QgsVectorDataProvider.ChangeFeatures


def test_mover_un_punto_va_con_su_version(capa, servidor):  # noqa: F811
    list(capa.getFeatures())
    version = servidor.estado.versiones[1001]

    mover(capa, 1001, -3.5, 40.5)
    assert capa.commitChanges(), capa.commitErrors()

    [lote] = lotes(servidor)
    assert lote["cambiar"] == [{
        "id": 1001, "expected_updated_at": version,
        "geometry": {"type": "Point", "coordinates": [-3.5, 40.5]},
    }]
    assert capa.getFeature(1001).geometry().asPoint() == QgsPointXY(-3.5, 40.5)


def test_atributos_y_geometria_del_mismo_elemento_van_juntos(capa, servidor):  # noqa: F811
    list(capa.getFeatures())
    mover(capa, 1002, -3.6, 40.6)
    editar(capa, 1002, codigo="movido")

    assert capa.commitChanges(), capa.commitErrors()

    [cambio] = lotes(servidor)[0]["cambiar"]
    assert cambio["attributes"] == {"codigo": "movido"}
    assert cambio["geometry"]["coordinates"] == [-3.6, 40.6]
    assert elemento(servidor, 1002)["codigo"] == "movido"


def test_atributos_de_uno_y_geometria_de_otro_en_un_solo_lote(capa, servidor):  # noqa: F811
    list(capa.getFeatures())
    mover(capa, 1001, -3.5, 40.5)
    editar(capa, 1002, codigo="otro")

    assert capa.commitChanges(), capa.commitErrors()

    assert len(lotes(servidor)) == 1
    assert {c["id"] for c in lotes(servidor)[0]["cambiar"]} == {1001, 1002}


def test_si_otro_lo_movio_no_entra_nada(capa, servidor):  # noqa: F811
    list(capa.getFeatures())
    mover(capa, 1001, -3.5, 40.5)
    editar(capa, 1002, codigo="otro")
    servidor.estado.tocar(1001)

    assert not capa.commitChanges()

    assert capa.isEditable()
    assert 1001 in capa.editBuffer().changedGeometries()
    assert elemento(servidor, 1002)["codigo"] == "A-002"


def test_quitar_la_geometria_no_se_manda(capa, servidor):  # noqa: F811
    list(capa.getFeatures())
    assert capa.startEditing()
    assert capa.changeGeometry(1001, QgsGeometry())

    assert not capa.commitChanges()

    assert lotes(servidor) == []
    assert any("sin geometría" in e for e in capa.commitErrors())
    assert indice(capa, "codigo") >= 0


@pytest.mark.parametrize("wkt", ["PointZ (-3.69 40.41 650)", "PointM (-3.69 40.41 7)", "PointZM (-3.69 40.41 650 7)"])
def test_la_altura_y_la_medida_no_se_mandan(capa, servidor, wkt):  # noqa: F811
    """Geosian guarda en 2D. QGIS no comprueba el tipo al cambiar una geometría."""
    list(capa.getFeatures())
    capa.startEditing()
    assert capa.changeGeometry(1001, QgsGeometry.fromWkt(wkt))

    assert capa.commitChanges(), capa.commitErrors()

    [cambio] = lotes(servidor)[-1]["cambiar"]
    assert cambio["geometry"] == {"type": "Point", "coordinates": [-3.69, 40.41]}
