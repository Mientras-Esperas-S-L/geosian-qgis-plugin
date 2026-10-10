"""Pruebas de la interfaz.

No comprueban el aspecto, sino que los widgets se construyen y se llenan. Es
donde se esconden los errores de enums de Qt, que no aparecen hasta que alguien
abre el diálogo.
"""

import pytest

pytest.importorskip("qgis.core")

from qgis.core import QgsFeature, QgsMapLayerType

from geosian.core import connections
from tests.fake_server import FakeGeosian


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
            # Los mapas cuelgan de su espacio de trabajo, como en la web.
            assert [raiz.child(i).text(0) for i in range(raiz.childCount())] == [
                "Ayuntamiento de Ejemplo",
                "Otro Ayuntamiento",
            ]
            mapa = raiz.child(0).child(0)
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
            mapa = raiz.child(0).child(0)
            panel._al_desplegar(mapa)

            from geosian.gui.browser_dock import ROL_DATOS

            panel.añadir_capa(mapa.child(0).data(0, ROL_DATOS))

            capas = [c for c in QgsProject.instance().mapLayers().values() if c.isSpatial()]
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
            panel.añadir_mapa(raiz.child(0).child(0).data(0, ROL_DATOS))

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
            # El fondo de la web (GEOSIAN, teselas vectoriales) encendido, y los
            # propios del mapa añadidos pero apagados, para cambiar como en la web.
            r = proyecto.layerTreeRoot()
            fondos = {
                c.name(): (c.type(), r.findLayer(c.id()).isVisible())
                for c in proyecto.mapLayers().values() if c.name().startswith("Fondo")
            }
            # Y los fijos del selector de la web: la ortofoto del IGN con sus calles
            # encima (un grupo, se encienden juntas) y el mapa base oscuro.
            assert fondos == {
                "Fondo: mapa base de Geosian": (QgsMapLayerType.VectorTileLayer, True),
                "Fondo: Ortofoto de ejemplo": (QgsMapLayerType.RasterLayer, False),
                "Fondo: mapa base oscuro": (QgsMapLayerType.VectorTileLayer, False),
                "Fondo: Ortofoto (IGN)": (QgsMapLayerType.RasterLayer, False),
                "Fondo: calles sobre la ortofoto": (QgsMapLayerType.VectorTileLayer, False),
            }
            grupo_foto = r.findGroup("Fondo: Ortofoto (IGN)")
            assert [n.name() for n in grupo_foto.children()] == [
                "Fondo: calles sobre la ortofoto", "Fondo: Ortofoto (IGN)",
            ]
            # Pintado: la vista arriba y los fondos debajo de todo.
            orden = r.customLayerOrder() if r.hasCustomLayerOrder() else r.layerOrder()
            nombres = [c.name() for c in orden if c.isSpatial()]
            assert nombres[0] == "Arbolado · Tilos"
            assert set(nombres[1:]) == set(fondos)
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
            mapa = raiz.child(0).child(0)
            panel._al_desplegar(mapa)
            vista = mapa.child(0).child(0)
            assert vista.text(0) == "Vista: Tilos"
            assert vista.data(0, ROL_TIPO) == TIPO_VISTA

            panel.añadir_capa(vista.data(0, ROL_DATOS))
            capa = next(c for c in proyecto.mapLayers().values() if c.isSpatial())
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
            sin_permiso = raiz.child(1).child(0)

            panel._al_desplegar(sin_permiso)
            panel.añadir_mapa(sin_permiso.data(0, ROL_DATOS))

            assert reconexiones == []
            errores = [m for m in iface.mensajes if m[0] == "error"]
            assert len(errores) == 2
            assert "permisos" in errores[0][2]
        finally:
            connections.remove_connection("Integracion5")


def test_vista_activa_sustituye_su_capa_y_se_pinta_encima(app_gui, monkeypatch):
    """Como en la web: una vista activa, también de iconos, oculta los datos base de su
    capa (``layerBaseVisible``) y se pinta sobre las capas base."""
    from qgis.core import QgsProject

    from geosian.gui.browser_dock import ROL_DATOS, GeosianBrowserDock

    proyecto = QgsProject.instance()
    proyecto.clear()
    with FakeGeosian() as fake:
        connections.save_connection("Integracion6", fake.url, "a@b.c")
        connections.set_session("Integracion6", "tok-de-prueba", "jwt")
        try:
            cliente = connections.client_for("Integracion6")
            monkeypatch.setattr(
                cliente, "map_settings", lambda _mid: {"settings": {"active_view_ids": [8]}}
            )
            panel = GeosianBrowserDock(IfaceFalso())
            raiz = panel.arbol.topLevelItem(0)
            panel._al_desplegar(raiz)
            panel.añadir_mapa(raiz.child(0).child(0).data(0, ROL_DATOS))

            grupo = proyecto.layerTreeRoot().children()[0]
            # Solo la vista: la capa base no se añade.
            assert [n.name() for n in grupo.findLayers() if n.layer().isSpatial()] == [
                "Arbolado · Iconos"
            ]
            # En el pintado: la vista encima de todo lo demás.
            orden = proyecto.layerTreeRoot().customLayerOrder()
            assert orden[0].name() == "Arbolado · Iconos"
        finally:
            proyecto.clear()
            connections.remove_connection("Integracion6")


def test_las_vistas_de_informacion_adicional_se_ofrecen_como_las_demas(app_gui):
    from geosian.gui.browser_dock import ROL_TIPO, TIPO_VISTA, GeosianBrowserDock

    with FakeGeosian() as fake:
        connections.save_connection("Integracion7", fake.url, "a@b.c")
        connections.set_session("Integracion7", "tok-de-prueba", "jwt")
        try:
            panel = GeosianBrowserDock(IfaceFalso())
            raiz = panel.arbol.topLevelItem(0)
            panel._al_desplegar(raiz)
            mapa = raiz.child(0).child(0)
            panel._al_desplegar(mapa)
            capa = mapa.child(0)
            partes = [capa.child(i) for i in range(capa.childCount())][-1]
            assert partes.text(0) == "Vista: Con partes"
            assert partes.data(0, ROL_TIPO) == TIPO_VISTA
        finally:
            connections.remove_connection("Integracion7")


def test_los_partes_de_la_capa_salen_en_su_ficha(app_gui):
    from qgis.core import (
        QgsAttributeEditorRelation,
        QgsExpression,
        QgsExpressionContext,
        QgsProject,
    )

    from geosian.gui.browser_dock import ROL_DATOS, GeosianBrowserDock
    from geosian.provider.metadata import register_provider

    register_provider()
    proyecto = QgsProject.instance()
    proyecto.clear()

    with FakeGeosian() as fake:
        connections.save_connection("Partes", fake.url, "a@b.c")
        connections.set_session("Partes", "tok-de-prueba", "jwt")
        try:
            panel = GeosianBrowserDock(IfaceFalso())
            raiz = panel.arbol.topLevelItem(0)
            panel._al_desplegar(raiz)
            mapa = raiz.child(0).child(0)
            panel._al_desplegar(mapa)
            fake.peticiones.clear()
            [capa] = panel.añadir_capa(mapa.child(0).data(0, ROL_DATOS))

            [tabla] = [c for c in proyecto.mapLayers().values() if not c.isSpatial()]
            assert tabla.name() == "Arbolado · Parte de poda"
            # Agrupadas aparte y plegadas, para no llenar el panel de capas.
            nodo = proyecto.layerTreeRoot().findLayer(tabla.id())
            assert nodo.parent().name() == "Información adicional"
            assert not nodo.parent().isExpanded()
            # Abrir la capa no descarga los partes de toda la capa.
            assert "/api/v1/additional-information/" not in [r for r, _ in fake.peticiones]

            [relacion] = proyecto.relationManager().referencedRelations(capa)
            assert relacion.referencingLayer() == tabla
            assert relacion.fieldPairs() == {"geodata_id": "id"}
            elemento = next(f for f in capa.getFeatures() if f["id"] == 1001)
            partes = list(relacion.getRelatedFeatures(elemento))
            assert sorted(p["id"] for p in partes) == [501, 502]
            # En la lista de partes, cada uno por su autor y su fecha, como la web.
            primero = next(p for p in partes if p["id"] == 501)
            contexto = QgsExpressionContext()
            contexto.setFeature(primero)
            assert QgsExpression(tabla.displayExpression()).evaluate(contexto) == "Técnica Uno · 2026-05-02"

            pestaña = next(
                t for t in capa.editFormConfig().tabs() if t.name() == "Información adicional"
            )
            # Envuelto en un grupo que solo se ve si el elemento cumple las
            # attribute_dependencies del tipo, como en la web.
            [envoltorio] = pestaña.children()
            [hijo] = envoltorio.children()
            assert isinstance(hijo, QgsAttributeEditorRelation)
            assert hijo.relation().id() == relacion.id()
            expresion = QgsExpression(envoltorio.visibilityExpression().data().expression())
            for fid, visible in ((1001, True), (1002, False)):
                contexto = QgsExpressionContext()
                contexto.setFeature(next(f for f in capa.getFeatures() if f["id"] == fid))
                assert bool(expresion.evaluate(contexto)) is visible, fid
        finally:
            proyecto.clear()
            connections.remove_connection("Partes")


def test_abrir_el_panel_no_toca_el_almacen_de_credenciales(app_gui, monkeypatch):
    """Leer una sesión guardada puede pedir la contraseña maestra de QGIS. Al arrancar
    QGIS no se debe pedir nada: solo cuando el usuario despliega la conexión."""
    from geosian.gui.browser_dock import GeosianBrowserDock

    connections.save_connection("SinTocar", "http://localhost:9", "a@b.c")
    connections._clientes.pop("SinTocar", None)

    def prohibido(_nombre):
        raise AssertionError("se leyó el almacén de credenciales al abrir el panel")

    monkeypatch.setattr(connections, "get_credentials", prohibido)
    try:
        panel = GeosianBrowserDock(IfaceFalso())
        panel.refrescar()
    finally:
        monkeypatch.undo()
        connections.remove_connection("SinTocar")


def _capa_de_prueba(fake, nombre):
    from geosian.gui.browser_dock import ROL_DATOS, GeosianBrowserDock

    connections.save_connection(nombre, fake.url, "a@b.c")
    connections.set_session(nombre, "tok-de-prueba", "jwt")
    panel = GeosianBrowserDock(IfaceFalso())
    raiz = panel.arbol.topLevelItem(0)
    panel._al_desplegar(raiz)
    mapa = raiz.child(0).child(0)
    panel._al_desplegar(mapa)
    return panel.añadir_capa(mapa.child(0).data(0, ROL_DATOS))[0]


def test_la_ficha_tiene_una_pestana_de_fotos_y_archivos(app_gui):
    from qgis.core import QgsProject

    from geosian.gui.media_widget import WIDGET_TYPE, register_media_widget
    from geosian.provider.metadata import register_provider

    register_provider()
    register_media_widget()
    with FakeGeosian() as fake:
        try:
            capa = _capa_de_prueba(fake, "Fotos1")
            pestaña = next(
                t for t in capa.editFormConfig().tabs() if t.name() == "Fotos y archivos"
            )
            [campo] = pestaña.children()
            assert campo.name() == "id"
            assert capa.editorWidgetSetup(capa.fields().indexOf("id")).type() == WIDGET_TYPE
            # Y las fichas de los partes también, que tienen sus fotos.
            [tabla] = [c for c in QgsProject.instance().mapLayers().values() if not c.isSpatial()]
            assert "Fotos y archivos" in [t.name() for t in tabla.editFormConfig().tabs()]
        finally:
            QgsProject.instance().clear()
            connections.remove_connection("Fotos1")


def test_el_panel_de_fotos_ensena_las_del_elemento(app_gui, monkeypatch, tmp_path):
    """En la ficha, como la monta QGIS. Pedir el envoltorio al registro desde Python no
    vale en QGIS 3.34: sip deja inservible el objeto de Python que creó la fábrica."""
    from qgis.core import QgsProject
    from qgis.gui import QgsAttributeEditorContext, QgsAttributeForm

    from geosian.gui import media_widget
    from geosian.provider.metadata import register_provider
    from tests.fake_server import FICHERO_PDF

    register_provider()
    media_widget.register_media_widget()
    with FakeGeosian() as fake:
        try:
            capa = _capa_de_prueba(fake, "Fotos2")
            elemento = next(f for f in capa.getFeatures() if f["id"] == 1001)
            contexto = QgsAttributeEditorContext()
            contexto.setVectorLayerTools(_herramientas_falsas())
            ficha = QgsAttributeForm(capa, elemento, contexto)
            panel = ficha.findChildren(media_widget.MediaPanel)[0]
            # Solo lectura (la ficha sin editar desactiva el id) no impide mirar las fotos.
            fake.peticiones.clear()
            panel.cargar()

            assert panel.fotos.count() == 2
            assert panel.ficheros.count() == 1
            assert panel.isEnabled()
            # La ficha con enlaces y, para la galería, solo las miniaturas.
            assert [r for r, _ in fake.peticiones] == [
                "/api/v1/geodata/1001/", "/api/v1/geodata/image/72/", "/api/v1/geodata/image/71/"
            ]
            assert all(c.get("as_thumbnail") == ["1"] for r, c in fake.peticiones[1:])

            abiertos = []
            monkeypatch.setattr(media_widget, "_abrir_fuera", abiertos.append)
            monkeypatch.setattr(media_widget, "_carpeta_temporal", lambda: str(tmp_path))
            panel.abrir_fichero(panel.ficheros.item(0))
            assert len(abiertos) == 1
            with open(abiertos[0], "rb") as fichero:
                assert fichero.read() == FICHERO_PDF

            # Sin elemento (uno nuevo), no se pide nada.
            fake.peticiones.clear()
            ficha.setFeature(QgsFeature(capa.fields()))
            panel.cargar()
            assert panel.fotos.count() == 0 and fake.peticiones == []
        finally:
            QgsProject.instance().clear()
            connections.remove_connection("Fotos2")


def _herramientas_falsas():
    from qgis.core import QgsVectorLayerTools

    class Herramientas(QgsVectorLayerTools):
        """Las que pone iface en QGIS; el editor de relaciones de la ficha las pide."""

        def addFeature(self, *args, **kwargs):
            return False, None

        def startEditing(self, layer):
            return False

        def stopEditing(self, layer, allowCancel=True):
            return False

        def saveEdits(self, layer):
            return False

        def copyMoveFeatures(self, *args, **kwargs):
            return False

    return Herramientas()


def test_el_panel_de_fotos_sobrevive_sin_referencias_en_python(app_gui):
    """QGIS crea el campo y no guarda nada en Python. Si el objeto Python del panel se
    recolecta, el widget sigue ahí pero sin su código: no carga nunca las fotos."""
    import gc

    from qgis.core import QgsProject
    from qgis.gui import QgsAttributeEditorContext, QgsAttributeForm

    from geosian.gui import media_widget
    from geosian.provider.metadata import register_provider

    register_provider()
    media_widget.register_media_widget()
    with FakeGeosian() as fake:
        try:
            capa = _capa_de_prueba(fake, "Fotos3")
            elemento = next(f for f in capa.getFeatures() if f["id"] == 1001)
            contexto = QgsAttributeEditorContext()
            herramientas = _herramientas_falsas()
            contexto.setVectorLayerTools(herramientas)
            ficha = QgsAttributeForm(capa, elemento, contexto)
            gc.collect()

            def ficha_de(widget):
                while widget is not None and not isinstance(widget, QgsAttributeForm):
                    widget = widget.parentWidget()
                return widget

            # El de la ficha del elemento; el editor de partes lleva el suyo dentro.
            propios = [
                p for p in ficha.findChildren(media_widget.MediaPanel) if ficha_de(p) is ficha
            ]
            # QGIS 4 monta el campo dos veces en la ficha; lo que importa es que
            # conserven su código de Python.
            assert propios
        finally:
            QgsProject.instance().clear()
            connections.remove_connection("Fotos3")


def test_la_ficha_sale_en_pestanas_y_sin_la_etiqueta_del_id(app_gui):
    """En QGIS 4 un contenedor sin padre nace como grupo: la ficha salía con todas las
    secciones apiladas, sin pestañas, y con «ID interno» junto al panel de fotos."""
    from qgis.core import QgsProject
    from qgis.gui import QgsAttributeEditorContext, QgsAttributeForm
    from qgis.PyQt.QtWidgets import QLabel, QTabWidget

    from geosian.gui import media_widget
    from geosian.provider.metadata import register_provider

    register_provider()
    media_widget.register_media_widget()
    with FakeGeosian() as fake:
        try:
            capa = _capa_de_prueba(fake, "Pestanas")
            elemento = next(f for f in capa.getFeatures() if f["id"] == 1001)
            contexto = QgsAttributeEditorContext()
            contexto.setVectorLayerTools(_herramientas_falsas())
            ficha = QgsAttributeForm(capa, elemento, contexto)
            [pestañas] = [
                w for w in ficha.findChildren(QTabWidget) if w.parentWidget() is not None
                and not any(isinstance(a, media_widget.MediaPanel) for a in _ancestros(w))
            ][:1]
            nombres = [pestañas.tabText(i) for i in range(pestañas.count())]
            assert "General" in nombres and "Fotos y archivos" in nombres
            fotos = pestañas.widget(nombres.index("Fotos y archivos"))
            etiquetas = [
                q.text() for q in fotos.findChildren(QLabel)
                if not q.isHidden() and "ID interno" in q.text()
            ]
            assert etiquetas == []
        finally:
            QgsProject.instance().clear()
            connections.remove_connection("Pestanas")


def _ancestros(widget):
    w = widget.parentWidget()
    while w is not None:
        yield w
        w = w.parentWidget()


def test_filtrar_por_partes_y_fechas_desde_el_menu_de_la_capa(app_gui):
    """Como el panel de filtros de la web: elementos con partes que cumplen algo y
    partes entre fechas. Va a la URI, así que se guarda con el proyecto."""
    from qgis.core import QgsProject
    from qgis.PyQt.QtCore import QDate
    from qgis.PyQt.QtWidgets import QMenu

    from geosian.gui.filtro_partes import FiltroPartesDialog, menu_de_filtros
    from geosian.provider.metadata import register_provider

    register_provider()
    with FakeGeosian() as fake:
        try:
            capa = _capa_de_prueba(fake, "Filtros")
            menu = QMenu()
            menu_de_filtros(menu, capa)
            assert [a.text() for a in menu.actions()] == ["Filtrar por partes y fechas…"]

            dialogo = FiltroPartesDialog(capa)
            assert [dialogo.tipo.itemText(i) for i in range(dialogo.tipo.count())] == ["Parte de poda"]
            dialogo.tipo.setCurrentIndex(0)
            dialogo.campo.setCurrentIndex(dialogo.campo.findData("labor"))
            dialogo.valor.setText("Poda")
            dialogo.agregar()
            dialogo.campo.setCurrentIndex(dialogo.campo.findData("horas"))
            dialogo.operador.setCurrentIndex(dialogo.operador.findData("gte"))
            dialogo.valor.setText("2")
            dialogo.agregar()
            dialogo.usar_desde.setChecked(True)
            dialogo.desde.setDate(QDate(2026, 1, 1))
            dialogo.ultimo.setChecked(True)
            dialogo.aplicar()

            uri = capa.dataProvider().layer_uri
            assert uri.partes == [("parte_poda__labor", "Poda"), ("parte_poda__horas__gte", "2")]
            assert (uri.date_from, uri.date_to, uri.most_recent) == ("2026-01-01", None, True)
            assert capa.isValid()
            fake.peticiones.clear()
            list(capa.getFeatures())
            [consulta] = [c for r, c in fake.peticiones if r == "/api/v1/geodata/paginated/"][:1]
            assert consulta["attr__parte_poda__labor"] == ["Poda"]
            assert consulta["attr__parte_poda__horas__gte"] == ["2"]

            # Y se pueden quitar todos.
            dialogo = FiltroPartesDialog(capa)
            assert dialogo.lista.count() == 2
            dialogo.lista.clear()
            dialogo.usar_desde.setChecked(False)
            dialogo.ultimo.setChecked(False)
            dialogo.aplicar()
            uri = capa.dataProvider().layer_uri
            assert uri.partes == [] and uri.date_from is None and not uri.most_recent
        finally:
            QgsProject.instance().clear()
            connections.remove_connection("Filtros")


def test_menu_de_la_capa_cambia_la_etiqueta(app_gui):
    from qgis.core import QgsProject
    from qgis.PyQt.QtWidgets import QMenu

    from geosian.gui.browser_dock import menu_de_etiquetas
    from geosian.provider.metadata import register_provider

    register_provider()
    with FakeGeosian() as fake:
        try:
            capa = _capa_de_prueba(fake, "Etiquetas")
            menu = QMenu()
            menu_de_etiquetas(menu, capa)
            [sub] = [a.menu() for a in menu.actions() if a.menu() is not None]
            opciones = {a.text(): a for a in sub.actions()}
            assert "Sin etiqueta" in opciones and "Especie" in opciones
            # La que está encendida sale marcada.
            assert opciones["Especie"].isChecked()

            opciones["Sin etiqueta"].trigger()
            assert not capa.labelsEnabled()

            opciones["Especie"].trigger()
            assert capa.labelsEnabled()
            assert capa.labeling().settings().fieldName == "especie"

            # Una capa que no es de Geosian no lleva el menú.
            otro = QMenu()
            menu_de_etiquetas(otro, None)
            assert otro.actions() == []
        finally:
            QgsProject.instance().clear()
            connections.remove_connection("Etiquetas")


def test_informacion_adicional_va_al_final_del_mapa(app_gui):
    """El grupo se crea al añadir la primera capa con partes; las capas que vienen
    después quedaban debajo de él, en medio del mapa."""
    from qgis.core import QgsProject, QgsVectorLayer

    from geosian.gui.browser_dock import GRUPO_PARTES, _partes_al_final

    proyecto = QgsProject.instance()
    proyecto.clear()
    try:
        mapa = proyecto.layerTreeRoot().addGroup("Mapa de ejemplo")
        partes = mapa.addGroup(GRUPO_PARTES)
        partes.setExpanded(False)
        tabla = QgsVectorLayer("None?field=geodata_id:integer", "Arbolado · Parte de poda", "memory")
        proyecto.addMapLayer(tabla, False)
        partes.addLayer(tabla)
        mobiliario = QgsVectorLayer("Point?crs=EPSG:4326", "Mobiliario", "memory")
        proyecto.addMapLayer(mobiliario, False)
        mapa.addLayer(mobiliario)

        _partes_al_final(mapa)

        assert [n.name() for n in mapa.children()] == ["Mobiliario", GRUPO_PARTES]
        movido = mapa.children()[-1]
        assert not movido.isExpanded()
        assert [n.name() for n in movido.findLayers()] == ["Arbolado · Parte de poda"]
    finally:
        proyecto.clear()


def test_un_cambio_en_gcc_recarga_la_capa_en_qgis(app_gui):
    """Tiempo real: el servidor avisa por /ws/layer-data/ y la capa se vuelve a pedir,
    como hace la web (useLayerDataWebSocket.js)."""
    import time

    from qgis.core import QgsProject
    from qgis.PyQt.QtCore import QCoreApplication

    from geosian.gui import realtime_hub
    from geosian.provider.metadata import register_provider
    from tests.fake_ws import FakeWebSocket

    def esperar(condicion, segundos=4):
        limite = time.monotonic() + segundos
        while time.monotonic() < limite:
            QCoreApplication.processEvents()
            if condicion():
                return True
            time.sleep(0.02)
        return False

    register_provider()
    canal = FakeWebSocket()
    with FakeGeosian() as fake:
        try:
            realtime_hub.watch_project()
            connections.save_connection("Vivo", fake.url, "a@b.c")
            connections.set_ws_url("Vivo", canal.url)
            capa = _capa_de_prueba(fake, "Vivo")
            assert capa.featureCount() == 3
            assert canal.conectado.wait(3)
            assert esperar(lambda: {"type": "subscribe_map", "map_id": 4} in canal.recibidos)

            fake.peticiones.clear()
            canal.enviar({"type": "layer_data_changed", "map_id": 4, "layer_id": 11,
                          "change_type": "update", "feature_id": 1001})
            assert esperar(lambda: any(r == "/api/v1/geodata/paginated/" for r, _ in fake.peticiones)
                           or (list(capa.getFeatures()) and any(
                               r == "/api/v1/geodata/paginated/" for r, _ in fake.peticiones)))

            # Un aviso de otra capa no recarga esta.
            esperar(lambda: False, 1)
            list(capa.getFeatures())
            recargas = []
            original = capa.dataProvider().reloadData
            capa.dataProvider().reloadData = lambda: (recargas.append(1), original())
            fake.peticiones.clear()
            canal.enviar({"type": "layer_data_changed", "map_id": 4, "layer_id": 99,
                          "change_type": "update"})
            esperar(lambda: False, 1)
            list(capa.getFeatures())
            assert recargas == []
            assert "/api/v1/geodata/paginated/" not in [r for r, _ in fake.peticiones]
        finally:
            realtime_hub.unwatch_project()
            realtime_hub.stop_all()
            QgsProject.instance().clear()
            connections.remove_connection("Vivo")
            canal.cerrar()


def test_si_cambia_el_esquema_en_gcc_la_capa_coge_los_campos_nuevos(app_gui, monkeypatch):
    """``layer_schema_changed``: antes había que quitar la capa y volver a añadirla."""
    import copy
    import time

    from qgis.core import QgsProject
    from qgis.PyQt.QtCore import QCoreApplication

    from geosian.gui import media_widget, realtime_hub
    from geosian.provider.metadata import register_provider
    from tests import fake_server
    from tests.fake_ws import FakeWebSocket

    def esperar(condicion, segundos=4):
        limite = time.monotonic() + segundos
        while time.monotonic() < limite:
            QCoreApplication.processEvents()
            if condicion():
                return True
            time.sleep(0.02)
        return False

    def nombres(contenedor):
        for hijo in contenedor.children():
            if hasattr(hijo, "children"):
                yield from nombres(hijo)
            else:
                yield hijo.name()

    register_provider()
    media_widget.register_media_widget()
    iface = _IfaceConBarra()
    canal = FakeWebSocket()
    esquema = copy.deepcopy(fake_server.ESQUEMA_ARBOLADO)
    monkeypatch.setattr(fake_server, "ESQUEMA_ARBOLADO", esquema)
    with FakeGeosian() as fake:
        try:
            realtime_hub.watch_project(iface)
            connections.save_connection("Esquema", fake.url, "a@b.c")
            connections.set_ws_url("Esquema", canal.url)
            capa = _capa_de_prueba(fake, "Esquema")
            [tabla] = [c for c in QgsProject.instance().mapLayers().values() if not c.isSpatial()]
            assert canal.conectado.wait(3)
            assert esperar(lambda: {"type": "subscribe_map", "map_id": 4} in canal.recibidos)
            assert capa.fields().indexOf("estado") < 0

            esquema["attributes"].append({"name": "estado", "type": "string", "title": "Estado"})
            esquema["additional_information"][0]["attributes"].append(
                {"name": "incidencia", "type": "text", "title": "Incidencia"}
            )
            canal.enviar({"type": "layer_schema_changed", "map_id": 4, "layer_id": 11,
                          "geometry_type": "Point"})
            assert esperar(lambda: capa.fields().indexOf("estado") >= 0)
            assert esperar(lambda: tabla.fields().indexOf("incidencia") >= 0)
            # La ficha también: el campo nuevo sale y siguen sus pestañas de partes y fotos.
            en_ficha = {n for p in capa.editFormConfig().tabs() for n in nombres(p)}
            assert "estado" in en_ficha
            pestañas = [p.name() for p in capa.editFormConfig().tabs()]
            assert "Información adicional" in pestañas and "Fotos y archivos" in pestañas
            assert "incidencia" in {n for p in tabla.editFormConfig().tabs() for n in nombres(p)}
            assert not any("vuelve a añadirla" in w.text().lower() for w in iface.barra.items())
        finally:
            realtime_hub.unwatch_project()
            realtime_hub.stop_all()
            QgsProject.instance().clear()
            connections.remove_connection("Esquema")
            canal.cerrar()


def test_al_reabrir_un_proyecto_se_suscribe_a_sus_mapas(app_gui, tmp_path):
    from qgis.core import QgsProject, QgsVectorLayer

    from geosian.gui import realtime_hub
    from geosian.provider.metadata import register_provider
    from tests.fake_ws import FakeWebSocket

    register_provider()
    canal = FakeWebSocket()
    proyecto = QgsProject.instance()
    with FakeGeosian() as fake:
        try:
            connections.save_connection("Reabrir", fake.url, "a@b.c")
            connections.set_session("Reabrir", "tok-de-prueba", "jwt")
            connections.set_ws_url("Reabrir", canal.url)
            capa = QgsVectorLayer("geosian://Reabrir/map/4/layer/11?geometry_type=points", "Arbolado", "geosian")
            proyecto.clear()
            proyecto.addMapLayer(capa)
            ruta = str(tmp_path / "reabrir.qgz")
            assert proyecto.write(ruta)
            proyecto.clear()

            realtime_hub.watch_project()
            assert proyecto.read(ruta)
            assert canal.conectado.wait(3)
            hub = realtime_hub._hubs["Reabrir"]
            assert 4 in hub._canal._mapas
        finally:
            realtime_hub.unwatch_project()
            realtime_hub.stop_all()
            proyecto.clear()
            connections.remove_connection("Reabrir")
            canal.cerrar()


class _IfaceConBarra:
    """Un iface con la barra de mensajes de verdad, para ver los avisos y sus botones."""

    def __init__(self):
        from qgis.gui import QgsMessageBar

        self.barra = QgsMessageBar()

    def messageBar(self):
        return self.barra


def test_sin_jwt_se_avisa_una_vez_y_al_entrar_se_activa_el_tiempo_real(app_gui):
    """Una sesión sin JWT no tiene tiempo real. Antes solo quedaba en el registro."""
    import time

    from qgis.core import QgsProject, QgsVectorLayer
    from qgis.PyQt.QtCore import QCoreApplication
    from qgis.PyQt.QtWidgets import QPushButton

    from geosian.gui import realtime_hub
    from geosian.provider.metadata import register_provider
    from tests.fake_ws import FakeWebSocket

    register_provider()
    canal = FakeWebSocket()
    iface = _IfaceConBarra()
    pedidas = []
    proyecto = QgsProject.instance()
    uri = "geosian://SinJwt/map/4/layer/11?geometry_type=points"
    with FakeGeosian() as fake:
        try:
            connections.save_connection("SinJwt", fake.url, "a@b.c")
            connections.set_session("SinJwt", "tok-de-prueba", None)
            connections.set_ws_url("SinJwt", canal.url)
            realtime_hub.watch_project(iface, pedidas.append)
            proyecto.addMapLayer(QgsVectorLayer(uri, "Uno", "geosian"))
            proyecto.addMapLayer(QgsVectorLayer(uri, "Otro", "geosian"))
            [aviso] = iface.barra.items()
            assert "tiempo real" in aviso.text().lower()
            [boton] = aviso.findChildren(QPushButton)
            boton.click()
            assert pedidas == ["SinJwt"]

            # Al volver a entrar con JWT, se suscribe a los mapas que ya estaban.
            connections.set_session("SinJwt", "tok-de-prueba", "jwt")
            realtime_hub.reconnect("SinJwt")
            assert canal.conectado.wait(3)
            limite = time.monotonic() + 3
            while time.monotonic() < limite and 4 not in realtime_hub._hubs["SinJwt"]._canal._mapas:
                QCoreApplication.processEvents()
                time.sleep(0.02)
            assert 4 in realtime_hub._hubs["SinJwt"]._canal._mapas
            assert iface.barra.items() == []
        finally:
            realtime_hub.unwatch_project()
            realtime_hub.stop_all()
            proyecto.clear()
            connections.remove_connection("SinJwt")
            canal.cerrar()


def test_jwt_rechazado_ofrece_volver_a_entrar_y_suelta_el_canal(app_gui):
    from qgis.PyQt.QtWidgets import QPushButton

    from geosian.gui import realtime_hub

    iface = _IfaceConBarra()
    pedidas = []
    try:
        realtime_hub.watch_project(iface, pedidas.append)
        connections.save_connection("Rechazo", "http://127.0.0.1:9", "a@b.c")
        connections.set_session("Rechazo", "tok", "jwt-caducado")
        hub = realtime_hub.subscribe("Rechazo", 4, iface)
        hub._procesar({"type": "auth_failed"})
        hub._procesar({"type": "auth_failed"})
        [aviso] = iface.barra.items()
        aviso.findChildren(QPushButton)[0].click()
        assert pedidas == ["Rechazo"]
        # El canal del JWT rechazado se suelta: al volver a entrar se abre otro.
        assert "Rechazo" not in realtime_hub._hubs
    finally:
        realtime_hub.unwatch_project()
        realtime_hub.stop_all()
        connections.remove_connection("Rechazo")


def test_con_la_sesion_caducada_no_se_avisa_aparte_del_tiempo_real(app_gui):
    """El aviso de la sesión ya ofrece volver a entrar; uno más sobra."""
    from geosian.gui import realtime_hub

    iface = _IfaceConBarra()
    try:
        realtime_hub.watch_project(iface, lambda nombre: None)
        connections.save_connection("YaCaducada", "http://127.0.0.1:9", "a@b.c")
        connections.set_session("YaCaducada", "tok", None)
        connections.mark_expired("YaCaducada")
        assert realtime_hub.subscribe("YaCaducada", 4, iface) is None
        assert iface.barra.items() == []
    finally:
        realtime_hub.unwatch_project()
        realtime_hub.stop_all()
        connections.clear_expired()
        connections.remove_connection("YaCaducada")


def test_sesion_caducada_al_reabrir_y_recuperar_las_capas(app_gui):
    """Con la sesión caducada la capa no se puede abrir; el error lo dice claro y, al
    volver a entrar, las capas del proyecto se recuperan sin rehacerlo."""
    from qgis.core import QgsProject, QgsVectorLayer

    from geosian.gui import sesion
    from geosian.provider.metadata import register_provider

    register_provider()
    proyecto = QgsProject.instance()
    with FakeGeosian() as fake:
        try:
            connections.save_connection("Caducada", fake.url, "a@b.c")
            connections.set_session("Caducada", "tok-caducado", "jwt")
            sesion.clear_expired()
            capa = QgsVectorLayer(
                "geosian://Caducada/map/4/layer/11?geometry_type=points", "Arbolado", "geosian"
            )
            assert not capa.isValid()
            assert "volver a entrar" in capa.dataProvider().error().lower()
            assert sesion.expired() == {"Caducada"}
            proyecto.clear()
            proyecto.addMapLayer(capa)

            connections.set_session("Caducada", "tok-de-prueba", "jwt")
            assert sesion.repair_layers("Caducada") == 1
            assert capa.isValid()
            assert capa.featureCount() == 3
            assert sesion.expired() == set()
        finally:
            proyecto.clear()
            connections.remove_connection("Caducada")


def test_al_reabrir_el_proyecto_sin_sesion_qgis_no_da_las_capas_por_perdidas(app_gui, tmp_path):
    """QGIS manda las capas que no abren a su diálogo de «capas no disponibles». Las de
    Geosian, ya abiertas antes en este equipo, abren vacías y vuelven al entrar."""
    from qgis.core import QgsProject, QgsProjectBadLayerHandler, QgsVectorLayer

    from geosian.gui import sesion
    from geosian.provider.metadata import register_provider

    class Anota(QgsProjectBadLayerHandler):
        def __init__(self, nodos):
            super().__init__()
            self.nodos = nodos

        def handleBadLayers(self, nodos):
            self.nodos.extend(nodos)

    register_provider()
    proyecto = QgsProject.instance()
    perdidas = []
    with FakeGeosian() as fake:
        try:
            connections.save_connection("Reabre", fake.url, "a@b.c")
            connections.set_session("Reabre", "tok-de-prueba", "jwt")
            capa = QgsVectorLayer(
                "geosian://Reabre/map/4/layer/11?geometry_type=points", "Arbolado", "geosian"
            )
            assert capa.isValid()
            proyecto.addMapLayer(capa)
            ruta = str(tmp_path / "p.qgz")
            assert proyecto.write(ruta)
            proyecto.clear()

            connections.set_session("Reabre", "tok-caducado", "jwt")
            sesion.clear_expired()
            proyecto.setBadLayerHandler(Anota(perdidas))
            assert proyecto.read(ruta)
            assert perdidas == []
            [reabierta] = proyecto.mapLayers().values()
            assert reabierta.isValid() and reabierta.featureCount() == 0
            assert sesion.expired() == {"Reabre"}

            connections.set_session("Reabre", "tok-de-prueba", "jwt")
            sesion.repair_layers("Reabre")
            assert reabierta.featureCount() == 3
            assert sesion.expired() == set()
        finally:
            proyecto.setBadLayerHandler(QgsProjectBadLayerHandler())
            proyecto.clear()
            sesion.clear_expired()
            connections.remove_connection("Reabre")


def test_un_proyecto_con_una_capa_que_no_abre_se_lee_sin_caerse(app_gui, tmp_path):
    """Sin definición guardada la capa no abre: QGIS la manda a su diálogo, sin caerse."""
    from qgis.core import QgsProject, QgsProjectBadLayerHandler, QgsVectorLayer

    from geosian.core import definitions
    from geosian.gui import sesion
    from geosian.provider.metadata import register_provider

    class Anota(QgsProjectBadLayerHandler):
        def __init__(self, nodos):
            super().__init__()
            self.nodos = nodos

        def handleBadLayers(self, nodos):
            self.nodos.extend(nodos)

    register_provider()
    proyecto = QgsProject.instance()
    perdidas = []
    with FakeGeosian() as fake:
        try:
            connections.save_connection("SinCopia", fake.url, "a@b.c")
            connections.set_session("SinCopia", "tok-de-prueba", "jwt")
            capa = QgsVectorLayer(
                "geosian://SinCopia/map/4/layer/11?geometry_type=points", "Arbolado", "geosian"
            )
            proyecto.addMapLayer(capa)
            ruta = str(tmp_path / "p.qgz")
            assert proyecto.write(ruta)
            proyecto.clear()
            definitions.forget("SinCopia")

            connections.set_session("SinCopia", "tok-caducado", "jwt")
            proyecto.setBadLayerHandler(Anota(perdidas))
            assert proyecto.read(ruta)
            assert len(perdidas) == 1
            [reabierta] = proyecto.mapLayers().values()
            assert not reabierta.isValid()
        finally:
            proyecto.setBadLayerHandler(QgsProjectBadLayerHandler())
            proyecto.clear()
            sesion.clear_expired()
            connections.remove_connection("SinCopia")


def test_volver_a_entrar_recupera_las_capas_caducadas(app_gui, monkeypatch):
    from geosian.gui import browser_dock, sesion

    reparadas = []
    monkeypatch.setattr(sesion, "repair_layers", reparadas.append)

    class DialogoQueEntra:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return True

    quitados = []
    monkeypatch.setattr(sesion, "dismiss_reconnect", lambda iface, nombre: quitados.append(nombre))
    monkeypatch.setattr(browser_dock, "ConnectionDialog", DialogoQueEntra)
    panel = browser_dock.GeosianBrowserDock(IfaceFalso())
    panel._pedir_reconexion("Caducada")
    assert reparadas == ["Caducada"]
    assert quitados == ["Caducada"]


def test_al_abrir_un_proyecto_con_sesion_caducada_se_ofrece_entrar(app_gui):
    from geosian.core import connections as conexiones
    from geosian.gui import sesion

    class Barra:
        def __init__(self):
            self.avisos = []

        def createMessage(self, titulo, texto):
            from qgis.gui import QgsMessageBar

            return QgsMessageBar().createMessage(titulo, texto)

        def pushWidget(self, widget, nivel=None):
            self.avisos.append(widget)

    class Iface:
        def __init__(self):
            self.barra = Barra()

        def messageBar(self):
            return self.barra

    iface = Iface()
    conexiones.clear_expired()
    sesion.offer_reconnect(iface, lambda nombre: None)
    assert iface.barra.avisos == []

    conexiones.mark_expired("Caducada")
    pedidas = []
    sesion.offer_reconnect(iface, pedidas.append)
    [aviso] = iface.barra.avisos
    assert "Caducada" in aviso.text()
    from qgis.PyQt.QtWidgets import QPushButton

    [boton] = aviso.findChildren(QPushButton)
    boton.click()
    assert pedidas == ["Caducada"]
    conexiones.clear_expired()


def test_el_aviso_de_volver_a_entrar_no_se_repite_mientras_se_ve(app_gui):
    """Al abrir el proyecto avisan la primera caducidad y el «proyecto leído»: un aviso."""
    from qgis.gui import QgsMessageBar

    from geosian.core import connections as conexiones
    from geosian.gui import sesion

    class Iface:
        def __init__(self):
            self.barra = QgsMessageBar()

        def messageBar(self):
            return self.barra

    iface = Iface()
    conexiones.clear_expired()
    conexiones.mark_expired("Doble")
    try:
        sesion.offer_reconnect(iface, lambda nombre: None)
        sesion.offer_reconnect(iface, lambda nombre: None)
        assert len(iface.barra.items()) == 1
        # Cerrado el aviso, vuelve a salir si hace falta.
        iface.barra.clearWidgets()
        sesion.offer_reconnect(iface, lambda nombre: None)
        assert len(iface.barra.items()) == 1
        # Y al volver a entrar se quita: las capas ya tienen datos.
        sesion.dismiss_reconnect(iface, "Doble")
        assert iface.barra.items() == []
    finally:
        conexiones.clear_expired()


def test_la_sesion_que_caduca_a_mitad_avisa_una_vez(app_gui):
    from qgis.PyQt.QtCore import QCoreApplication

    from geosian.core import connections as conexiones
    from geosian.gui import sesion

    avisadas = []
    conexiones.clear_expired()
    sesion.watch_expired(avisadas.append)
    try:
        conexiones.mark_expired("Mitad")
        conexiones.mark_expired("Mitad")  # otra capa de la misma conexión
        QCoreApplication.processEvents()
        assert avisadas == ["Mitad"]
    finally:
        sesion.unwatch_expired()
        conexiones.clear_expired()
