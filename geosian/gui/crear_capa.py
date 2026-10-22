"""«Crear capa en Geosian…»: una capa nueva en un mapa, sin definir sus campos en QGIS.

Dos formas (``core/crear_capa.py`` y la API ``maps/<id>/layers/crear/``):

- **A partir de otra capa de Geosian**: la capa nueva, vacía, con los formularios, partes
  y colores de la elegida, y si se quiere sus vistas.
- **A partir de una capa de QGIS**: con sus campos (nombre, título y tipo) y, si se
  quiere, sus elementos, que suben con el guardado de siempre (todo o nada). Con más de
  ``MAX_ELEMENTOS``, en una tarea de QGIS: se empaquetan en un GeoPackage, suben a trozos y
  el servidor los importa; la capa aparece al terminar (``core/importar_grande.py``).

Lo demás (listas, partes, fotos, colores) se completa en la web. La capa nueva la ve el
grupo de quien la crea y va en la carpeta «Nuevas desde QGIS».
"""

import os
import shutil
import tempfile

from qgis.core import (
    QgsApplication,
    QgsCoordinateTransform,
    QgsFeature,
    QgsGeometry,
    QgsMapLayerProxyModel,
    QgsProject,
    QgsTask,
    QgsVectorLayerFeatureSource,
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
from ..core import importar_grande as I
from ..core.errors import AuthError, GeosianError, NetworkError

PLANTILLA, DE_QGIS = 0, 1


def texto_de_error(exc):
    """Lo que se le dice a quien crea la capa, con qué hacer si se puede."""
    if isinstance(exc, AuthError):
        return ("Tu sesión de Geosian ha caducado. Vuelve a entrar (clic derecho en la conexión del "
                "panel › Volver a entrar) y repite.")
    if isinstance(exc, NetworkError):
        return f"Sin conexión con Geosian: {exc}. Comprueba la red y repite."
    return str(exc)


class CrearCapaDialog(QDialog):
    def __init__(self, conexion, mapa, parent=None):
        super().__init__(parent)
        self.conexion = conexion
        self.mapa = mapa
        self.cliente = connections.client_for(conexion)
        self.capa_creada = None
        # Lo que falló al cargar mapas o capas: manda sobre «elige la plantilla».
        self.error_de_carga = None
        self.subir = False
        # Más de MAX_ELEMENTOS: la capa no se crea aquí, la crea la importación.
        self.grande = None
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
            self.error_de_carga = f"No se pudieron cargar los mapas. {texto_de_error(exc)}"
            self.estado.setText(self.error_de_carga)
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
            self.error_de_carga = f"No se pudieron cargar las capas. {texto_de_error(exc)}"
            self.estado.setText(self.error_de_carga)
            return
        for capa in sorted(capas, key=lambda c: str(c.get("name") or "").casefold()):
            self.capa_plantilla.addItem(capa.get("name") or f"Capa {capa.get('id')}", capa)

    def _al_cambiar_capa_qgis(self, capa):
        self.campos, self.fuera, self.correspondencia = ([], [], {})
        self.geometria = None
        self.total_elementos = 0
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
            lineas.append("Sin campos: la capa tendrá solo geometría; los campos se añaden en la web.")
        if self.fuera:
            lineas.append("No se llevan (tipo no admitido): " + ", ".join(self.fuera) + ".")
        self.resumen.setText("\n".join(lineas))
        total = self.total_elementos = C.contar_elementos(capa)
        self.con_elementos.setText(f"Subir también sus {total:,} elementos".replace(",", "."))
        self.con_elementos.setEnabled(total > 0)
        self.con_elementos.setChecked(total > 0)
        if total > C.MAX_ELEMENTOS:
            self.con_elementos.setText(
                f"Subir también sus {total:,} elementos, en segundo plano: la capa aparecerá "
                "cuando estén todos dentro".replace(",", ".")
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
                self.estado.setText(self.error_de_carga or "Elige la capa que sirve de modelo.")
                return
            datos = {"name": nombre, "plantilla": plantilla["id"], "copiar_vistas": self.copiar_vistas.isChecked()}
        else:
            if self.capa_qgis.currentLayer() is None or self.geometria is None:
                self.estado.setText("Elige una capa de QGIS con geometría de punto, línea o polígono.")
                return
            datos = {"name": nombre, "geometry_type": self.geometria, "campos": self.campos}
            if self.con_elementos.isChecked() and self.total_elementos > C.MAX_ELEMENTOS:
                # La crea el servidor al importar; aquí no se pide nada.
                self.grande = datos
                self.accept()
                return

        self.botones.setEnabled(False)
        self.estado.setText("Creando la capa…")
        try:
            self.capa_creada = self.cliente.crear_capa(self.mapa["id"], datos)
        except GeosianError as exc:
            self.estado.setText(f"No se ha creado la capa. {texto_de_error(exc)}")
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
        # Geosian guarda en 2D: sin quitar Z y M, QGIS no deja añadirlos a la capa.
        geometria.get().dropZValue()
        geometria.get().dropMValue()
        if multi:
            geometria.convertToMultiType()
        nuevo = QgsFeature(campos)
        nuevo.setGeometry(geometria)
        for de_qgis, en_geosian in correspondencia.items():
            indice = campos.indexFromName(en_geosian)
            if indice >= 0:
                tipo = origen.fields().field(de_qgis).type()
                nuevo.setAttribute(indice, C.valor_para_geosian(elemento[de_qgis], tipo))
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
    errores = _motivos(destino.commitErrors())
    destino.rollBack()
    return False, f"No se ha subido nada. {errores}"


def _motivos(errores):
    """Lo que dice Geosian, sin el envoltorio de QGIS («ERROR: … not added», «Provider errors:»)."""
    propios = [
        e.strip() for e in errores
        if e.strip() and not e.strip().startswith("ERROR:") and "Provider errors" not in e
    ]
    return "; ".join(propios or [e.strip() for e in errores if e.strip()])


class ImportarCapaGrande(QgsTask):
    """Empaqueta la capa de QGIS, la sube a trozos y espera a que el servidor la importe.

    Corre en segundo plano (el gestor de tareas de QGIS enseña el avance); al acabar,
    añade la capa al proyecto o dice por qué no se ha creado.
    """

    def __init__(self, dock, conexion, mapa, origen, datos, correspondencia):
        super().__init__(f"Importar «{datos['name']}» en Geosian", QgsTask.Flag.CanCancel)
        self.dock = dock
        self.conexion = conexion
        self.mapa = mapa
        self.datos = datos
        self.correspondencia = correspondencia
        # La capa y el proyecto no se tocan desde el hilo de la tarea.
        self.fuente = QgsVectorLayerFeatureSource(origen)
        self.total = C.contar_elementos(origen)
        self.contexto = QgsProject.instance().transformContext()
        self.final = None
        self.error = None

    def _fase(self, desde, hasta):
        return lambda parte: self.setProgress(desde + (hasta - desde) * parte)

    def run(self):
        carpeta = tempfile.mkdtemp(prefix="geosian-importar-")
        try:
            ruta = os.path.join(carpeta, "capa.gpkg")
            escritos, _ = I.empaquetar(
                self.fuente, self.datos["campos"], self.correspondencia, self.datos["geometry_type"], ruta,
                avance=self._fase(0, 30), cancelado=self.isCanceled, total=self.total, contexto=self.contexto,
            )
            cliente = connections.client_for(self.conexion)
            datos = {**self.datos, "elementos": escritos}
            subida = I.subir(cliente, self.mapa["id"], datos, ruta, avance=self._fase(30, 60), cancelado=self.isCanceled)
            self.final = I.esperar(cliente, self.mapa["id"], subida["id"], avance=self._fase(60, 100), cancelado=self.isCanceled)
            return self.final["estado"] == "hecha"
        except I.Cancelado:
            return False
        except (I.NoSePuede, GeosianError) as exc:
            self.error = texto_de_error(exc)
            return False
        finally:
            shutil.rmtree(carpeta, ignore_errors=True)

    def finished(self, ok):
        _EN_MARCHA.discard(self)
        barra = self.dock.iface.messageBar()
        nombre = self.datos["name"]
        if ok:
            cliente = connections.client_for(self.conexion)
            cliente.forget_layers()
            capa = next((c for c in cliente.layers(self.mapa["id"]) if c.get("id") == self.final["capa_id"]), None)
            if capa is not None:
                self.dock.añadir_capa({"conexion": self.conexion, "mapa": self.mapa, "capa": capa})
            total = (self.final.get("progreso") or {}).get("total") or 0
            barra.pushSuccess("Geosian", f"«{nombre}» importada con sus {total:,} elementos.".replace(",", "."))
        elif self.isCanceled():
            barra.pushInfo("Geosian", f"Importación de «{nombre}» cancelada: no se ha creado nada.")
        else:
            motivo = self.error or (self.final or {}).get("error") or "no se sabe por qué"
            barra.pushWarning("Geosian", f"No se ha creado «{nombre}». {motivo}")


# Las tareas en marcha: sin una referencia, Python las recoge antes de que acaben.
_EN_MARCHA = set()


def crear_capa(dock, datos_mapa, parent=None):
    """Abre el diálogo y, al aceptar, añade la capa al proyecto (y sube sus elementos)."""
    conexion, mapa = datos_mapa["conexion"], datos_mapa["mapa"]
    dialogo = CrearCapaDialog(conexion, mapa, parent)
    if not dialogo.exec():
        return None
    if dialogo.grande:
        tarea = ImportarCapaGrande(
            dock, conexion, mapa, dialogo.capa_qgis.currentLayer(), dialogo.grande, dialogo.correspondencia
        )
        _EN_MARCHA.add(tarea)
        QgsApplication.taskManager().addTask(tarea)
        dock.iface.messageBar().pushInfo(
            "Geosian",
            f"Importando «{dialogo.grande['name']}» en segundo plano; la verás al terminar. "
            "El avance está en la barra de tareas de abajo.",
        )
        return tarea
    if not dialogo.capa_creada:
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
