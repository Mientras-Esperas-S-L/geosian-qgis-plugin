"""«Crear capa en Geosian…»: una capa nueva en un mapa, sin definir sus campos en QGIS.

Dos formas (``core/crear_capa.py`` y la API ``maps/<id>/layers/crear/``):

- **A partir de otra capa de Geosian**: la capa nueva, vacía, con los formularios, partes
  y colores de la elegida, y si se quiere sus vistas.
- **A partir de una capa de QGIS**: con sus campos (nombre, título y tipo) y, si se
  quiere, sus elementos, que suben con el guardado de siempre (todo o nada).

Lo demás (listas, partes, fotos, colores) se completa en la web. La capa nueva la ve el
grupo de quien la crea y va en la carpeta «Nuevas desde QGIS».
"""

from qgis.core import (
    QgsCoordinateTransform,
    QgsFeature,
    QgsGeometry,
    QgsMapLayerProxyModel,
    QgsProject,
    QgsWkbTypes,
)
from qgis.gui import QgsMapLayerComboBox
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QRadioButton,
    QVBoxLayout,
)

from ..core import connections
from ..core import crear_capa as C
from ..core.errors import GeosianError

PLANTILLA, DE_QGIS = 0, 1


class CrearCapaDialog(QDialog):
    def __init__(self, conexion, mapa, parent=None):
        super().__init__(parent)
        self.conexion = conexion
        self.mapa = mapa
        self.cliente = connections.client_for(conexion)
        self.capa_creada = None
        self.subir = False
        self.correspondencia = {}
        self.setWindowTitle(f"Crear capa en «{mapa.get('name')}»")
        self.setMinimumWidth(560)

        self.nombre = QLineEdit()
        self.nombre.setPlaceholderText("Arbolado 2027")
        formulario = QFormLayout()
        formulario.addRow("Nombre", self.nombre)

        self.forma = QButtonGroup(self)
        self.de_plantilla = QRadioButton("A partir de otra capa de Geosian (sus formularios, partes y colores)")
        self.de_qgis = QRadioButton("A partir de una capa de QGIS (sus campos y, si quieres, sus elementos)")
        self.forma.addButton(self.de_plantilla, PLANTILLA)
        self.forma.addButton(self.de_qgis, DE_QGIS)
        self.de_plantilla.setChecked(True)

        # Plantilla: mapa y capa (por defecto, el mapa en el que se crea).
        self.caja_plantilla = QGroupBox()
        disp = QFormLayout(self.caja_plantilla)
        self.mapa_plantilla = QComboBox()
        self.capa_plantilla = QComboBox()
        self.copiar_vistas = QCheckBox("Copiar también sus vistas")
        disp.addRow("Mapa", self.mapa_plantilla)
        disp.addRow("Capa", self.capa_plantilla)
        disp.addRow("", self.copiar_vistas)

        # Desde QGIS: la capa y lo que se va a crear.
        self.caja_qgis = QGroupBox()
        disp = QFormLayout(self.caja_qgis)
        self.capa_qgis = QgsMapLayerComboBox()
        self.capa_qgis.setFilters(QgsMapLayerProxyModel.Filter.VectorLayer)
        self.capa_qgis.setExcludedProviders(["geosian"])
        self.resumen = QLabel()
        self.resumen.setWordWrap(True)
        self.resumen.setTextFormat(Qt.TextFormat.PlainText)
        self.con_elementos = QCheckBox()
        disp.addRow("Capa de QGIS", self.capa_qgis)
        disp.addRow("", self.resumen)
        disp.addRow("", self.con_elementos)

        aviso = QLabel(
            "La capa nueva la verá tu grupo y aparecerá en la carpeta «Nuevas desde QGIS». "
            "Listas, partes, fotos y colores se completan después en la web de GCC."
        )
        aviso.setWordWrap(True)
        self.estado = QLabel("")
        self.estado.setWordWrap(True)

        self.botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.botones.button(QDialogButtonBox.StandardButton.Ok).setText("Crear capa")
        self.botones.accepted.connect(self._crear)
        self.botones.rejected.connect(self.reject)

        caja = QVBoxLayout(self)
        caja.addLayout(formulario)
        caja.addWidget(self.de_plantilla)
        caja.addWidget(self.caja_plantilla)
        caja.addWidget(self.de_qgis)
        caja.addWidget(self.caja_qgis)
        caja.addWidget(aviso)
        caja.addWidget(self.estado)
        caja.addWidget(self.botones)

        self.forma.idToggled.connect(self._al_cambiar_forma)
        self.mapa_plantilla.currentIndexChanged.connect(self._cargar_capas_plantilla)
        self.capa_qgis.layerChanged.connect(self._al_cambiar_capa_qgis)
        self._cargar_mapas()
        self._al_cambiar_capa_qgis(self.capa_qgis.currentLayer())
        self._al_cambiar_forma()

    # ------------------------------------------------------------------
    def _al_cambiar_forma(self, *_):
        plantilla = self.forma.checkedId() == PLANTILLA
        self.caja_plantilla.setEnabled(plantilla)
        self.caja_qgis.setEnabled(not plantilla)

    def _cargar_mapas(self):
        try:
            mapas = self.cliente.maps() if self.cliente else []
        except GeosianError as exc:
            self.estado.setText(f"No se pudieron cargar los mapas: {exc}")
            mapas = []
        mapas = sorted(mapas, key=lambda m: (m.get("id") != self.mapa.get("id"), str(m.get("name") or "").casefold()))
        for mapa in mapas:
            self.mapa_plantilla.addItem(mapa.get("name") or f"Mapa {mapa.get('id')}", mapa)

    def _cargar_capas_plantilla(self, *_):
        self.capa_plantilla.clear()
        mapa = self.mapa_plantilla.currentData()
        if not mapa:
            return
        try:
            capas = self.cliente.layers(mapa["id"])
        except GeosianError as exc:
            self.estado.setText(f"No se pudieron cargar las capas: {exc}")
            return
        for capa in sorted(capas, key=lambda c: str(c.get("name") or "").casefold()):
            self.capa_plantilla.addItem(capa.get("name") or f"Capa {capa.get('id')}", capa)

    def _al_cambiar_capa_qgis(self, capa):
        self.campos, self.fuera, self.correspondencia = ([], [], {})
        self.geometria = None
        if capa is None:
            self.resumen.setText("No hay capas vectoriales en el proyecto.")
            self.con_elementos.setEnabled(False)
            return
        self.geometria = C.tipo_de_geometria(capa)
        self.campos, self.fuera, self.correspondencia = C.campos_de(capa)
        lineas = []
        if self.geometria is None:
            lineas.append("Esta capa no tiene geometría de punto, línea o polígono: no se puede crear.")
        else:
            lineas.append(f"Geometría: {self.geometria}.")
        if self.campos:
            nombres = [
                c["name"] if c["name"] == c["title"] else f"{c['title']} → {c['name']}" for c in self.campos
            ]
            lineas.append(f"Campos ({len(self.campos)}): " + ", ".join(nombres) + ".")
        else:
            lineas.append("No tiene campos que se puedan llevar.")
        if self.fuera:
            lineas.append("No se llevan (tipo no admitido): " + ", ".join(self.fuera) + ".")
        self.resumen.setText("\n".join(lineas))
        total = capa.featureCount()
        self.con_elementos.setText(f"Subir también sus {total:,} elementos".replace(",", "."))
        self.con_elementos.setEnabled(0 < total <= C.MAX_ELEMENTOS)
        self.con_elementos.setChecked(0 < total <= C.MAX_ELEMENTOS)
        if total > C.MAX_ELEMENTOS:
            self.con_elementos.setText(
                f"Tiene {total:,} elementos: más de {C.MAX_ELEMENTOS:,} no se suben de una vez".replace(",", ".")
            )

    # ------------------------------------------------------------------
    def _crear(self):
        nombre = self.nombre.text().strip()
        if not nombre:
            self.estado.setText("Ponle un nombre a la capa.")
            return
        if self.forma.checkedId() == PLANTILLA:
            plantilla = self.capa_plantilla.currentData()
            if not plantilla:
                self.estado.setText("Elige la capa que sirve de modelo.")
                return
            datos = {"name": nombre, "plantilla": plantilla["id"], "copiar_vistas": self.copiar_vistas.isChecked()}
        else:
            if self.capa_qgis.currentLayer() is None or self.geometria is None or not self.campos:
                self.estado.setText("Elige una capa de QGIS con geometría y algún campo.")
                return
            datos = {"name": nombre, "geometry_type": self.geometria, "campos": self.campos}

        self.botones.setEnabled(False)
        self.estado.setText("Creando la capa…")
        try:
            self.capa_creada = self.cliente.crear_capa(self.mapa["id"], datos)
        except GeosianError as exc:
            self.estado.setText(f"No se ha creado: {exc}")
            return
        finally:
            self.botones.setEnabled(True)
        self.subir = self.forma.checkedId() == DE_QGIS and self.con_elementos.isChecked()
        self.accept()


def subir_elementos(origen, destino, correspondencia):
    """Copia los elementos de ``origen`` (QGIS) a ``destino`` (la capa de Geosian nueva) y
    guarda: un solo lote, todo o nada (más de 300, en segundo plano).

    Devuelve ``(ok, mensaje)``.
    """
    transformacion = QgsCoordinateTransform(origen.crs(), destino.crs(), QgsProject.instance())
    campos = destino.fields()
    multi = QgsWkbTypes.isMultiType(destino.wkbType())
    nuevos = []
    for elemento in origen.getFeatures():
        geometria = QgsGeometry(elemento.geometry())
        if geometria.isNull() or geometria.isEmpty():
            continue
        geometria.transform(transformacion)
        if multi:
            geometria.convertToMultiType()
        nuevo = QgsFeature(campos)
        nuevo.setGeometry(geometria)
        for de_qgis, en_geosian in correspondencia.items():
            indice = campos.indexFromName(en_geosian)
            if indice >= 0:
                valor = elemento[de_qgis]
                nuevo.setAttribute(indice, valor)
        nuevos.append(nuevo)
    if not nuevos:
        return True, "La capa de QGIS no tiene elementos con geometría."
    if not destino.isEditable():
        destino.startEditing()
    if not destino.addFeatures(nuevos):
        destino.rollBack()
        return False, "QGIS no pudo preparar los elementos."
    if destino.commitChanges():
        return True, f"Subidos {len(nuevos):,} elementos.".replace(",", ".")
    errores = "; ".join(destino.commitErrors())
    destino.rollBack()
    return False, f"No se ha subido nada: {errores}"


def crear_capa(dock, datos_mapa, parent=None):
    """Abre el diálogo y, al aceptar, añade la capa al proyecto (y sube sus elementos)."""
    conexion, mapa = datos_mapa["conexion"], datos_mapa["mapa"]
    dialogo = CrearCapaDialog(conexion, mapa, parent)
    if not dialogo.exec() or not dialogo.capa_creada:
        return None
    capa = dict(dialogo.capa_creada)
    # Una capa vacía no trae tipos en los metadatos: los de su definición de campos.
    tipos = {"Point": "points", "MultiPoint": "multi_points", "MultiLineString": "multi_lines",
             "MultiPolygon": "multi_polygons"}
    capa["tile_metadata"] = {"geometry_types": [tipos[t] for t in capa.get("geometry_types") or [] if t in tipos]}
    añadidas = dock.añadir_capa({"conexion": conexion, "mapa": mapa, "capa": capa})
    if dialogo.subir and añadidas:
        ok, mensaje = subir_elementos(dialogo.capa_qgis.currentLayer(), añadidas[0], dialogo.correspondencia)
        (dock.iface.messageBar().pushSuccess if ok else dock.iface.messageBar().pushWarning)(
            "Geosian", f"«{capa.get('name')}»: {mensaje}"
        )
    elif añadidas:
        dock.iface.messageBar().pushSuccess(
            "Geosian",
            f"Capa «{capa.get('name')}» creada. Sus formularios, partes y colores se completan en la web.",
        )
    if not añadidas:
        QMessageBox.warning(parent, "Geosian", "La capa se ha creado, pero no se pudo abrir en QGIS.")
    return añadidas
