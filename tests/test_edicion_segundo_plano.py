"""El lote grande, en QGIS: se confirma esperando a Geosian, todo o nada.

Con el servidor falso respondiendo 202 y el estado de la tarea, como el backend por
encima de ``LOTE_SINCRONO``. El cliente, sin QGIS: ``test_lote_en_segundo_plano.py``.
"""

import pytest

qgis_core = pytest.importorskip("qgis.core")

from geosian.core import client as C
from geosian.gui import edicion as gui
from tests.test_edicion_atributos import (  # noqa: F401
    abrir,
    editar,
    elemento,
    servidor,
)


@pytest.fixture
def en_segundo_plano(servidor, monkeypatch):  # noqa: F811
    monkeypatch.setattr(C, "PAUSA_DE_LOTE", 0.01)
    servidor.estado.lote_sincrono = 1
    return servidor


def test_qgis_confirma_un_lote_en_segundo_plano(en_segundo_plano, monkeypatch):
    servidor = en_segundo_plano  # noqa: F811
    avisos = []
    monkeypatch.setattr(gui, "_al_encolar", lambda capa, total: avisos.append(total))
    capa = abrir(servidor)
    editar(capa, 1001, codigo="uno")
    editar(capa, 1002, codigo="dos")

    assert capa.commitChanges(), capa.commitErrors()

    assert avisos == [2]
    assert elemento(servidor, 1001)["codigo"] == "uno"
    assert elemento(servidor, 1002)["codigo"] == "dos"
    preguntas = [r for r, _ in servidor.peticiones if r.startswith("/api/v1/tasks/")]
    assert len(preguntas) == servidor.estado.vueltas_de_tarea + 1


def test_qgis_un_choque_en_segundo_plano_no_guarda_nada(en_segundo_plano, monkeypatch):
    servidor = en_segundo_plano  # noqa: F811
    vistos = []
    monkeypatch.setattr(gui, "_al_encolar", lambda capa, total: None)
    monkeypatch.setattr(gui, "_al_conflicto", lambda capa, proveedor, choques: vistos.append(choques))
    capa = abrir(servidor)
    list(capa.getFeatures())
    editar(capa, 1001, codigo="mío")
    editar(capa, 1002, codigo="otro mío")
    servidor.estado.tocar(1001, codigo="suyo")

    assert not capa.commitChanges()

    assert [c["id"] for c in vistos[0]] == [1001]
    assert elemento(servidor, 1002)["codigo"] != "otro mío"
    assert capa.isEditable()


def test_qgis_si_no_se_sabe_lo_dice_y_no_dice_que_no_guardo(en_segundo_plano, monkeypatch):
    from geosian.core.errors import LoteIncierto

    servidor = en_segundo_plano  # noqa: F811

    def incierto(self, task_id, esperar):
        raise LoteIncierto(C.INCIERTO.format(motivo="prueba"))

    monkeypatch.setattr(gui, "_al_encolar", lambda capa, total: None)
    monkeypatch.setattr(C.GeosianClient, "_esperar_lote", incierto)
    capa = abrir(servidor)
    editar(capa, 1001, codigo="uno")
    editar(capa, 1002, codigo="dos")

    assert not capa.commitChanges()

    errores = " ".join(capa.commitErrors())
    assert "No se sabe si Geosian ha guardado" in errores
    assert "no ha guardado nada" not in errores


def test_qgis_tras_cambiar_el_origen_se_sigue_guardando(servidor):  # noqa: F811
    """Filtrar por partes o reconectar le pone a la capa un proveedor nuevo."""
    from qgis.core import QgsDataProvider

    from tests.test_edicion_atributos import URI

    capa = abrir(servidor)
    viejo = capa.dataProvider()
    capa.setDataSource(URI, capa.name(), "geosian", QgsDataProvider.ProviderOptions())
    assert capa.isValid() and capa.dataProvider() is not viejo
    editar(capa, 1001, codigo="tras el filtro")

    assert capa.commitChanges(), capa.commitErrors()

    assert elemento(servidor, 1001)["codigo"] == "tras el filtro"
    assert capa.dataProvider().al_conflicto is not None
