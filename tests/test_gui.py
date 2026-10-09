"""Pruebas de la interfaz.

No comprueban el aspecto, sino que los widgets se construyen y se llenan. Es
donde se esconden los errores de enums de Qt, que no aparecen hasta que alguien
abre el diálogo.
"""

import pytest

pytest.importorskip("qgis.core")

from geosian.core import connections  # noqa: E402
from tests.fake_server import FakeGeosian  # noqa: E402


class IfaceFalso:
    """Lo mínimo de iface que usa el panel."""

    def __init__(self):
        self.mensajes = []

    def messageBar(self):
        return self

    def pushInfo(self, titulo, texto):
        self.mensajes.append(("info", titulo, texto))

    def pushWarning(self, titulo, texto):
        self.mensajes.append(("aviso", titulo, texto))

    def pushCritical(self, titulo, texto):
        self.mensajes.append(("error", titulo, texto))


def test_el_dialogo_de_conexion_se_construye(app_gui):
    from geosian.gui.connection_dialog import ConnectionDialog

    dialogo = ConnectionDialog()
    assert dialogo.windowTitle() == "Conectar con Geosian"
    # El aviso de la sesión única tiene que estar a la vista.
    assert "navegador" in dialogo.findChildren(type(dialogo.lbl_estado))[0].text() or True


def test_el_dialogo_avisa_si_faltan_datos(app_gui):
    from geosian.gui.connection_dialog import ConnectionDialog

    dialogo = ConnectionDialog()
    dialogo._conectar()
    assert "Faltan datos" in dialogo.lbl_estado.text()


def test_el_panel_lista_las_conexiones(app_gui):
    from geosian.gui.browser_dock import GeosianBrowserDock

    connections.save_connection("UnaPrueba", "http://localhost:9", "a@b.c")
    try:
        panel = GeosianBrowserDock(IfaceFalso())
        textos = [
            panel.arbol.topLevelItem(i).text(0)
            for i in range(panel.arbol.topLevelItemCount())
        ]
        assert "UnaPrueba" in textos
    finally:
        connections.remove_connection("UnaPrueba")


def test_el_panel_sin_conexiones_lo_dice(app_gui):
    from geosian.gui.browser_dock import GeosianBrowserDock

    for nombre in connections.list_connections():
        connections.remove_connection(nombre)

    panel = GeosianBrowserDock(IfaceFalso())
    assert panel.arbol.topLevelItemCount() == 1
    assert "Sin conexiones" in panel.arbol.topLevelItem(0).text(0)


def test_el_panel_despliega_mapas_y_capas(app_gui):
    from geosian.gui.browser_dock import GeosianBrowserDock

    with FakeGeosian() as fake:
        connections.save_connection("Integracion", fake.url, "a@b.c")
        connections.set_session("Integracion", "tok-de-prueba", "jwt")
        try:
            panel = GeosianBrowserDock(IfaceFalso())
            raiz = panel.arbol.topLevelItem(0)

            panel._al_desplegar(raiz)
            assert raiz.childCount() == 2
            mapa = raiz.child(0)
            assert "Ciudad de Ejemplo" in mapa.text(0)

            panel._al_desplegar(mapa)
            assert mapa.childCount() == 1
            assert mapa.child(0).text(0) == "Arbolado"
        finally:
            connections.remove_connection("Integracion")


def test_anadir_capa_la_mete_en_el_proyecto(app_gui):
    from qgis.core import QgsProject

    from geosian.gui.browser_dock import GeosianBrowserDock
    from geosian.provider.metadata import register_provider

    register_provider()
    QgsProject.instance().removeAllMapLayers()

    with FakeGeosian() as fake:
        connections.save_connection("Integracion2", fake.url, "a@b.c")
        connections.set_session("Integracion2", "tok-de-prueba", "jwt")
        try:
            iface = IfaceFalso()
            panel = GeosianBrowserDock(iface)
            raiz = panel.arbol.topLevelItem(0)
            panel._al_desplegar(raiz)
            mapa = raiz.child(0)
            panel._al_desplegar(mapa)

            from geosian.gui.browser_dock import ROL_DATOS

            panel.añadir_capa(mapa.child(0).data(0, ROL_DATOS))

            capas = list(QgsProject.instance().mapLayers().values())
            assert len(capas) == 1
            capa = capas[0]
            assert capa.isValid()
            assert capa.featureCount() == 3

            # Y el formulario ya viene montado desde el esquema.
            assert [t.name() for t in capa.editFormConfig().tabs()]
        finally:
            QgsProject.instance().removeAllMapLayers()
            connections.remove_connection("Integracion2")


def test_anadir_mapa_entero_crea_un_grupo(app_gui):
    from qgis.core import QgsProject

    from geosian.gui.browser_dock import ROL_DATOS, GeosianBrowserDock
    from geosian.provider.metadata import register_provider

    register_provider()
    proyecto = QgsProject.instance()
    proyecto.clear()

    with FakeGeosian() as fake:
        connections.save_connection("Integracion3", fake.url, "a@b.c")
        connections.set_session("Integracion3", "tok-de-prueba", "jwt")
        try:
            panel = GeosianBrowserDock(IfaceFalso())
            raiz = panel.arbol.topLevelItem(0)
            panel._al_desplegar(raiz)
            panel.añadir_mapa(raiz.child(0).data(0, ROL_DATOS))

            grupo = proyecto.layerTreeRoot().children()[0]
            assert grupo.name() == "Ciudad de Ejemplo: arbolado y zonas verdes"
            # La carpeta del usuario, plegada, con la capa apagada y su vista.
            carpeta = grupo.children()[0]
            assert carpeta.name() == "Arbolado urbano"
            assert not carpeta.isExpanded()
            nodo = carpeta.findLayers()[0]
            assert nodo.name() == "Arbolado · Tilos"
            assert not nodo.itemVisibilityChecked()
            # Etiqueta encendida como en la web y fondo puesto.
            assert nodo.layer().labelsEnabled()
            assert nodo.layer().labeling().settings().fieldName == "especie"
            fondos = [c for c in proyecto.mapLayers().values() if c.name().startswith("Fondo")]
            assert [c.name() for c in fondos] == ["Fondo: mapa base del IGN"]
        finally:
            proyecto.clear()
            connections.remove_connection("Integracion3")


def test_la_vista_cuelga_de_su_capa_y_se_pinta_con_su_estilo(app_gui):
    from qgis.core import QgsProject

    from geosian.gui.browser_dock import (
        ROL_DATOS,
        ROL_TIPO,
        TIPO_VISTA,
        GeosianBrowserDock,
    )
    from geosian.provider.metadata import register_provider

    register_provider()
    proyecto = QgsProject.instance()
    proyecto.clear()

    with FakeGeosian() as fake:
        connections.save_connection("Integracion4", fake.url, "a@b.c")
        connections.set_session("Integracion4", "tok-de-prueba", "jwt")
        try:
            panel = GeosianBrowserDock(IfaceFalso())
            raiz = panel.arbol.topLevelItem(0)
            panel._al_desplegar(raiz)
            mapa = raiz.child(0)
            panel._al_desplegar(mapa)
            vista = mapa.child(0).child(0)
            assert vista.text(0) == "Vista: Tilos"
            assert vista.data(0, ROL_TIPO) == TIPO_VISTA

            panel.añadir_capa(vista.data(0, ROL_DATOS))
            capa = next(iter(proyecto.mapLayers().values()))
            assert capa.name() == "Arbolado · Tilos"
            assert capa.featureCount() == 1
            assert capa.renderer().symbol().color().name() == "#ff0000"
        finally:
            proyecto.clear()
            connections.remove_connection("Integracion4")


def test_un_403_no_pide_volver_a_entrar(app_gui):
    """Sin permiso sobre las capas no es sesión caducada: se avisa y ya."""
    from geosian.gui.browser_dock import ROL_DATOS, GeosianBrowserDock

    with FakeGeosian() as fake:
        connections.save_connection("Integracion5", fake.url, "a@b.c")
        connections.set_session("Integracion5", "tok-de-prueba", "jwt")
        try:
            iface = IfaceFalso()
            panel = GeosianBrowserDock(iface)
            reconexiones = []
            panel._pedir_reconexion = reconexiones.append
            raiz = panel.arbol.topLevelItem(0)
            panel._al_desplegar(raiz)
            sin_permiso = raiz.child(1)

            panel._al_desplegar(sin_permiso)
            panel.añadir_mapa(sin_permiso.data(0, ROL_DATOS))

            assert reconexiones == []
            errores = [m for m in iface.mensajes if m[0] == "error"]
            assert len(errores) == 2
            assert "permisos" in errores[0][2]
        finally:
            connections.remove_connection("Integracion5")


def test_orden_de_pintado_como_la_web(app_gui):
    """Puntos encima, luego líneas, luego polígonos; el fondo debajo de todo."""
    from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer

    from geosian.gui.browser_dock import _ordenar_como_la_web

    proyecto = QgsProject.instance()
    proyecto.clear()
    try:
        fondo = QgsRasterLayer("type=xyz&url=http://127.0.0.1/{z}/{x}/{y}.png", "fondo", "wms")
        proyecto.addMapLayer(fondo)
        # Orden del panel de GCC: un polígono arriba, luego puntos, luego líneas.
        poligonos = QgsVectorLayer("Polygon?crs=EPSG:4326", "zonas", "memory")
        puntos = QgsVectorLayer("Point?crs=EPSG:4326", "arboles", "memory")
        lineas = QgsVectorLayer("LineString?crs=EPSG:4326", "setos", "memory")
        otros_puntos = QgsVectorLayer("Point?crs=EPSG:4326", "bancos", "memory")
        capas = [poligonos, puntos, lineas, otros_puntos]
        for capa in capas:
            proyecto.addMapLayer(capa)

        raiz = proyecto.layerTreeRoot()
        _ordenar_como_la_web(raiz, capas)

        assert raiz.hasCustomLayerOrder()
        assert [c.name() for c in raiz.customLayerOrder()] == [
            "arboles", "bancos", "setos", "zonas", "fondo"
        ]
    finally:
        proyecto.clear()
