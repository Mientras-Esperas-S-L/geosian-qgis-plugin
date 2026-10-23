"""«Subir capas de QGIS a este mapa…»: varias capas del proyecto de una vez."""

import pytest

qgis_core = pytest.importorskip("qgis.core")

from qgis.core import QgsFeature, QgsGeometry, QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import Qt

from geosian.core import importar_grande as I
from geosian.gui import subir_capas as SC
from tests.test_edicion_atributos import CONEXION, servidor  # noqa: F401
from tests.test_importar_grande import _Dock, _esperar, origen_con

MAPA = {"id": 4, "name": "Ciudad de Ejemplo"}


@pytest.fixture
def proyecto():
    capas = []

    def poner(capa):
        QgsProject.instance().addMapLayer(capa)
        capas.append(capa)
        return capa

    yield poner
    for capa in capas:
        QgsProject.instance().removeMapLayer(capa.id())


def lineas():
    capa = QgsVectorLayer("LineString?crs=EPSG:4326&field=tramo:string", "Tramos", "memory")
    f = QgsFeature(capa.fields())
    f.setGeometry(QgsGeometry.fromWkt("LINESTRING(-3.70 40.41, -3.69 40.42)"))
    f["tramo"] = "T1"
    capa.dataProvider().addFeatures([f])
    return capa


def rota():
    capa = QgsVectorLayer("Polygon?crs=EPSG:4326&field=n:string", "Zonas rotas", "memory")
    f = QgsFeature(capa.fields())
    f.setGeometry(QgsGeometry.fromWkt("POLYGON((0 0, 1 1, 1 0, 0 1, 0 0))"))
    capa.dataProvider().addFeatures([f])
    return capa


class TestVentana:
    def test_lista_las_capas_con_lo_que_se_va_a_crear(self, app_gui, proyecto):
        proyecto(origen_con(3))
        proyecto(lineas())
        proyecto(QgsVectorLayer("None?field=x:string", "Solo tabla", "memory"))

        d = SC.SubirCapasDialog(MAPA)

        filas = {d.tabla.item(i, SC.COL_CAPA).text(): i for i in range(d.tabla.rowCount())}
        assert set(filas) == {"origen", "Tramos", "Solo tabla"}
        assert d.tabla.item(filas["Tramos"], SC.COL_GEOMETRIA).text() == "MultiLineString"
        assert d.tabla.item(filas["origen"], SC.COL_ELEMENTOS).text() == "3"
        tabla = d.tabla.item(filas["Solo tabla"], SC.COL_CAPA)
        assert tabla.checkState() == Qt.CheckState.Unchecked and "no se puede subir" in d.tabla.item(filas["Solo tabla"], SC.COL_AVISO).text()

        d.tabla.item(filas["Tramos"], SC.COL_NOMBRE).setText("Tramos 2027")
        d._aceptar()

        assert sorted(datos["name"] for _, datos, _ in d.elegidas) == ["Tramos 2027", "origen"]

    def test_nombres_repetidos_o_vacios_no_pasan(self, app_gui, proyecto):
        proyecto(origen_con(3))
        proyecto(lineas())
        d = SC.SubirCapasDialog(MAPA)
        for fila in range(d.tabla.rowCount()):
            d.tabla.item(fila, SC.COL_NOMBRE).setText("Igual")

        d._aceptar()

        assert d.elegidas == [] and "dos capas" in d.estado.text()
        d.tabla.item(0, SC.COL_NOMBRE).setText("  ")
        d._aceptar()
        assert "Ponle nombre" in d.estado.text()

    def test_un_nombre_que_ya_tiene_el_mapa_se_ve_antes_de_subir(self, app_gui, servidor, proyecto):  # noqa: F811
        from geosian.core import connections

        proyecto(QgsVectorLayer("Point?crs=EPSG:4326&field=n:string", "Arbolado", "memory"))
        d = SC.SubirCapasDialog(MAPA, cliente=connections.client_for(CONEXION))

        assert "Ya hay una capa con este nombre" in d.tabla.item(0, SC.COL_AVISO).text()
        d._aceptar()
        assert d.elegidas == [] and d.estado.text() == "Ya hay una capa «Arbolado» en este mapa. Elige otro nombre."
        d.tabla.item(0, SC.COL_NOMBRE).setText("Arbolado de QGIS")
        d._aceptar()
        assert [datos["name"] for _, datos, _ in d.elegidas] == ["Arbolado de QGIS"]

    def test_sin_marcar_ninguna(self, app_gui, proyecto):
        proyecto(origen_con(3))
        d = SC.SubirCapasDialog(MAPA)
        d.tabla.item(0, SC.COL_CAPA).setCheckState(Qt.CheckState.Unchecked)

        d._aceptar()

        assert d.elegidas == [] and "al menos una" in d.estado.text()


class TestSubida:
    def test_todas_una_detras_de_otra(self, app_gui, servidor, proyecto, monkeypatch):  # noqa: F811
        monkeypatch.setattr(I, "esperar", _esperar)
        proyecto(origen_con(3))
        proyecto(lineas())
        d = SC.SubirCapasDialog(MAPA)
        d._aceptar()
        dock = _Dock()
        tarea = SC.ImportarCapas(dock, CONEXION, MAPA, d.elegidas)

        ok = tarea.run()
        tarea.finished(ok)

        assert ok
        assert sorted(c["name"] for c in dock.añadidas) == ["Tramos", "origen"]
        assert dock.barra.avisos[-1] == ("pushSuccess", "Subidas las 2 capas a «Ciudad de Ejemplo».")
        confirmadas = [r for r in servidor.rutas_pedidas() if r.endswith("/confirmar/") and "/importar/" in r]
        assert len(confirmadas) == 2

    def test_si_una_falla_las_demas_suben_y_lo_dice(self, app_gui, servidor, proyecto, monkeypatch):  # noqa: F811
        monkeypatch.setattr(I, "esperar", _esperar)
        proyecto(origen_con(3))
        proyecto(rota())
        d = SC.SubirCapasDialog(MAPA)
        d._aceptar()
        dock = _Dock()
        tarea = SC.ImportarCapas(dock, CONEXION, MAPA, d.elegidas)

        ok = tarea.run()
        tarea.finished(ok)

        assert not ok
        assert [c["name"] for c in dock.añadidas] == ["origen"]
        nivel, texto = dock.barra.avisos[-1]
        assert nivel == "pushWarning" and texto.startswith("Subidas 1 de 2 capas.")
        assert "«Zonas rotas»" in texto and "geometría rota" in texto


class TestCapasRaras:
    def test_una_capa_sin_elementos_se_crea_vacia_y_no_tumba_las_demas(self, app_gui, servidor, proyecto, monkeypatch):  # noqa: F811
        monkeypatch.setattr(I, "esperar", _esperar)
        vacia = proyecto(QgsVectorLayer("Point?crs=EPSG:4326&field=n:string", "Vacía", "memory"))
        proyecto(origen_con(3))
        d = SC.SubirCapasDialog(MAPA)
        d._aceptar()
        dock = _Dock()
        tarea = SC.ImportarCapas(dock, CONEXION, MAPA, d.elegidas)

        ok = tarea.run()
        tarea.finished(ok)

        assert ok, tarea.resultados
        assert sorted(c["name"] for c in dock.añadidas) == ["Vacía", "origen"]
        assert vacia.featureCount() == 0

    def test_un_fallo_inesperado_en_una_capa_lo_dice_y_sigue(self, app_gui, servidor, proyecto, monkeypatch):  # noqa: F811
        monkeypatch.setattr(I, "esperar", _esperar)
        proyecto(origen_con(3))
        proyecto(lineas())
        d = SC.SubirCapasDialog(MAPA)
        d._aceptar()
        original = I.empaquetar

        def falla_con_lineas(origen, campos, correspondencia, tipo, *args, **kwargs):
            if tipo == "MultiLineString":
                raise RuntimeError("algo raro")
            return original(origen, campos, correspondencia, tipo, *args, **kwargs)

        monkeypatch.setattr(I, "empaquetar", falla_con_lineas)
        dock = _Dock()
        tarea = SC.ImportarCapas(dock, CONEXION, MAPA, d.elegidas)

        ok = tarea.run()
        tarea.finished(ok)

        assert not ok and [c["name"] for c in dock.añadidas] == ["origen"]
        nivel, texto = dock.barra.avisos[-1]
        assert nivel == "pushWarning" and "«Tramos»: fallo inesperado (RuntimeError: algo raro)" in texto


def test_con_una_sola_capa_el_aviso_habla_en_singular(app_gui, servidor, proyecto, monkeypatch):  # noqa: F811
    monkeypatch.setattr(I, "esperar", _esperar)
    proyecto(origen_con(3))
    d = SC.SubirCapasDialog(MAPA)
    d._aceptar()
    dock = _Dock()
    tarea = SC.ImportarCapas(dock, CONEXION, MAPA, d.elegidas)

    tarea.finished(tarea.run())

    assert dock.barra.avisos[-1] == ("pushSuccess", "Subida «origen» a «Ciudad de Ejemplo».")


def test_al_acabar_el_mapa_del_panel_ensena_las_capas_nuevas(app_gui, servidor, proyecto, monkeypatch):  # noqa: F811
    from geosian.gui.browser_dock import GeosianBrowserDock
    from tests.test_gui import IfaceFalso

    monkeypatch.setattr(I, "esperar", _esperar)
    panel = GeosianBrowserDock(IfaceFalso())
    raiz = next(panel.arbol.topLevelItem(i) for i in range(panel.arbol.topLevelItemCount())
                if panel.arbol.topLevelItem(i).text(0) == CONEXION)
    raiz.setExpanded(True)
    mapa = raiz.child(0).child(0)
    mapa.setExpanded(True)
    antes = [mapa.child(i).text(0) for i in range(mapa.childCount())]
    proyecto(origen_con(3))
    d = SC.SubirCapasDialog(MAPA)
    d._aceptar()
    dock = _Dock()
    dock.refrescar_mapa = panel.refrescar_mapa
    tarea = SC.ImportarCapas(dock, CONEXION, MAPA, d.elegidas)

    tarea.finished(tarea.run())

    despues = [mapa.child(i).text(0) for i in range(mapa.childCount())]
    assert "origen" not in antes and "origen" in despues


def test_con_otra_subida_en_marcha_espera_su_turno(app_gui, servidor, proyecto, monkeypatch):  # noqa: F811
    from geosian.gui import crear_capa as G

    monkeypatch.setattr(I, "esperar", _esperar)
    proyecto(origen_con(3))
    d = SC.SubirCapasDialog(MAPA)
    d._aceptar()
    tarea = SC.ImportarCapas(_Dock(), CONEXION, MAPA, d.elegidas)
    assert G._UNA_A_LA_VEZ.acquire(blocking=False)
    try:
        tarea.cancel()

        assert tarea.run() is False
    finally:
        G._UNA_A_LA_VEZ.release()
    # Mientras esperaba no ha empaquetado ni pedido nada.
    assert tarea.resultados == [] and not [r for r in servidor.rutas_pedidas() if "/importar/" in r]


def test_si_no_se_pueden_abrir_al_final_lo_dice_y_avisa_igual(app_gui, servidor, proyecto, monkeypatch):  # noqa: F811
    monkeypatch.setattr(I, "esperar", _esperar)
    proyecto(origen_con(3))
    d = SC.SubirCapasDialog(MAPA)
    d._aceptar()

    class DockQueFalla(_Dock):
        def añadir_capa(self, datos):
            raise RuntimeError("sin red")

    dock = DockQueFalla()
    tarea = SC.ImportarCapas(dock, CONEXION, MAPA, d.elegidas)

    tarea.finished(tarea.run())

    niveles = [nivel for nivel, _ in dock.barra.avisos]
    assert niveles == ["pushWarning", "pushSuccess"]
    assert "no se han podido abrir en QGIS" in dock.barra.avisos[0][1]
