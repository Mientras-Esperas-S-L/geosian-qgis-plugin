"""Fotos y archivos de un elemento (o de un parte) dentro de su ficha.

Es un tipo de campo propio del complemento, enganchado al campo ``id``: QGIS lo
crea al abrir la ficha y le pasa el elemento. Se hizo así y no con una función
de inicio del formulario porque esa es código Python incrustado en el proyecto,
y QGIS pregunta antes de ejecutarlo (o lo bloquea). Si el complemento no está
cargado, el campo se ve como un número más.

Las fotos se piden al ver la pestaña, no al abrir la ficha: un elemento con
muchas fotos tardaría en abrirse aunque nadie las mirase.
"""

import os
import sys
import tempfile

from qgis.core import Qgis, QgsMessageLog
from qgis.gui import (
    QgsEditorConfigWidget,
    QgsEditorWidgetFactory,
    QgsEditorWidgetWrapper,
    QgsGui,
)
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QSize, Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QIcon, QPixmap
from qgis.PyQt.QtWidgets import (
    QDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core.errors import GeosianError

WIDGET_TYPE = "GeosianMedia"
TITULO = "Fotos y archivos de Geosian"
LOG_TAG = "Geosian"
MINIATURA = 128

_registrado = False

# Lo que se crea en Python y se entrega a QGIS: si Python lo recolecta, QGIS se
# queda con un objeto destruido (se cae) o sin el código de Python (el panel no
# carga nada). Se guarda aquí hasta que Qt lo destruya.
_vivos = {}


def _retener(objeto):
    clave = id(objeto)
    _vivos[clave] = objeto
    sip.transferto(objeto, None)
    objeto.destroyed.connect(lambda *_: _vivos.pop(clave, None))
    return objeto


def register_media_widget():
    """Registra el tipo de campo. Es idempotente, como el del proveedor."""
    global _registrado
    registro = QgsGui.editorWidgetRegistry()
    if _registrado or WIDGET_TYPE in registro.factories():
        _registrado = True
        return True
    _registrado = bool(registro.registerWidget(WIDGET_TYPE, MediaWidgetFactory()))
    return _registrado


def is_available():
    return WIDGET_TYPE in QgsGui.editorWidgetRegistry().factories()


def _modulo():
    """Este módulo tal y como esté cargado ahora (ver ``provider/metadata.py``).

    El registro de QGIS no deja quitar una fábrica: al recargar el complemento,
    la vieja seguiría creando paneles con el código viejo.
    """
    return sys.modules[__name__]


class MediaWidgetFactory(QgsEditorWidgetFactory):
    def __init__(self):
        super().__init__(TITULO)

    def create(self, layer, fieldIdx, editor, parent):
        return _retener(_modulo().MediaWidgetWrapper(layer, fieldIdx, editor, parent))

    def configWidget(self, layer, fieldIdx, parent):
        return _retener(_modulo().SinAjustes(layer, fieldIdx, parent))

    def fieldScore(self, layer, fieldIdx):
        # Nunca se elige solo: lo pone el complemento en la pestaña de fotos.
        return 0


class SinAjustes(QgsEditorConfigWidget):
    """El tipo de campo no tiene nada que configurar."""

    def __init__(self, layer, fieldIdx, parent):
        super().__init__(layer, fieldIdx, parent)
        QVBoxLayout(self).addWidget(QLabel("Fotos y archivos del elemento en Geosian."))

    def config(self):
        return {}

    def setConfig(self, config):
        pass


class MediaWidgetWrapper(QgsEditorWidgetWrapper):
    """Une el campo ``id`` de la ficha con el panel de fotos."""

    def __init__(self, layer, fieldIdx, editor, parent):
        super().__init__(layer, fieldIdx, editor, parent)
        self._valor = None
        self._panel = None

    def createWidget(self, parent):
        return _retener(MediaPanel(self.layer(), parent))

    def initWidget(self, editor):
        self._panel = editor if isinstance(editor, MediaPanel) else None

    def valid(self):
        return self._panel is not None

    def value(self):
        return self._valor

    def setFeature(self, feature):
        # QGIS avisa del elemento por aquí; updateValues no se puede
        # sobrescribir desde Python.
        super().setFeature(feature)
        # Los subformularios de partes mandan un elemento vacío cuando no hay ninguno
        # seleccionado: sin ese atributo, no hay elemento del que enseñar fotos.
        idx = self.fieldIdx()
        valor = feature.attribute(idx) if 0 <= idx < len(feature.attributes()) else None
        self._valor = None if _es_nulo(valor) else valor
        if self._panel is not None:
            self._panel.set_element(self._valor)

    def setEnabled(self, enabled):
        # El id es de solo lectura y QGIS desactiva su widget; las fotos se
        # tienen que poder mirar igual.
        if self._panel is not None:
            self._panel.setEnabled(True)


class MediaPanel(QWidget):
    """Miniaturas de las fotos y lista de archivos de un elemento."""

    def __init__(self, layer, parent=None):
        super().__init__(parent)
        self._capa = layer
        self._pendiente = None
        self._cargado = None
        self._medios = []

        self.estado = QLabel("")
        self.fotos = QListWidget()
        self.fotos.setViewMode(QListWidget.ViewMode.IconMode)
        self.fotos.setIconSize(QSize(MINIATURA, MINIATURA))
        self.fotos.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.fotos.setMovement(QListWidget.Movement.Static)
        self.fotos.setSpacing(6)
        self.fotos.itemActivated.connect(self.ver_foto)
        self.ficheros = QListWidget()
        self.ficheros.itemActivated.connect(self.abrir_fichero)

        capa = QVBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        capa.addWidget(self.estado)
        capa.addWidget(QLabel("Fotos (doble clic para verla en grande)"))
        capa.addWidget(self.fotos, 3)
        capa.addWidget(QLabel("Archivos (doble clic para abrirlo)"))
        capa.addWidget(self.ficheros, 1)

    def set_element(self, fid):
        self._pendiente = fid
        if self.isVisible():
            self.cargar()

    def showEvent(self, evento):
        super().showEvent(evento)
        self.cargar()

    def cargar(self):
        """Pide las fotos y los archivos del elemento, si no se pidieron ya."""
        fid = self._pendiente
        if fid == self._cargado:
            return
        self._cargado = fid
        self.fotos.clear()
        self.ficheros.clear()
        self._medios = []
        if fid in (None, "") or _es_nulo(fid):
            self.estado.setText("El elemento aún no está guardado en Geosian.")
            return

        proveedor = self._capa.dataProvider() if self._capa is not None else None
        if proveedor is None or not hasattr(proveedor, "media_of"):
            self.estado.setText("Esta capa no es de Geosian.")
            return
        try:
            self._medios = proveedor.media_of(int(fid))
        except (GeosianError, ValueError) as exc:
            self.estado.setText(f"No se pudieron pedir las fotos: {exc}")
            return

        for item in self._medios:
            if item.kind == "image":
                self._añadir_foto(proveedor, item)
            else:
                fila = QListWidgetItem(item.name)
                fila.setData(Qt.ItemDataRole.UserRole, item)
                self.ficheros.addItem(fila)
        n_fotos, n_ficheros = self.fotos.count(), self.ficheros.count()
        self.estado.setText(
            "Sin fotos ni archivos."
            if not (n_fotos or n_ficheros)
            else f"{n_fotos} foto(s) y {n_ficheros} archivo(s)."
        )

    def _añadir_foto(self, proveedor, item):
        imagen = QPixmap()
        try:
            imagen.loadFromData(proveedor.media_bytes(item, thumb=True))
        except GeosianError as exc:
            QgsMessageLog.logMessage(f"Foto {item.id}: {exc}", LOG_TAG, Qgis.Warning)
        fila = QListWidgetItem("Portada" if item.main else "")
        if not imagen.isNull():
            fila.setIcon(QIcon(imagen.scaled(
                MINIATURA, MINIATURA,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )))
        else:
            fila.setText("(no se pudo leer)")
        fila.setData(Qt.ItemDataRole.UserRole, (item, imagen))
        self.fotos.addItem(fila)

    def ver_foto(self, fila):
        item, imagen = fila.data(Qt.ItemDataRole.UserRole)
        if item.thumb_url:
            # La galería tiene la miniatura; en grande, la foto entera.
            entera = QPixmap()
            try:
                entera.loadFromData(self._capa.dataProvider().media_bytes(item))
            except GeosianError as exc:
                self.estado.setText(f"No se pudo descargar la foto: {exc}")
                return
            if not entera.isNull():
                imagen = entera
        if imagen.isNull():
            return
        visor = QDialog(self)
        visor.setWindowTitle("Foto")
        etiqueta = QLabel()
        pantalla = self.screen().availableGeometry() if self.screen() else None
        ancho = int(pantalla.width() * 0.8) if pantalla else 1200
        alto = int(pantalla.height() * 0.8) if pantalla else 900
        etiqueta.setPixmap(imagen.scaled(
            ancho, alto, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))
        desplazable = QScrollArea()
        desplazable.setWidget(etiqueta)
        QVBoxLayout(visor).addWidget(desplazable)
        visor.resize(min(ancho, etiqueta.pixmap().width()) + 40, min(alto, etiqueta.pixmap().height()) + 40)
        visor.show()

    def abrir_fichero(self, fila):
        """Descarga el archivo a una carpeta temporal y lo abre con su programa."""
        item = fila.data(Qt.ItemDataRole.UserRole)
        proveedor = self._capa.dataProvider()
        try:
            contenido = proveedor.media_bytes(item)
        except GeosianError as exc:
            self.estado.setText(f"No se pudo descargar «{item.name}»: {exc}")
            return
        nombre = os.path.basename(item.name) or f"fichero-{item.id}"
        ruta = os.path.join(_carpeta_temporal(), f"{item.id}-{nombre}")
        with open(ruta, "wb") as destino:
            destino.write(contenido)
        _abrir_fuera(ruta)


def _es_nulo(valor):
    return hasattr(valor, "isNull") and valor.isNull()


def _carpeta_temporal():
    carpeta = os.path.join(tempfile.gettempdir(), "geosian-adjuntos")
    os.makedirs(carpeta, exist_ok=True)
    return carpeta


def _abrir_fuera(ruta):
    QDesktopServices.openUrl(QUrl.fromLocalFile(ruta))
