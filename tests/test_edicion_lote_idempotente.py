"""Un guardado que se quedó sin respuesta no crea las altas dos veces.

Cada lote va con un ``lote_id`` y queda apuntado en disco hasta que llega la respuesta.
Si se corta, volver a guardar lo mismo lleva el mismo identificador y Geosian no lo
repite; guardar otra cosa pregunta antes cómo acabó aquel; y al reabrir la capa (QGIS
cerrado a mitad) se dice cómo acabó.
"""

import pytest

qgis_core = pytest.importorskip("qgis.core")

from geosian.core import lotes_sin_respuesta as pendientes
from geosian.gui import edicion as gui
from tests.test_edicion_altas import nuevo
from tests.test_edicion_atributos import (  # noqa: F401
    CONEXION,
    abrir,
    editar,
    lotes,
    servidor,
)


@pytest.fixture(autouse=True)
def sin_apuntes():
    pendientes.olvidar(CONEXION, 11, "points")
    yield
    pendientes.olvidar(CONEXION, 11, "points")


@pytest.fixture
def mensajes(monkeypatch):
    vistos = []
    monkeypatch.setattr(gui, "_mensaje", vistos.append)
    return vistos


def altas_en_el_servidor(servidor):  # noqa: F811
    return [e for e in servidor.estado.elementos if e["properties"]["id"] >= 2001]


def test_una_respuesta_normal_no_deja_apunte(servidor):  # noqa: F811
    capa = abrir(servidor)
    nuevo(capa, -3.69, 40.41, codigo="N-1")

    assert capa.commitChanges(), capa.commitErrors()

    assert lotes(servidor)[-1]["lote_id"]
    assert pendientes.apuntado(CONEXION, 11, "points") is None


def test_si_se_corta_y_se_vuelve_a_guardar_no_se_repite(servidor):  # noqa: F811
    capa = abrir(servidor)
    nuevo(capa, -3.69, 40.41, codigo="N-1")
    servidor.estado.perder_respuesta = True

    assert not capa.commitChanges()
    assert "No se sabe si GreenCityControl ha guardado" in " ".join(capa.commitErrors())
    assert len(altas_en_el_servidor(servidor)) == 1
    servidor.estado.perder_respuesta = False

    assert capa.commitChanges(), capa.commitErrors()

    assert len(altas_en_el_servidor(servidor)) == 1
    enviados = [d for r, d in servidor.peticiones if r == "/api/v1/geodata/confirmar/"]
    primero, segundo = enviados[-2:]
    assert primero["lote_id"] == segundo["lote_id"]
    assert pendientes.apuntado(CONEXION, 11, "points") is None


def test_si_se_corta_y_se_guarda_otra_cosa_avisa_de_que_entro(servidor):  # noqa: F811
    capa = abrir(servidor)
    nuevo(capa, -3.69, 40.41, codigo="N-1")
    servidor.estado.perder_respuesta = True
    assert not capa.commitChanges()
    servidor.estado.perder_respuesta = False
    enviados = len([r for r, _ in servidor.peticiones if r == "/api/v1/geodata/confirmar/"])

    nuevo(capa, -3.70, 40.42, codigo="N-2")
    assert not capa.commitChanges()

    assert "sí entró" in " ".join(capa.commitErrors())
    assert len([r for r, _ in servidor.peticiones if r == "/api/v1/geodata/confirmar/"]) == enviados
    assert len(altas_en_el_servidor(servidor)) == 1


def test_si_el_anterior_no_entro_se_guarda_lo_nuevo(servidor):  # noqa: F811
    pendientes.apuntar(CONEXION, 11, "points", "00000000-0000-4000-8000-000000000000")
    capa = abrir(servidor)
    nuevo(capa, -3.69, 40.41, codigo="N-1")

    assert capa.commitChanges(), capa.commitErrors()

    assert len(altas_en_el_servidor(servidor)) == 1
    assert lotes(servidor)[-1]["lote_id"] != "00000000-0000-4000-8000-000000000000"


def test_al_reabrir_tras_un_cierre_dice_que_entro(servidor, mensajes):  # noqa: F811
    from qgis.PyQt.QtCore import QCoreApplication

    capa = abrir(servidor)
    nuevo(capa, -3.69, 40.41, codigo="N-1")
    servidor.estado.perder_respuesta = True
    assert not capa.commitChanges()
    servidor.estado.perder_respuesta = False
    # QGIS se cierra: se pierde lo que tenía en memoria, el apunte en disco queda.
    capa.rollBack()
    del capa

    otra = abrir(servidor)
    QCoreApplication.processEvents()

    [texto] = mensajes
    assert "sí entró" in texto and "Arbolado" in texto
    assert pendientes.apuntado(CONEXION, 11, "points") is None
    assert otra.isValid()


def test_al_reabrir_sin_apunte_no_dice_nada(servidor, mensajes):  # noqa: F811
    from qgis.PyQt.QtCore import QCoreApplication

    abrir(servidor)
    QCoreApplication.processEvents()

    assert mensajes == []
