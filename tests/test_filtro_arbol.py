"""Las condiciones combinadas (el filtro en árbol de GreenCityControl) en el plugin.

Un servidor que no entiende el parámetro `filtro` lo ignoraría y la capa saldría sin
filtrar, sin aviso: el plugin lo comprueba antes, y si no, la capa no abre y lo dice.
"""

import json

import pytest

pytest.importorskip("qgis.core")

from geosian.core import connections
from geosian.core.client import _ADMITE_FILTRO
from tests.fake_server import FakeGeosian

ARBOL = {"todas": True, "condiciones": [{"campo": "especie", "op": "es_uno_de", "valor": ["Tilia platyphyllos"]}]}


@pytest.fixture(autouse=True)
def _sin_recuerdo():
    _ADMITE_FILTRO.clear()
    yield
    _ADMITE_FILTRO.clear()


def _abrir(fake, nombre, admite):
    from qgis.core import QgsVectorLayer

    from geosian.provider.uri import LayerUri

    fake._server.admite_filtro = admite
    connections.save_connection(nombre, fake.url, "a@b.c")
    connections.set_session(nombre, "tok-de-prueba", "jwt")
    uri = LayerUri(nombre, 4, 11, "points", filtro=ARBOL)
    return QgsVectorLayer(str(uri), "Arbolado", "geosian")


def test_con_un_servidor_que_lo_entiende_se_manda_en_cada_peticion(app):
    from geosian.provider.metadata import register_provider

    register_provider()
    with FakeGeosian() as fake:
        try:
            capa = _abrir(fake, "Con árbol", admite=True)
            assert capa.isValid(), str(capa.dataProvider().error())
            fake.peticiones.clear()
            list(capa.getFeatures())
            consultas = [c for r, c in fake.peticiones if r == "/api/v1/geodata/paginated/"]
            assert consultas and all(json.loads(c["filtro"][0]) == ARBOL for c in consultas)
        finally:
            connections.remove_connection("Con árbol")


def test_con_un_servidor_antiguo_la_capa_no_abre_y_lo_dice(app):
    from geosian.provider.metadata import register_provider

    register_provider()
    with FakeGeosian() as fake:
        try:
            capa = _abrir(fake, "Sin árbol", admite=False)
            assert not capa.isValid()
            assert "condiciones combinadas" in str(capa.dataProvider().error())
        finally:
            connections.remove_connection("Sin árbol")


# --------------------------------------------------------------------------- el diálogo

def test_el_dialogo_construye_el_arbol_y_lo_deja_en_la_uri(app):
    from qgis.core import QgsProject
    from qgis.PyQt.QtCore import Qt

    from geosian.gui.condiciones_combinadas import CondicionesDialog
    from geosian.provider.metadata import register_provider
    from tests.test_gui import _capa_de_prueba

    register_provider()
    with FakeGeosian() as fake:
        try:
            capa = _capa_de_prueba(fake, "Constructor")
            d = CondicionesDialog(capa)
            assert d.frase.text() == "Se muestran: Todos los elementos"

            # Una condición del elemento: especie es uno de Tilia platyphyllos.
            d.anadir_condicion()
            d.campo.setCurrentIndex(d.campo.findData("especie"))
            assert d.operador.currentData() == "es_uno_de"
            lista = d.valor_lista
            elegida = next(lista.item(i) for i in range(lista.count()) if lista.item(i).text() == "Tilia platyphyllos")
            elegida.setCheckState(Qt.CheckState.Checked)

            # Un bloque «sin ningún parte de poda en los últimos 30 días».
            d.anadir_partes()
            d.partes_tiene.setCurrentIndex(1)
            d.partes_periodo.setCurrentIndex(d.partes_periodo.findData("ultimos"))
            d.partes_dias.setValue(30)

            assert "Especie es uno de Tilia platyphyllos" in d.frase.text()
            assert "sin ningún parte de Parte de poda en los últimos 30 días" in d.frase.text()

            d.aplicar()
            filtro = capa.dataProvider().layer_uri.filtro
            assert filtro == {"todas": True, "condiciones": [
                {"campo": "especie", "op": "es_uno_de", "valor": ["Tilia platyphyllos"]},
                {"partes": "parte_poda", "tiene": False, "todas": True, "ultimo": False, "condiciones": [],
                 "periodo": {"ultimos_dias": 30}},
            ]}
            assert capa.isValid()

            # Al volver a abrirlo, se ven y se pueden quitar todas.
            d = CondicionesDialog(capa)
            assert d.vista.topLevelItemCount() == 2
            for _ in range(2):
                d.vista.setCurrentItem(d.vista.topLevelItem(0))
                d.quitar()
            d.aplicar()
            assert capa.dataProvider().layer_uri.filtro is None
        finally:
            QgsProject.instance().clear()
            connections.remove_connection("Constructor")


def test_el_menu_solo_abre_el_dialogo_si_el_servidor_lo_entiende(app, monkeypatch):
    from qgis.core import QgsProject
    from qgis.PyQt.QtWidgets import QApplication, QMenu

    from geosian.gui import condiciones_combinadas as C
    from geosian.provider.metadata import register_provider
    from tests.test_gui import _capa_de_prueba

    abiertos, avisos = [], []
    monkeypatch.setattr(C.CondicionesDialog, "exec", lambda self: abiertos.append(self.capa.id()) or 0)
    monkeypatch.setattr(C.QMessageBox, "information", lambda *a, **k: avisos.append(a[2]))
    register_provider()
    with FakeGeosian() as fake:
        try:
            capa = _capa_de_prueba(fake, "Menú")
            for admite in (True, False):
                _ADMITE_FILTRO.clear()
                fake._server.admite_filtro = admite
                menu = QMenu()
                C.menu_de_condiciones(menu, capa)
                [accion] = menu.actions()
                assert accion.text() == "Condiciones combinadas…"
                antes = len(abiertos)
                accion.trigger()
                assert len(abiertos) == antes  # nada dentro de la acción del menú
                QApplication.processEvents()
            assert abiertos == [capa.id()]
            assert avisos and "todavía no admite" in avisos[0]
        finally:
            QgsProject.instance().clear()
            connections.remove_connection("Menú")
