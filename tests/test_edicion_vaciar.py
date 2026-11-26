"""Vaciar un campo de lista desde QGIS.

Un texto vacío es dejar el campo vacío, igual que un nulo: no un valor fuera de la
lista. Y vaciar un campo con valor en muchos elementos de una vez se pregunta antes,
porque con la calculadora de campos un nulo vacía la capa entera sin que se note.
"""

import copy

import pytest

qgis_core = pytest.importorskip("qgis.core")

from geosian.gui import edicion
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


class TestTextoVacioEsVaciar:
    def test_texto_vacio_en_una_multiple_la_vacia(self, capa, servidor):  # noqa: F811
        # La calculadora de campos, al asignar '' a un campo de lista, deja [''].
        editar(capa, 1001, operacion=[""])

        assert capa.commitChanges(), capa.commitErrors()
        assert elemento(servidor, 1001)["operacion"] is None

    def test_texto_vacio_en_una_lista_simple_la_vacia(self, capa, servidor):  # noqa: F811
        editar(capa, 1001, especie="")

        assert capa.commitChanges(), capa.commitErrors()
        assert elemento(servidor, 1001)["especie"] in ("", None)

    def test_un_texto_vacio_junto_a_valores_no_cuenta(self, capa, servidor):  # noqa: F811
        editar(capa, 1001, operacion=["Poda", "", "Tala"])

        assert capa.commitChanges(), capa.commitErrors()
        assert elemento(servidor, 1001)["operacion"] == ["Poda", "Tala"]

    def test_lo_que_no_esta_en_la_lista_sigue_sin_entrar(self, capa, servidor):  # noqa: F811
        editar(capa, 1001, operacion=["", "Riego a manta"])

        assert not capa.commitChanges()
        assert lotes(servidor) == []
        assert any("Riego a manta" in e for e in capa.commitErrors())


def _con_elementos(servidor, cuantos):  # noqa: F811
    """La capa con ``cuantos`` elementos más, todos con especie y operación."""
    base = servidor.estado.elementos[0]
    for n in range(cuantos):
        nuevo = copy.deepcopy(base)
        nuevo["properties"]["id"] = 2000 + n
        nuevo["properties"]["object_id"] = f"OBJ-{2000 + n}"
        servidor.estado.elementos.append(nuevo)
        servidor.estado.versiones[2000 + n] = servidor.estado.versiones[1001]
    return [2000 + n for n in range(cuantos)]


class TestAvisoAlVaciarMuchos:
    @pytest.fixture
    def preguntas(self, monkeypatch):
        hechas = []

        def responder(capa, vaciados):
            hechas.append(dict(vaciados))
            return responder.respuesta

        responder.respuesta = False
        monkeypatch.setattr(edicion, "preguntar_vaciado", responder)
        return responder, hechas

    def test_cancelar_no_guarda_nada(self, servidor, preguntas):  # noqa: F811
        _responder, hechas = preguntas
        ids = _con_elementos(servidor, edicion.UMBRAL_VACIADO)
        capa = abrir(servidor)
        list(capa.getFeatures())
        for fid in ids:
            editar(capa, fid, operacion=None)

        assert not capa.commitChanges()

        assert hechas == [{"Operaciones": edicion.UMBRAL_VACIADO}]
        assert lotes(servidor) == []
        assert any("cancelado el vaciado" in e for e in capa.commitErrors())
        # Lo pendiente sigue ahí, para revisarlo o deshacerlo.
        assert capa.isEditable() and capa.editBuffer().changedAttributeValues()

    def test_aceptar_guarda(self, servidor, preguntas):  # noqa: F811
        responder, hechas = preguntas
        responder.respuesta = True
        ids = _con_elementos(servidor, edicion.UMBRAL_VACIADO)
        capa = abrir(servidor)
        list(capa.getFeatures())
        for fid in ids:
            editar(capa, fid, operacion=[""])

        assert capa.commitChanges(), capa.commitErrors()
        assert len(hechas) == 1
        assert all(elemento(servidor, fid)["operacion"] is None for fid in ids)

    def test_pocos_no_preguntan(self, capa, servidor, preguntas):  # noqa: F811
        _responder, hechas = preguntas
        list(capa.getFeatures())
        editar(capa, 1001, operacion=None)
        editar(capa, 1002, operacion=None)

        assert capa.commitChanges(), capa.commitErrors()
        assert hechas == []

    def test_lo_que_ya_estaba_vacio_no_cuenta(self, servidor, preguntas):  # noqa: F811
        _responder, hechas = preguntas
        ids = _con_elementos(servidor, edicion.UMBRAL_VACIADO)
        for e in servidor.estado.elementos:
            if e["properties"]["id"] in ids:
                e["properties"]["observaciones"] = None
        capa = abrir(servidor)
        list(capa.getFeatures())
        for fid in ids:
            editar(capa, fid, observaciones="")

        capa.commitChanges()
        assert hechas == []

    def test_cambiar_valores_no_pregunta(self, servidor, preguntas):  # noqa: F811
        _responder, hechas = preguntas
        ids = _con_elementos(servidor, edicion.UMBRAL_VACIADO)
        capa = abrir(servidor)
        list(capa.getFeatures())
        for fid in ids:
            editar(capa, fid, operacion=["Tala"])

        assert capa.commitChanges(), capa.commitErrors()
        assert hechas == []
