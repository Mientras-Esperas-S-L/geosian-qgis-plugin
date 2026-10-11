"""Editar atributos desde QGIS y confirmarlos en Geosian, todo o nada.

Con QGIS de verdad y el servidor falso, que responde como ``/geodata/confirmar/``.
"""

import pytest

qgis_core = pytest.importorskip("qgis.core")

from qgis.core import QgsVectorDataProvider, QgsVectorLayer

from geosian.core import connections
from geosian.gui import edicion
from tests.fake_server import SIN_PERMISOS, FakeGeosian

CONEXION = "PruebaEdicion"
URI = f"geosian://{CONEXION}/map/4/layer/11?geometry_type=points"


@pytest.fixture
def servidor(app):
    with FakeGeosian() as fake:
        connections.save_connection(CONEXION, fake.url, "tecnico@ejemplo.com")
        connections.set_session(CONEXION, "tok-de-prueba", "jwt-de-prueba")
        yield fake
        connections.remove_connection(CONEXION)


def abrir(servidor):
    capa = QgsVectorLayer(URI, "Arbolado", "geosian")
    assert capa.isValid(), capa.dataProvider().error()
    assert edicion.enganchar(capa)
    return capa


@pytest.fixture
def capa(servidor):
    return abrir(servidor)


def indice(capa, nombre):
    i = capa.fields().indexOf(nombre)
    assert i >= 0, nombre
    return i


def editar(capa, fid, **valores):
    if not capa.isEditable():
        assert capa.startEditing()
    for nombre, valor in valores.items():
        assert capa.changeAttributeValue(fid, indice(capa, nombre), valor)


def lotes(servidor):
    return servidor.estado.lotes


def elemento(servidor, fid):
    return next(e for e in servidor.estado.elementos if e["properties"]["id"] == fid)["properties"]


class TestQuePuedeHacer:
    def test_con_permiso_de_edicion_cambia_atributos(self, capa):
        capacidades = capa.dataProvider().capabilities()
        assert capacidades & QgsVectorDataProvider.ChangeAttributeValues

    def test_sin_permiso_es_de_solo_lectura(self, servidor):
        servidor.estado.permisos[11] = dict(SIN_PERMISOS)
        capa = abrir(servidor)

        assert not capa.dataProvider().capabilities() & QgsVectorDataProvider.ChangeAttributeValues
        assert not capa.startEditing()

    def test_un_servidor_que_no_da_permisos_deja_la_capa_de_solo_lectura(self, servidor):
        servidor.estado.permisos.clear()
        capa = abrir(servidor)

        assert not capa.startEditing()


class TestConfirmar:
    def test_un_cambio_va_al_servidor_con_su_version(self, capa, servidor):
        list(capa.getFeatures())
        version = servidor.estado.versiones[1001]

        editar(capa, 1001, codigo="A-001-B", altura=13.25)
        assert capa.commitChanges(), capa.commitErrors()

        [lote] = lotes(servidor)
        assert lote["layer_id"] == 11
        assert lote["geometry_type"] == "points"
        assert lote["cambiar"] == [{
            "id": 1001, "expected_updated_at": version,
            "attributes": {"codigo": "A-001-B", "altura": 13.25},
        }]
        assert lote["crear"] == [] and lote["retirar"] == []
        assert elemento(servidor, 1001)["codigo"] == "A-001-B"

    def test_lo_confirmado_se_ve_en_la_capa(self, capa, servidor):
        editar(capa, 1001, codigo="A-001-B")
        assert capa.commitChanges(), capa.commitErrors()

        assert capa.getFeature(1001)["codigo"] == "A-001-B"

    def test_varios_elementos_van_en_un_solo_lote(self, capa, servidor):
        editar(capa, 1001, codigo="X1")
        editar(capa, 1002, codigo="X2")
        assert capa.commitChanges(), capa.commitErrors()

        assert len(lotes(servidor)) == 1
        assert {c["id"] for c in lotes(servidor)[0]["cambiar"]} == {1001, 1002}

    def test_seguir_editando_tras_confirmar_usa_la_version_nueva(self, capa, servidor):
        editar(capa, 1001, codigo="X1")
        assert capa.commitChanges(stopEditing=False), capa.commitErrors()
        nueva = servidor.estado.versiones[1001]

        editar(capa, 1001, codigo="X2")
        assert capa.commitChanges(), capa.commitErrors()

        assert lotes(servidor)[1]["cambiar"][0]["expected_updated_at"] == nueva
        assert elemento(servidor, 1001)["codigo"] == "X2"

    def test_valores_como_los_guarda_la_web(self, capa, servidor):
        editar(capa, 1001, operacion=["Poda", "Tala"], observaciones=None, fecha_plantacion="2020-01-31")
        assert capa.commitChanges(), capa.commitErrors()

        atributos = lotes(servidor)[0]["cambiar"][0]["attributes"]
        assert atributos == {"operacion": ["Poda", "Tala"], "observaciones": None, "fecha_plantacion": "2020-01-31"}

    def test_el_atributo_renombrado_vuelve_a_su_nombre(self, capa, servidor):
        # «id» del esquema choca con el id de sistema: en QGIS es attr__id.
        editar(capa, 1001, attr__id=77)
        assert capa.commitChanges(), capa.commitErrors()

        assert lotes(servidor)[0]["cambiar"][0]["attributes"] == {"id": 77}


class TestNoSeGuardaNada:
    def test_si_otro_lo_cambio_no_entra_y_sigue_pendiente(self, capa, servidor):
        list(capa.getFeatures())
        editar(capa, 1001, codigo="mío")
        servidor.estado.tocar(1001, codigo="de otra")

        assert not capa.commitChanges()

        assert capa.isEditable()
        assert capa.editBuffer().changedAttributeValues()[1001][indice(capa, "codigo")] == "mío"
        assert elemento(servidor, 1001)["codigo"] == "de otra"
        assert any("alguien cambió" in e and "1001" in e and "Otra Técnica" in e for e in capa.commitErrors())

    def test_una_recarga_a_mitad_no_esconde_el_conflicto(self, capa, servidor):
        list(capa.getFeatures())
        assert capa.startEditing()
        servidor.estado.tocar(1001, codigo="de otra")
        # El tiempo real recarga la capa y trae la versión nueva...
        capa.dataProvider().reloadData()
        list(capa.getFeatures())
        editar(capa, 1001, codigo="mío")

        # ...pero se manda la que había al empezar a editar.
        assert not capa.commitChanges()
        assert elemento(servidor, 1001)["codigo"] == "de otra"

    def test_un_campo_de_solo_lectura_no_se_manda(self, capa, servidor):
        editar(capa, 1001, object_id="OTRO")

        assert not capa.commitChanges()

        assert lotes(servidor) == []
        assert any("lo pone Geosian" in e or "solo lectura" in e for e in capa.commitErrors())

    def test_un_error_del_servidor_lo_deja_todo_pendiente(self, capa, servidor):
        servidor.estado.forzar = (403, {"error": "No tiene permisos para update este elemento específico"})
        editar(capa, 1001, codigo="X")

        assert not capa.commitChanges()

        assert capa.isEditable()
        assert 1001 in capa.editBuffer().changedAttributeValues()
        assert any("este elemento específico" in e for e in capa.commitErrors())

    def test_tras_un_fallo_se_puede_volver_a_confirmar(self, capa, servidor):
        list(capa.getFeatures())
        editar(capa, 1001, codigo="mío")
        servidor.estado.forzar = (400, {"errores": [{"op": "cambiar", "id": 1001, "error": "algo"}]})
        assert not capa.commitChanges()

        assert capa.commitChanges(), capa.commitErrors()
        assert elemento(servidor, 1001)["codigo"] == "mío"

    def test_descartar_no_manda_nada(self, capa, servidor):
        editar(capa, 1001, codigo="X")
        assert capa.rollBack()

        assert lotes(servidor) == []
        assert capa.getFeature(1001)["codigo"] == "A-001"
