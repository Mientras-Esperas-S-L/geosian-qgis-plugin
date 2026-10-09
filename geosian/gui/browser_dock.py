"""Panel de mapas y capas.

Árbol con las conexiones, sus mapas y las capas de cada mapa. Doble clic sobre
una capa y entra en el proyecto.

El árbol se llena a demanda: los mapas se piden al desplegar la conexión y las
capas al desplegar el mapa. Con conexiones que tienen decenas de mapas, cargarlo
todo de golpe al abrir QGIS sería una espera que nadie ha pedido.
"""

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsMapLayerType,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsRelation,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import Qt, QTimer
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

from ..core import connections, icon_store, lad, maptree, styles, symbology, views
from ..core.errors import AuthError, GeosianError
from ..provider.provider import GEOMETRY_TYPES
from ..provider.uri import build_uri
from . import media_widget
from .connection_dialog import ConnectionDialog

ROL_TIPO = Qt.ItemDataRole.UserRole
ROL_DATOS = Qt.ItemDataRole.UserRole + 1

TIPO_CONEXION = "conexion"
TIPO_MAPA = "mapa"
TIPO_CAPA = "capa"
TIPO_VISTA = "vista"
TIPO_ESPACIO = "espacio"

# Fondos. El mapa base propio de GCC son teselas vectoriales con un estilo de
# MapLibre; en QGIS se usa el equivalente ráster público más cercano.
ESPAÑA = QgsRectangle(-18.5, 27.4, 4.6, 44.0)
MERCATOR = QgsCoordinateReferenceSystem("EPSG:3857")
# Donde van las tablas de partes, para no mezclarlas con las capas del mapa.
GRUPO_PARTES = "Información adicional"
FONDO_IGN = (
    "Fondo: mapa base del IGN",
    (
        "type=xyz&url=https://tms-ign-base.idee.es/1.0.0/IGNBaseTodo/{z}/{x}/{-y}.jpeg"
        "&zmin=0&zmax=17"
    ),
)
FONDO_OSM = (
    "Fondo: OpenStreetMap",
    "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png&zmin=0&zmax=19",
)

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
            cliente = connections.cached_client(nombre)
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

        # Agrupados por espacio de trabajo, como en el selector de mapas de la web.
        espacios = {}
        for mapa in mapas:
            espacio = mapa.get("workspace_name") or "Sin espacio de trabajo"
            if espacio not in espacios:
                carpeta = QTreeWidgetItem([espacio])
                carpeta.setData(0, ROL_TIPO, TIPO_ESPACIO)
                carpeta.setFlags(Qt.ItemFlag.ItemIsEnabled)
                espacios[espacio] = carpeta
            hijo = QTreeWidgetItem([mapa.get("name") or f"Mapa {mapa.get('id')}"])
            hijo.setData(0, ROL_TIPO, TIPO_MAPA)
            hijo.setData(0, ROL_DATOS, {"conexion": nombre, "mapa": mapa})
            hijo.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            espacios[espacio].addChild(hijo)
        for espacio in sorted(espacios, key=str.casefold):
            item.addChild(espacios[espacio])

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
                # Todas las vistas se abren igual, sea cual sea su context_type:
                # la web no lo mira al pintarlas, y su editor solo crea vistas de
                # elementos. Los filtros sobre información adicional ya se
                # traducen a attr__<formulario>__<campo>.
                nieto = QTreeWidgetItem([f"Vista: {vista.get('name')}"])
                nieto.setData(0, ROL_TIPO, TIPO_VISTA)
                nieto.setData(
                    0,
                    ROL_DATOS,
                    {"conexion": nombre, "mapa": mapa, "capa": capa, "vista": vista},
                )
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
        """Mete el mapa entero en un grupo, ordenado y encendido como en GCC.

        Respeta el orden y las carpetas del panel de capas, las capas apagadas
        y la vista activa de cada capa, según las preferencias del usuario en
        ese mapa. Si el proyecto no tiene fondo, le pone uno.
        """
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

        # Lo que no sea imprescindible no impide abrir el mapa.
        try:
            ajustes = cliente.map_settings(mapa["id"])
        except GeosianError:
            ajustes = {}
        try:
            vistas = cliente.map_views(mapa["id"])
        except GeosianError:
            vistas = {}

        por_id = {c["id"]: c for c in capas if "id" in c}
        cliente.prefetch_layer_attributes(list(por_id))
        activas = maptree.active_views(ajustes, vistas)
        ocultas = maptree.hidden_layers(ajustes)

        proyecto = QgsProject.instance()
        vacio = not proyecto.mapLayers()
        if vacio:
            # La web es Web Mercator, y el fondo también.
            proyecto.setCrs(MERCATOR)
        raiz = proyecto.layerTreeRoot()
        grupo = raiz.insertGroup(0, mapa.get("name") or f"Mapa {mapa['id']}")

        def poblar(destino, nodos):
            for nodo in nodos:
                if nodo[0] == "group":
                    _, nombre, expandido, hijos = nodo
                    subgrupo = destino.addGroup(nombre)
                    subgrupo.setExpanded(expandido)
                    poblar(subgrupo, hijos)
                    continue
                lid = nodo[1]
                # Una vista activa sustituye a los datos base de su capa, sea del
                # tipo que sea: la web los oculta si y solo si la capa tiene
                # alguna vista activa (``layerBaseVisible`` en maps.jsx).
                vista = activas.get(lid)
                añadidas = self.añadir_capa(
                    {"conexion": conexion, "mapa": mapa, "capa": por_id[lid], "vista": vista},
                    grupo=destino,
                    avisar=False,
                )
                if vista is not None:
                    de_vistas.extend(añadidas)
                if lid in ocultas:
                    for capa in añadidas:
                        nodo_capa = raiz.findLayer(capa.id())
                        if nodo_capa is not None:
                            nodo_capa.setItemVisibilityChecked(False)

        de_vistas = []
        poblar(grupo, maptree.layer_tree(ajustes, list(por_id)))

        capas_qgis = [
            n.layer() for n in grupo.findLayers()
            if n.layer() is not None and n.layer().isSpatial()
        ]
        extension = _extension_de(capas_qgis)
        self._añadir_fondo(extension)
        if de_vistas:
            _vistas_encima(raiz, de_vistas)
        self._encuadrar(extension)
        if vacio:
            # Con «usar el CRS de la primera capa», QGIS pone el de la capa
            # (4326) después de que se añada, en diferido. Se reafirma cuando
            # ya lo ha hecho.
            QTimer.singleShot(0, lambda: self._reafirmar_mercator(extension))
        self.iface.messageBar().pushInfo(
            "Geosian", f"{len(capas_qgis)} capa(s) añadidas al proyecto."
        )

    def _añadir_fondo(self, extension):
        """Un mapa base si el proyecto no tiene ninguno: el del IGN en España."""
        proyecto = QgsProject.instance()
        if any(c.type() == QgsMapLayerType.RasterLayer for c in proyecto.mapLayers().values()):
            return
        en_españa = not extension.isNull() and ESPAÑA.contains(extension.center())
        nombre, url = FONDO_IGN if en_españa else FONDO_OSM
        fondo = QgsRasterLayer(url, nombre, "wms")
        if not fondo.isValid():
            return
        proyecto.addMapLayer(fondo, False)
        proyecto.layerTreeRoot().addLayer(fondo)

    def _reafirmar_mercator(self, extension):
        if QgsProject.instance().crs() != MERCATOR:
            QgsProject.instance().setCrs(MERCATOR)
            self._encuadrar(extension)

    def _encuadrar(self, extension):
        lienzo = getattr(self.iface, "mapCanvas", lambda: None)()
        if lienzo is None or extension.isNull():
            return
        if extension.isEmpty():
            # Un solo punto: se le da un margen para no encuadrar a escala cero.
            extension = QgsRectangle(extension)
            extension.grow(0.001)
        transformacion = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem("EPSG:4326"),
            QgsProject.instance().crs(),
            QgsProject.instance(),
        )
        try:
            lienzo.setExtent(transformacion.transformBoundingBox(extension))
        except Exception:
            return
        lienzo.refresh()

    def añadir_capa(self, datos, grupo=None, avisar=True):
        """Mete la capa en el proyecto, una por tipo de geometría.

        Devuelve las capas de QGIS añadidas.
        """
        conexion = datos["conexion"]
        capa = datos["capa"]
        mapa = datos["mapa"]
        vista = datos.get("vista")

        tipos = _tipos_de_geometria(capa)
        if not tipos:
            tipos = [None]

        añadidas = []
        for tipo in tipos:
            nombre = capa.get("name") or f"Capa {capa['id']}"
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

            # El título que enseña la web es el del esquema, no el de la capa.
            esquema = getattr(vectorial.dataProvider(), "schema", None) or {}
            nombre = str(esquema.get("title") or nombre)
            if vista:
                nombre = f"{nombre} · {vista.get('name')}"
            if tipo and len(tipos) > 1:
                nombre = f"{nombre} ({ETIQUETAS_GEOMETRIA.get(tipo, tipo)})"
            vectorial.setName(nombre)

            self._aplicar_esquema(vectorial)
            self._aplicar_estilo(vectorial)
            self._aplicar_etiquetas(vectorial)
            self._limitar_escala(vectorial)
            if grupo is None:
                QgsProject.instance().addMapLayer(vectorial)
            else:
                QgsProject.instance().addMapLayer(vectorial, False)
                grupo.addLayer(vectorial)
            self._añadir_partes(vectorial, conexion, mapa["id"], capa["id"], tipo, grupo)
            añadidas.append(vectorial)

        if añadidas and avisar:
            self.iface.messageBar().pushInfo(
                "Geosian",
                f"{len(añadidas)} capa(s) añadidas al proyecto.",
            )
        return añadidas

    def _añadir_partes(self, capa, conexion, map_id, layer_id, tipo, grupo):
        """Una tabla por tipo de parte, relacionada con la capa por ``geodata_id``.

        Así la ficha del elemento enseña sus partes, como la web. Los partes de
        cada elemento se piden al abrir su ficha, no al añadir la capa.
        """
        tipos = (getattr(capa.dataProvider(), "schema", None) or {}).get(
            "additional_information"
        ) or []
        proyecto = QgsProject.instance()
        relaciones = []
        for info in tipos:
            if not isinstance(info, dict) or not info.get("name"):
                continue
            uri = build_uri(conexion, map_id, layer_id, geometry_type=tipo, info_name=info["name"])
            tabla = QgsVectorLayer(uri, f"{capa.name()} · {info.get('title') or info['name']}", "geosian")
            if not tabla.isValid():
                continue
            self._aplicar_esquema(tabla)
            # La lista de partes de la ficha los nombra así; sin esto, QGIS coge
            # el primer campo de texto, que suele estar vacío.
            tabla.setDisplayExpression(
                "coalesce(\"usuario\", '?') || ' · ' || left(\"created_at\", 10)"
            )
            proyecto.addMapLayer(tabla, False)
            _grupo_de_partes(grupo).addLayer(tabla)

            relacion = QgsRelation()
            relacion.setId(f"geosian_partes_{capa.id()}_{info['name']}")
            relacion.setName(tabla.name())
            relacion.setReferencedLayer(capa.id())
            relacion.setReferencingLayer(tabla.id())
            relacion.addFieldPair("geodata_id", "id")
            if relacion.isValid():
                proyecto.relationManager().addRelation(relacion)
                relaciones.append((relacion, info))
        if relaciones:
            lad.add_relations_tab(capa, relaciones)

    def _aplicar_etiquetas(self, capa):
        """Las etiquetas que la web enciende sola, a partir de la misma escala."""
        proveedor = capa.dataProvider()
        try:
            atributo = styles.label_attribute(proveedor.schema)
            if not atributo:
                return
            resolver = symbology.field_resolver(proveedor.fields(), proveedor.attr_map)
            campo = resolver(atributo)
            if campo:
                symbology.apply_labels(capa, campo, proveedor.layer_uri.geometry_type)
        except Exception as exc:
            proveedor.log_warning(f"{capa.name()}: no se pudieron poner las etiquetas: {exc}")

    def _aplicar_estilo(self, capa):
        """Pinta la capa como la pinta Geosian, con el estilo de su esquema."""
        proveedor = capa.dataProvider()
        try:
            resolver = symbology.field_resolver(proveedor.fields(), proveedor.attr_map)
            tipo = proveedor.layer_uri.geometry_type
            if proveedor.view is not None:
                renderizador, avisos = symbology.view_renderer(
                    proveedor.view.get("style_config"),
                    tipo,
                    proveedor.schema,
                    resolver,
                    iconos=icon_store.default_store().path,
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
            if media_widget.is_available():
                lad.add_media_tab(capa, esquema, media_widget.WIDGET_TYPE)
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


def menu_de_etiquetas(menu, capa):
    """Submenú «Etiqueta» de una capa de Geosian, como el selector de la web.

    Una etiqueta por capa, a elegir entre los atributos que la web ofrece, o
    ninguna. Se engancha al menú contextual del panel de capas de QGIS.
    """
    proveedor = capa.dataProvider() if capa is not None and capa.isValid() else None
    if proveedor is None or proveedor.name() != "geosian":
        return
    opciones = styles.label_choices(getattr(proveedor, "schema", None))
    if not opciones:
        return
    resolver = symbology.field_resolver(proveedor.fields(), proveedor.attr_map)
    actual = (
        capa.labeling().settings().fieldName
        if capa.labelsEnabled() and capa.labeling() is not None
        else None
    )
    sub = menu.addMenu("Etiqueta (como en la web)")
    sin = sub.addAction("Sin etiqueta")
    sin.setCheckable(True)
    sin.setChecked(actual is None)
    sin.triggered.connect(lambda: _poner_etiqueta(capa, None))
    for nombre, titulo in opciones:
        campo = resolver(nombre)
        if not campo:
            continue
        accion = sub.addAction(titulo)
        accion.setCheckable(True)
        accion.setChecked(campo == actual)
        accion.triggered.connect(lambda _=False, c=campo: _poner_etiqueta(capa, c))


def _poner_etiqueta(capa, campo):
    if campo is None:
        capa.setLabelsEnabled(False)
    else:
        symbology.apply_labels(capa, campo, capa.dataProvider().layer_uri.geometry_type)
    capa.triggerRepaint()


def _grupo_de_partes(grupo):
    """El grupo plegado «Información adicional» al final del mapa (o del proyecto)."""
    raiz = QgsProject.instance().layerTreeRoot()
    destino = grupo or raiz
    while destino.parent() is not None and destino.parent() is not raiz:
        destino = destino.parent()
    existente = destino.findGroup(GRUPO_PARTES)
    if existente is not None and existente.parent() is destino:
        return existente
    nuevo = destino.addGroup(GRUPO_PARTES)
    nuevo.setExpanded(False)
    return nuevo


def _extension_de(capas):
    """Extensión conjunta, en grados, de las capas que la tengan.

    Una capa de un solo punto tiene extensión de tamaño cero: cuenta igual.
    """
    total = QgsRectangle()
    total.setNull()
    for capa in capas:
        extension = capa.extent()
        if extension.isNull():
            continue
        total.combineExtentWith(extension)
    return total



def _vistas_encima(raiz, capas_vista):
    """Las capas de vista se pintan encima de todas las capas base, como en la web.

    La web pinta las capas base en un solo lote al fondo y añade las vistas por
    encima (``maps.jsx``: «las vistas … quedan siempre encima»), así que una
    vista de una capa baja del panel se ve sobre capas más altas. El panel de
    capas de QGIS no cambia: solo el orden de pintado del proyecto.
    """
    ids = {c.id() for c in capas_vista}
    actuales = raiz.customLayerOrder() if raiz.hasCustomLayerOrder() else raiz.layerOrder()
    vistas = [c for c in actuales if c.id() in ids]
    resto = [c for c in actuales if c.id() not in ids]
    raiz.setCustomLayerOrder(vistas + resto)
    raiz.setHasCustomLayerOrder(True)
