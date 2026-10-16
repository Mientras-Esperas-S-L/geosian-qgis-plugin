"""Ante un 409, elegir por elemento: sobrescribir con lo mío o quedarse con lo de Geosian."""

import pytest

qgis_core = pytest.importorskip("qgis.core")

from qgis.core import QgsGeometry, QgsPointXY
from qgis.PyQt.QtCore import QCoreApplication

from geosian.gui import edicion
from tests.test_edicion_atributos import (  # noqa: F401
    abrir,
    editar,
    elemento,
    indice,
    lotes,
    servidor,
)


@pytest.fixture
def respuestas(monkeypatch):
    """Lo que «contesta» el diálogo de conflictos, y con qué se abrió."""
    vistas = []

    def responder(capa, conflictos):
        vistas.append(conflictos)
        return responder.decisiones

    responder.decisiones = None
    responder.vistas = vistas
    monkeypatch.setattr(edicion, "preguntar_conflictos", responder)
    monkeypatch.setattr(edicion, "preguntar_retirada", lambda capa, n: True)
    return responder


@pytest.fixture
def capa(servidor, respuestas):  # noqa: F811
    capa = abrir(servidor)
    list(capa.getFeatures())
    return capa


def confirmar_con_choque(capa, servidor, fid=1001, **suyo):  # noqa: F811
    servidor.estado.tocar(fid, **suyo)
    assert not capa.commitChanges()
    # El diálogo se abre cuando QGIS ha terminado de confirmar.
    QCoreApplication.processEvents()


def test_el_dialogo_se_abre_con_los_choques(capa, servidor, respuestas):  # noqa: F811
    editar(capa, 1001, codigo="mío")
    confirmar_con_choque(capa, servidor, codigo="suyo")

    [choques] = respuestas.vistas
    assert [c["id"] for c in choques] == [1001]
    assert choques[0]["updated_by"]["nombre"] == "Otra Técnica"


def test_sobrescribir_con_lo_mio(capa, servidor, respuestas):  # noqa: F811
    editar(capa, 1001, codigo="mío")
    respuestas.decisiones = {1001: edicion.MIO}
    confirmar_con_choque(capa, servidor, codigo="suyo")

    assert capa.commitChanges(), capa.commitErrors()

    assert elemento(servidor, 1001)["codigo"] == "mío"


def test_quedarme_con_lo_de_geosian(capa, servidor, respuestas):  # noqa: F811
    editar(capa, 1001, codigo="mío")
    editar(capa, 1002, codigo="otro mío")
    respuestas.decisiones = {1001: edicion.GEOSIAN}
    confirmar_con_choque(capa, servidor, codigo="suyo")

    # Lo de Geosian vuelve a la capa y mi cambio de 1001 no se manda.
    assert capa.getFeature(1001)["codigo"] == "suyo"
    assert capa.commitChanges(), capa.commitErrors()

    assert [c["id"] for c in lotes(servidor)[-1]["cambiar"]] == [1002]
    assert elemento(servidor, 1001)["codigo"] == "suyo"
    assert elemento(servidor, 1002)["codigo"] == "otro mío"


def test_quedarme_con_la_geometria_de_geosian(capa, servidor, respuestas):  # noqa: F811
    assert capa.startEditing()
    assert capa.changeGeometry(1001, QgsGeometry.fromPointXY(QgsPointXY(-3.5, 40.5)))
    respuestas.decisiones = {1001: edicion.GEOSIAN}
    servidor.estado.elementos[0]["geometry"] = {"type": "Point", "coordinates": [-3.6, 40.6]}
    confirmar_con_choque(capa, servidor)

    assert capa.getFeature(1001).geometry().asPoint() == QgsPointXY(-3.6, 40.6)
    assert capa.commitChanges(), capa.commitErrors()
    # No quedaba nada que mandar: ni siquiera se llama al servidor.
    assert len(lotes(servidor)) == 1
    assert elemento(servidor, 1001)  # sigue ahí, con su geometría
    assert servidor.estado.elementos[0]["geometry"]["coordinates"] == [-3.6, 40.6]


def test_cancelar_el_dialogo_lo_deja_todo_como_estaba(capa, servidor, respuestas):  # noqa: F811
    editar(capa, 1001, codigo="mío")
    respuestas.decisiones = None
    confirmar_con_choque(capa, servidor, codigo="suyo")

    assert capa.editBuffer().changedAttributeValues()[1001][indice(capa, "codigo")] == "mío"
    assert not capa.commitChanges()


def test_no_se_puede_sobrescribir_un_elemento_retirado(capa, servidor, respuestas):  # noqa: F811
    editar(capa, 1001, codigo="mío")
    choque = {"id": 1001, "updated_at": "2026-10-11T12:00:00+00:00", "object_status": "no_disponible"}

    avisos = edicion.resolver_conflictos(capa, capa.dataProvider(), [choque], {1001: edicion.MIO})

    assert avisos and "retirado" in avisos[0]


def test_el_dialogo_ofrece_las_dos_salidas_salvo_si_lo_retiraron(app, capa):
    conflictos = [
        {"id": 1001, "updated_at": "2026-10-11T12:00:00.000001+00:00", "object_status": "disponible",
         "updated_by": {"nombre": "Otra Técnica"}},
        {"id": 1002, "updated_at": "2026-10-11T12:00:00+00:00", "object_status": "no_disponible"},
    ]

    dialogo = edicion.dialogo_de_conflictos(capa, conflictos)

    opciones = {
        fid: [combo.itemData(i) for i in range(combo.count())] for fid, combo in dialogo.combos.items()
    }
    assert opciones == {1001: [edicion.GEOSIAN, edicion.MIO], 1002: [edicion.GEOSIAN]}
    dialogo.combos[1001].setCurrentIndex(1)
    assert dialogo.decisiones() == {1001: edicion.MIO, 1002: edicion.GEOSIAN}
    dialogo.deleteLater()
