"""Punto de entrada del complemento."""

from qgis.core import QgsMapLayerType
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAction

from .gui import realtime_hub
from .gui.browser_dock import GeosianBrowserDock, menu_de_etiquetas
from .gui.connection_dialog import ConnectionDialog
from .gui.media_widget import register_media_widget
from .provider.metadata import register_provider

MENU = "&Geosian"


class GeosianPlugin:
    """Registra el proveedor y monta la interfaz."""

    def __init__(self, iface):
        self.iface = iface
        self.dock = None
        self.acciones = []

    def initGui(self):
        # El proveedor se registra al arrancar y no al abrir el panel: un
        # proyecto guardado con capas geosian:// tiene que poder abrirlas sin
        # que el usuario toque nada.
        if not register_provider():
            self.iface.messageBar().pushCritical(
                "Geosian",
                "No se pudo registrar el proveedor de datos. Las capas de "
                "Geosian no se podrán abrir en esta sesión.",
            )

        # Igual con el panel de fotos de la ficha, que es un tipo de campo.
        register_media_widget()

        self.dock = GeosianBrowserDock(self.iface, self.iface.mainWindow())
        self.iface.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.dock)
        self.dock.hide()

        self._añadir_accion(
            "Mapas y capas de Geosian",
            self._alternar_panel,
            checkable=True,
        )
        self._añadir_accion("Nueva conexión...", self._nueva_conexion)

        # El selector de etiquetas de la web, en el menú contextual de la capa.
        vista = self.iface.layerTreeView()
        if vista is not None and hasattr(vista, "contextMenuAboutToShow"):
            vista.contextMenuAboutToShow.connect(self._menu_de_capa)

    def _añadir_accion(self, texto, callback, checkable=False):
        accion = QAction(texto, self.iface.mainWindow())
        accion.setCheckable(checkable)
        accion.triggered.connect(callback)
        self.iface.addPluginToMenu(MENU, accion)
        self.acciones.append(accion)
        return accion

    def _alternar_panel(self):
        if self.dock is None:
            return
        self.dock.setVisible(not self.dock.isVisible())

    def _nueva_conexion(self):
        dialogo = ConnectionDialog(self.iface.mainWindow())
        if dialogo.exec() and self.dock is not None:
            self.dock.refrescar()
            self.dock.show()

    def _menu_de_capa(self, menu):
        capa = self.iface.layerTreeView().currentLayer()
        if capa is not None and capa.type() == QgsMapLayerType.VectorLayer:
            menu_de_etiquetas(menu, capa)

    def unload(self):
        realtime_hub.stop_all()
        vista = self.iface.layerTreeView()
        if vista is not None and hasattr(vista, "contextMenuAboutToShow"):
            try:
                vista.contextMenuAboutToShow.disconnect(self._menu_de_capa)
            except TypeError:
                pass
        for accion in self.acciones:
            self.iface.removePluginMenu(MENU, accion)
        self.acciones = []

        if self.dock is not None:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None

        # El proveedor no se puede quitar del registro de QGIS una vez puesto.
        # Se deja registrado a propósito: si el usuario recarga el complemento,
        # register_provider() ve que ya está y no duplica nada.
