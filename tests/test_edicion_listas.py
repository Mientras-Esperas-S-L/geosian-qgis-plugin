"""Las listas cerradas solo admiten sus valores, como el formulario de la web.

En QGIS se puede escribir cualquier cosa con la calculadora de campos o la tabla; al
confirmar, lo que no esté en la lista de Geosian para la confirmación con el motivo.
"""

import pytest

qgis_core = pytest.importorskip("qgis.core")

from qgis.core import QgsFeature, QgsGeometry, QgsPointXY

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


def test_un_valor_de_la_lista_entra(capa, servidor):  # noqa: F811
    editar(capa, 1001, especie="Tilia platyphyllos", operacion=["Poda", "Tala"])

    assert capa.commitChanges(), capa.commitErrors()
    assert elemento(servidor, 1001)["especie"] == "Tilia platyphyllos"


def test_un_valor_fuera_de_la_lista_no_entra(capa, servidor):  # noqa: F811
    editar(capa, 1001, especie="Quercus inventada")

    assert not capa.commitChanges()

    assert lotes(servidor) == []
    assert any("Quercus inventada" in e and "lista" in e for e in capa.commitErrors())


def test_en_una_multiple_cada_valor_tiene_que_estar(capa, servidor):  # noqa: F811
    editar(capa, 1001, operacion=["Poda", "Riego a manta"])

    assert not capa.commitChanges()
    assert any("Riego a manta" in e for e in capa.commitErrors())


def test_lo_guardado_fuera_de_la_lista_se_conserva(servidor):  # noqa: F811
    # Un valor retirado de la lista que el elemento ya tenía, como en la web.
    servidor.estado.elementos[0]["properties"]["operacion"] = ["Desbroce"]
    capa = abrir(servidor)
    list(capa.getFeatures())

    editar(capa, 1001, operacion=["Desbroce", "Poda"])

    assert capa.commitChanges(), capa.commitErrors()
    assert elemento(servidor, 1001)["operacion"] == ["Desbroce", "Poda"]


def test_un_alta_con_un_valor_fuera_de_la_lista_no_entra(capa, servidor):  # noqa: F811
    assert capa.startEditing()
    nuevo = QgsFeature(capa.fields())
    nuevo["codigo"] = "N-1"
    nuevo["nuevo_riesgo"] = "Altísimo"
    nuevo.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-3.69, 40.41)))
    assert capa.addFeature(nuevo)

    assert not capa.commitChanges()
    assert any("Altísimo" in e for e in capa.commitErrors())


def test_el_texto_libre_no_tiene_lista(capa, servidor):  # noqa: F811
    editar(capa, 1001, observaciones="Cualquier cosa")

    assert capa.commitChanges(), capa.commitErrors()
