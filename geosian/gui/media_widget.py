"""Fotos y archivos de un elemento (o de un parte) dentro de su ficha.

Es un tipo de campo propio del complemento, enganchado al campo ``adjuntos_nuevos``
(o al ``id`` en los partes): QGIS lo crea al abrir la ficha y le pasa el elemento. Se hizo así y no con una función
de inicio del formulario porque esa es código Python incrustado en el proyecto,
y QGIS pregunta antes de ejecutarlo (o lo bloquea). Si el complemento no está
cargado, el campo se ve como un número más.

Las fotos se piden al ver la pestaña, no al abrir la ficha: un elemento con
muchas fotos tardaría en abrirse aunque nadie las mirase.

En un elemento nuevo, con la capa en edición y permiso de alta, la pestaña deja
añadir fotos y archivos a cada campo del LAD. Cada uno se sube a Geosian al
añadirlo y su referencia queda en ``adjuntos_nuevos`` (``core/adjuntos.py``); el
alta la lleva al confirmar. Las fotos se reducen antes, como en la web.
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
from qgis.PyQt.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QIcon, QImage, QPainter, QPixmap
from qgis.PyQt.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core import adjuntos as A
from ..core import schema as S
from ..core.errors import GeosianError

WIDGET_TYPE = "GeosianMedia"
TITULO = "Fotos y archivos de Geosian"
LOG_TAG = "Geosian"
MINIATURA = 128

# Como ResponsiveImageUploader.jsx: el lado mayor a 1600 px, en JPEG al 72 %; lo que
# ya es pequeño y JPEG o PNG va tal cual.
LADO_MAXIMO = 1600
CALIDAD_JPEG = 72
TAL_CUAL_HASTA = 200 * 1024

_registrado = False

# Distinto de cualquier id: obliga a volver a pintar el panel.
_SIN_CARGAR = object()

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
    """Une el campo de la ficha (``adjuntos_nuevos`` o ``id``) con el panel de fotos."""

    def __init__(self, layer, fieldIdx, editor, parent):
        super().__init__(layer, fieldIdx, editor, parent)
        self._valor = None
        self._panel = None

    def _de_adjuntos(self):
        return self.field().name() == S.CAMPO_ADJUNTOS

    def createWidget(self, parent):
        return _retener(MediaPanel(self.layer(), parent))

    def initWidget(self, editor):
        self._panel = editor if isinstance(editor, MediaPanel) else None
        if self._panel is not None:
            self._panel.al_cambiar = self._cambiado

    def valid(self):
        return self._panel is not None

    def value(self):
        if self._de_adjuntos():
            return A.escribir(self._panel.nuevos) if self._panel is not None else self._valor
        return self._valor

    def _cambiado(self):
        self.emitValueChanged()

    def setFeature(self, feature):
        # QGIS avisa del elemento por aquí; updateValues no se puede
        # sobrescribir desde Python.
        super().setFeature(feature)
        # Los subformularios de partes mandan un elemento vacío cuando no hay ninguno
        # seleccionado: sin ese atributo, no hay elemento del que enseñar fotos.
        idx = self.fieldIdx()
        valor = feature.attribute(idx) if 0 <= idx < len(feature.attributes()) else None
        self._valor = None if _es_nulo(valor) else valor
        if self._de_adjuntos():
            i = feature.fields().indexOf("id")
            fid = feature.attribute(i) if 0 <= i < len(feature.attributes()) else None
            fid = None if fid is None or _es_nulo(fid) else fid
            nuevos = A.leer(self._valor)
        else:
            fid, nuevos = self._valor, []
        if self._panel is not None:
            self._panel.set_element(fid, nuevos)

    def setEnabled(self, enabled):
        # El campo es interno y QGIS puede desactivar su widget; las fotos se
        # tienen que poder mirar igual. Añadir, solo si la ficha se puede editar.
        if self._panel is not None:
            self._panel.setEnabled(True)
            self._panel.set_editable(bool(enabled) and self._de_adjuntos())


class MediaPanel(QWidget):
    """Miniaturas de las fotos y lista de archivos de un elemento."""

    def __init__(self, layer, parent=None):
        super().__init__(parent)
        self._capa = layer
        self._pendiente = None
        self._cargado = _SIN_CARGAR
        self._medios = []
        # Lo añadido a un elemento nuevo, ya subido (entradas de core/adjuntos.py).
        self.nuevos = []
        self._editable = False
        self.al_cambiar = None

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

        # Un botón por campo de fotos o archivos del LAD, solo en un elemento nuevo.
        self.botones = QWidget()
        self._fila_botones = QHBoxLayout(self.botones)
        self._fila_botones.setContentsMargins(0, 0, 0, 0)
        self.quitar = QPushButton("Quitar lo seleccionado")
        self.quitar.clicked.connect(self.quitar_seleccion)
        self.botones.setVisible(False)

        capa = QVBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        capa.addWidget(self.estado)
        capa.addWidget(self.botones)
        capa.addWidget(QLabel("Fotos (doble clic para verla en grande)"))
        capa.addWidget(self.fotos, 3)
        capa.addWidget(QLabel("Archivos (doble clic para abrirlo)"))
        capa.addWidget(self.ficheros, 1)

    def set_element(self, fid, nuevos=()):
        nuevos = list(nuevos)
        if nuevos != self.nuevos:
            self._cargado = _SIN_CARGAR
        self._pendiente = fid
        self.nuevos = nuevos
        if self.isVisible():
            self.cargar()

    def set_editable(self, editable):
        if editable != self._editable:
            self._editable = editable
            self._cargado = _SIN_CARGAR
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
            self._cargar_nuevo()
            return
        self.botones.setVisible(False)

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

    def _cargar_nuevo(self):
        """Un elemento nuevo: lo añadido hasta ahora y, si se puede, los botones."""
        proveedor = self._capa.dataProvider() if self._capa is not None else None
        campos = proveedor.campos_de_adjuntos() if hasattr(proveedor, "campos_de_adjuntos") else []
        puede = self._editable and bool(campos) and proveedor.puede_dar_altas()
        self._poner_botones(campos if puede else [])
        titulos = {nombre: titulo for nombre, titulo, _ in campos}
        for entrada in self.nuevos:
            titulo = titulos.get(entrada["campo"], entrada["campo"])
            if entrada.get("tipo") == "foto":
                imagen = QPixmap(entrada.get("ruta") or "")
                fila = QListWidgetItem(titulo)
                if not imagen.isNull():
                    fila.setIcon(QIcon(imagen.scaled(
                        MINIATURA, MINIATURA,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )))
                fila.setData(Qt.ItemDataRole.UserRole, (None, imagen))
                fila.setData(Qt.ItemDataRole.UserRole + 1, entrada["adjunto"])
                self.fotos.addItem(fila)
            else:
                fila = QListWidgetItem(f"{entrada.get('nombre')} ({titulo})")
                fila.setData(Qt.ItemDataRole.UserRole + 1, entrada["adjunto"])
                self.ficheros.addItem(fila)
        if self.nuevos:
            self.estado.setText(
                f"Elemento nuevo: {len(self.nuevos)} foto(s) o archivo(s) añadidos; se guardan "
                "en Geosian al guardar la edición."
            )
        elif puede:
            self.estado.setText("Elemento nuevo: añade sus fotos y archivos con los botones.")
        else:
            self.estado.setText("El elemento aún no está guardado en Geosian.")

    def _poner_botones(self, campos):
        while self._fila_botones.count():
            hijo = self._fila_botones.takeAt(0).widget()
            if hijo is not None and hijo is not self.quitar:
                hijo.deleteLater()
        for nombre, titulo, tipo in campos:
            boton = QPushButton(f"Añadir {'fotos' if tipo == 'foto' else 'archivos'} a «{titulo}»…")
            boton.clicked.connect(lambda _=False, n=nombre, t=titulo, k=tipo: self.añadir(n, t, k))
            self._fila_botones.addWidget(boton)
        if campos:
            self._fila_botones.addWidget(self.quitar)
            self._fila_botones.addStretch(1)
        self.botones.setVisible(bool(campos))

    def añadir(self, campo, titulo, tipo, rutas=None):
        """Sube a Geosian las fotos o archivos elegidos para ``campo`` y los apunta.

        ``rutas`` es para las pruebas; sin ellas se preguntan al usuario.
        """
        if rutas is None:
            filtro = "Imágenes (*.jpg *.jpeg *.png *.webp *.bmp *.gif *.tif *.tiff)" if tipo == "foto" else ""
            rutas, _ = QFileDialog.getOpenFileNames(self, f"Añadir a «{titulo}»", "", filtro)
        if not rutas:
            return
        ya = sum(1 for e in self.nuevos if e["campo"] == campo)
        if ya + len(rutas) > A.MAXIMO_POR_CAMPO:
            self.estado.setText(f"«{titulo}» admite como mucho {A.MAXIMO_POR_CAMPO}.")
            return
        proveedor = self._capa.dataProvider()
        fallos = []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for ruta in rutas:
                nombre = os.path.basename(ruta)
                try:
                    if tipo == "foto":
                        contenido, nombre = preparar_foto(ruta)
                    else:
                        with open(ruta, "rb") as origen:
                            contenido = origen.read()
                except (OSError, ValueError) as exc:
                    fallos.append(f"{nombre}: {exc}")
                    continue
                try:
                    respuesta = proveedor.subir_adjunto(campo, nombre, contenido)
                except GeosianError as exc:
                    from ..provider.edicion import texto_de_error

                    fallos.append(f"{nombre}: {texto_de_error(exc)}")
                    continue
                local = ruta
                if tipo == "foto":
                    # La miniatura sale de lo que se subió, no del original.
                    local = os.path.join(_carpeta_temporal(), f"{respuesta['adjunto']}.jpg")
                    with open(local, "wb") as destino:
                        destino.write(contenido)
                self.nuevos.append({
                    "campo": campo, "adjunto": respuesta["adjunto"], "nombre": nombre,
                    "tipo": tipo, "ruta": local,
                })
        finally:
            QApplication.restoreOverrideCursor()
        self._cargado = _SIN_CARGAR
        self.cargar()
        if fallos:
            self.estado.setText("No se pudo añadir: " + "; ".join(fallos))
        if self.al_cambiar is not None:
            self.al_cambiar()

    def quitar_seleccion(self):
        """Quita de lo añadido lo seleccionado. En Geosian caduca solo."""
        quitar = {
            fila.data(Qt.ItemDataRole.UserRole + 1)
            for lista in (self.fotos, self.ficheros)
            for fila in lista.selectedItems()
        } - {None}
        if not quitar:
            return
        self.nuevos = [e for e in self.nuevos if e["adjunto"] not in quitar]
        self._cargado = _SIN_CARGAR
        self.cargar()
        if self.al_cambiar is not None:
            self.al_cambiar()

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
        if item is not None and item.thumb_url:
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
        if item is None:
            # Uno añadido a un elemento nuevo: está en el disco de quien lo añadió.
            entrada = next(
                (e for e in self.nuevos if e["adjunto"] == fila.data(Qt.ItemDataRole.UserRole + 1)), None
            )
            if entrada and entrada.get("ruta") and os.path.exists(entrada["ruta"]):
                _abrir_fuera(entrada["ruta"])
            return
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


def preparar_foto(ruta):
    """``(bytes, nombre)`` de una foto lista para subir, como la web: el lado mayor a
    1600 px y en JPEG al 72 %, salvo lo pequeño en JPEG o PNG, que va tal cual."""
    nombre = os.path.basename(ruta)
    imagen = QImage(ruta)
    if imagen.isNull():
        raise ValueError("no es una imagen que se pueda leer")
    extension = os.path.splitext(nombre)[1].lower()
    if (
        os.path.getsize(ruta) <= TAL_CUAL_HASTA
        and extension in (".jpg", ".jpeg", ".png")
        and max(imagen.width(), imagen.height()) <= LADO_MAXIMO
    ):
        with open(ruta, "rb") as origen:
            return origen.read(), nombre
    if max(imagen.width(), imagen.height()) > LADO_MAXIMO:
        imagen = imagen.scaled(
            LADO_MAXIMO, LADO_MAXIMO,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    if imagen.hasAlphaChannel():
        # JPEG no tiene transparencia: sobre blanco, como el lienzo de la web.
        fondo = QImage(imagen.size(), QImage.Format.Format_RGB32)
        fondo.fill(Qt.GlobalColor.white)
        pintor = QPainter(fondo)
        pintor.drawImage(0, 0, imagen)
        pintor.end()
        imagen = fondo
    datos = QByteArray()
    salida = QBuffer(datos)
    salida.open(QIODevice.OpenModeFlag.WriteOnly)
    if not imagen.save(salida, "JPEG", CALIDAD_JPEG):
        raise ValueError("no se pudo pasar a JPEG")
    salida.close()
    return bytes(datos), os.path.splitext(nombre)[0] + ".jpg"


def _es_nulo(valor):
    return hasattr(valor, "isNull") and valor.isNull()


def _carpeta_temporal():
    carpeta = os.path.join(tempfile.gettempdir(), "geosian-adjuntos")
    os.makedirs(carpeta, exist_ok=True)
    return carpeta


def _abrir_fuera(ruta):
    QDesktopServices.openUrl(QUrl.fromLocalFile(ruta))
