"""Panel de mapas y capas.

Árbol con las conexiones, sus mapas y las capas de cada mapa. Doble clic sobre
una capa y entra en el proyecto.

El árbol se llena a demanda: los mapas se piden al desplegar la conexión y las
capas al desplegar el mapa. Con conexiones que tienen decenas de mapas, cargarlo
todo de golpe al abrir QGIS sería una espera que nadie ha pedido.
"""

from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDockWidget,
    QHBoxLayout,
    QMenu,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import connections, lad, symbology, views
from ..core.errors import AuthError, GeosianError
from ..provider.provider import GEOMETRY_TYPES
from ..provider.uri import build_uri
from .connection_dialog import ConnectionDialog

ROL_TIPO = Qt.ItemDataRole.UserRole
ROL_DATOS = Qt.ItemDataRole.UserRole + 1

TIPO_CONEXION = "conexion"
TIPO_MAPA = "mapa"
TIPO_CAPA = "capa"
TIPO_VISTA = "vista"

# Nombres legibles de los tipos de geometría, para cuando una capa tiene más
# de uno y hay que abrir una capa de QGIS por cada uno.
ETIQUETAS_GEOMETRIA = {
    "points": "puntos",
    "multi_points": "puntos múltiples",
    "lines": "líneas",
    "multi_lines": "líneas múltiples",
    "polygons": "polígonos",
    "multi_polygons": "polígonos múltiples",
    "geometry_collections": "colecciones",
}


class GeosianBrowserDock(QDockWidget):
    """Panel acoplable con el catálogo de Geosian."""

    def __init__(self, iface, parent=None):
        super().__init__("Geosian", parent)
        self.iface = iface
        self.setObjectName("GeosianBrowserDock")

        contenedor = QWidget()
        disposicion = QVBoxLayout(contenedor)
        disposicion.setContentsMargins(4, 4, 4, 4)

        self.arbol = QTreeWidget()
        self.arbol.setHeaderHidden(True)
        self.arbol.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.arbol.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.arbol.itemExpanded.connect(self._al_desplegar)
        self.arbol.itemDoubleClicked.connect(self._al_doble_clic)
        self.arbol.customContextMenuRequested.connect(self._menu_contextual)

        botonera = QHBoxLayout()
        self.btn_nueva = QPushButton("Nueva conexión")
        self.btn_nueva.clicked.connect(self.nueva_conexion)
        self.btn_refrescar = QPushButton("Refrescar")
        self.btn_refrescar.clicked.connect(self.refrescar)
        botonera.addWidget(self.btn_nueva)
        botonera.addWidget(self.btn_refrescar)

        disposicion.addWidget(self.arbol)
        disposicion.addLayout(botonera)
        self.setWidget(contenedor)

        self.refrescar()

    # ------------------------------------------------------------------
    # Árbol
    # ------------------------------------------------------------------

    def refrescar(self):
        self.arbol.clear()
        for nombre in connections.list_connections():
            cliente = connections.client_for(nombre)
            if cliente is not None:
                cliente.forget_layers()
            item = QTreeWidgetItem([nombre])
            item.setData(0, ROL_TIPO, TIPO_CONEXION)
            item.setData(0, ROL_DATOS, nombre)
            item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            self.arbol.addTopLevelItem(item)

        if self.arbol.topLevelItemCount() == 0:
            vacio = QTreeWidgetItem(["Sin conexiones. Crea una para empezar."])
            vacio.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.arbol.addTopLevelItem(vacio)

    def _al_desplegar(self, item):
        # Ya tiene contenido de verdad: no hay nada que pedir.
        if item.childCount() > 0:
            return

        tipo = item.data(0, ROL_TIPO)
        if tipo == TIPO_CONEXION:
            self._cargar_mapas(item)
        elif tipo == TIPO_MAPA:
            self._cargar_capas(item)

    def _cargar_mapas(self, item):
        nombre = item.data(0, ROL_DATOS)
        cliente = connections.client_for(nombre)
        if cliente is None:
            return
        try:
            mapas = cliente.maps()
        except AuthError:
            self._pedir_reconexion(nombre)
            return
        except GeosianError as exc:
            self._error(f"No se pudieron cargar los mapas: {exc}")
            return

        if not mapas:
            item.addChild(_hoja_informativa("Este usuario no tiene mapas"))
            return

        for mapa in mapas:
            hijo = QTreeWidgetItem([mapa.get("name") or f"Mapa {mapa.get('id')}"])
            hijo.setData(0, ROL_TIPO, TIPO_MAPA)
            hijo.setData(0, ROL_DATOS, {"conexion": nombre, "mapa": mapa})
            hijo.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            item.addChild(hijo)

    def _cargar_capas(self, item):
        datos = item.data(0, ROL_DATOS)
        nombre = datos["conexion"]
        mapa = datos["mapa"]
        cliente = connections.client_for(nombre)
        if cliente is None:
            return
        try:
            capas = cliente.layers(mapa["id"])
        except AuthError:
            self._pedir_reconexion(nombre)
            return
        except GeosianError as exc:
            self._error(f"No se pudieron cargar las capas: {exc}")
            return

        if not capas:
            item.addChild(_hoja_informativa("Este mapa no tiene capas"))
            return

        try:
            vistas = cliente.map_views(mapa["id"])
        except GeosianError:
            # Sin vistas el mapa se puede usar igual.
            vistas = {}

        for capa in capas:
            hijo = QTreeWidgetItem([capa.get("name") or f"Capa {capa.get('id')}"])
            hijo.setData(0, ROL_TIPO, TIPO_CAPA)
            hijo.setData(
                0, ROL_DATOS, {"conexion": nombre, "mapa": mapa, "capa": capa}
            )
            item.addChild(hijo)
            for vista in vistas.get(capa.get("id")) or []:
                nieto = QTreeWidgetItem([f"Vista: {vista.get('name')}"])
                if views.is_element_view(vista):
                    nieto.setData(0, ROL_TIPO, TIPO_VISTA)
                    nieto.setData(
                        0,
                        ROL_DATOS,
                        {"conexion": nombre, "mapa": mapa, "capa": capa, "vista": vista},
                    )
                else:
                    # Muestra registros de información adicional, no elementos.
                    nieto.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    nieto.setToolTip(0, "Vista de información adicional: todavía no se abre en QGIS.")
                hijo.addChild(nieto)

    # ------------------------------------------------------------------
    # Acciones
    # ------------------------------------------------------------------

    def _al_doble_clic(self, item, _columna):
        if item.data(0, ROL_TIPO) in (TIPO_CAPA, TIPO_VISTA):
            self.añadir_capa(item.data(0, ROL_DATOS))

    def _menu_contextual(self, punto):
        item = self.arbol.itemAt(punto)
        if item is None:
            return
        tipo = item.data(0, ROL_TIPO)
        menu = QMenu(self)

        if tipo in (TIPO_CAPA, TIPO_VISTA):
            menu.addAction(
                "Añadir al proyecto",
                lambda: self.añadir_capa(item.data(0, ROL_DATOS)),
            )
        elif tipo == TIPO_MAPA:
            menu.addAction(
                "Añadir el mapa entero",
                lambda: self.añadir_mapa(item.data(0, ROL_DATOS)),
            )
        elif tipo == TIPO_CONEXION:
            nombre = item.data(0, ROL_DATOS)
            menu.addAction("Volver a entrar", lambda: self._pedir_reconexion(nombre))
            menu.addAction("Eliminar conexión", lambda: self._eliminar(nombre))

        if not menu.isEmpty():
            menu.exec(self.arbol.viewport().mapToGlobal(punto))

    def nueva_conexion(self):
        dialogo = ConnectionDialog(self)
        if dialogo.exec():
            self.refrescar()

    def _pedir_reconexion(self, nombre):
        dialogo = ConnectionDialog(self, nombre=nombre)
        if dialogo.exec():
            self.refrescar()

    def _eliminar(self, nombre):
        respuesta = QMessageBox.question(
            self,
            "Eliminar conexión",
            f"¿Eliminar la conexión «{nombre}»?",
        )
        if respuesta == QMessageBox.StandardButton.Yes:
            connections.remove_connection(nombre)
            self.refrescar()

    def añadir_mapa(self, datos):
        """Mete todas las capas del mapa en un grupo con su nombre."""
        conexion = datos["conexion"]
        mapa = datos["mapa"]
        cliente = connections.client_for(conexion)
        if cliente is None:
            return
        try:
            capas = cliente.layers(mapa["id"])
        except AuthError:
            self._pedir_reconexion(conexion)
            return
        except GeosianError as exc:
            self._error(f"No se pudieron cargar las capas: {exc}")
            return

        cliente.prefetch_layer_attributes([c["id"] for c in capas if "id" in c])

        raiz = QgsProject.instance().layerTreeRoot()
        grupo = raiz.insertGroup(0, mapa.get("name") or f"Mapa {mapa['id']}")
        for capa in capas:
            self.añadir_capa(
                {"conexion": conexion, "mapa": mapa, "capa": capa},
                grupo=grupo,
                avisar=False,
            )
        self.iface.messageBar().pushInfo(
            "Geosian", f"{len(grupo.findLayers())} capa(s) añadidas al proyecto."
        )

    def añadir_capa(self, datos, grupo=None, avisar=True):
        """Mete la capa en el proyecto, una por tipo de geometría."""
        conexion = datos["conexion"]
        capa = datos["capa"]
        mapa = datos["mapa"]
        vista = datos.get("vista")

        tipos = _tipos_de_geometria(capa)
        if not tipos:
            tipos = [None]

        añadidas = 0
        for tipo in tipos:
            nombre = capa.get("name") or f"Capa {capa['id']}"
            if vista:
                nombre = f"{nombre} · {vista.get('name')}"
            if tipo and len(tipos) > 1:
                nombre = f"{nombre} ({ETIQUETAS_GEOMETRIA.get(tipo, tipo)})"

            uri = build_uri(
                conexion,
                mapa["id"],
                capa["id"],
                geometry_type=tipo,
                view_id=vista.get("id") if vista else None,
            )
            vectorial = QgsVectorLayer(uri, nombre, "geosian")

            if not vectorial.isValid():
                proveedor = vectorial.dataProvider()
                motivo = proveedor.error() if proveedor else ""
                self._error(f"No se pudo abrir «{nombre}». {motivo}")
                continue

            self._aplicar_esquema(vectorial)
            self._aplicar_estilo(vectorial)
            self._limitar_escala(vectorial)
            if grupo is None:
                QgsProject.instance().addMapLayer(vectorial)
            else:
                QgsProject.instance().addMapLayer(vectorial, False)
                grupo.addLayer(vectorial)
            añadidas += 1

        if añadidas and avisar:
            self.iface.messageBar().pushInfo(
                "Geosian",
                f"{añadidas} capa(s) añadidas al proyecto.",
            )

    def _aplicar_estilo(self, capa):
        """Pinta la capa como la pinta Geosian, con el estilo de su esquema."""
        proveedor = capa.dataProvider()
        try:
            resolver = symbology.field_resolver(proveedor.fields(), proveedor.attr_map)
            tipo = proveedor.layer_uri.geometry_type
            if proveedor.view is not None:
                renderizador, avisos = symbology.view_renderer(
                    proveedor.view.get("style_config"), tipo, proveedor.schema, resolver
                )
            else:
                renderizador, avisos = symbology.base_renderer(proveedor.schema, tipo, resolver)
            capa.setRenderer(renderizador)
            for aviso in avisos:
                proveedor.log_warning(f"{capa.name()}: {aviso}")
        except Exception as exc:
            # Sin estilo se ve con el de QGIS; no es motivo para no abrirla.
            proveedor.log_warning(f"{capa.name()}: no se pudo aplicar el estilo: {exc}")

    def _limitar_escala(self, capa):
        """Una capa grande solo se pinta de cerca, donde se pide por zonas."""
        proveedor = capa.dataProvider()
        escala = getattr(proveedor, "suggested_min_scale", lambda: 0)()
        if not escala:
            return
        capa.setScaleBasedVisibility(True)
        capa.setMinimumScale(escala)
        self.iface.messageBar().pushInfo(
            "Geosian",
            f"«{capa.name()}» tiene {proveedor.featureCount():,} elementos. ".replace(",", ".")
            + f"Se pinta a partir de 1:{escala:,}".replace(",", ".")
            + " y solo se descarga la zona que se ve.",
        )

    def _aplicar_esquema(self, capa):
        """Configura formulario y widgets a partir del esquema de la capa."""
        proveedor = capa.dataProvider()
        esquema = getattr(proveedor, "schema", None)
        if not esquema:
            return
        try:
            lad.apply_editor_config(capa, esquema)
            lad.apply_form(capa, esquema)
        except Exception as exc:
            # Un formulario mal construido no debe impedir ver los datos.
            self.iface.messageBar().pushWarning(
                "Geosian", f"No se pudo construir el formulario: {exc}"
            )

    def _error(self, mensaje):
        self.iface.messageBar().pushCritical("Geosian", mensaje)


def _hoja_informativa(texto):
    item = QTreeWidgetItem([texto])
    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
    return item


def _tipos_de_geometria(capa):
    """Tipos presentes en la capa, según los metadatos que dé la API."""
    metadatos = capa.get("tile_metadata") or {}
    tipos = metadatos.get("geometry_types") or []
    if isinstance(tipos, dict):
        tipos = list(tipos.keys())
    return [t for t in tipos if t in GEOMETRY_TYPES]
