"""Tiempo real en QGIS: lo que cambia en GCC se vuelve a pedir.

Un canal (``core/realtime.py``) por conexión, suscrito a los mapas que se han
abierto. Cuando el servidor avisa de un cambio en una capa, se recargan las
capas de QGIS que la muestran, como hace la web. Los avisos se agrupan medio
segundo: una importación manda muchos seguidos y basta con recargar una vez.
"""

from qgis.core import Qgis, QgsMessageLog, QgsProject
from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal
from qgis.PyQt.QtWidgets import QPushButton

from ..core import connections, realtime

LOG_TAG = "Geosian"
AGRUPAR_MS = 500

_hubs = {}


def subscribe(conexion, map_id, iface=None):
    """Suscribe la conexión a un mapa, abriendo el canal si hace falta."""
    hub = _hubs.get(conexion)
    if hub is None:
        cliente = connections.client_for(conexion)
        if cliente is None:
            return None
        if not getattr(cliente, "jwt", None):
            # Sin JWT (una sesión antigua) no hay tiempo real: hay que volver a entrar.
            _ofrecer_entrar(conexion, iface)
            return None
        hub = _hubs[conexion] = RealtimeHub(conexion, cliente, iface)
    hub.subscribe(int(map_id))
    return hub


def reconnect(conexion):
    """Tras volver a entrar: canal nuevo con el JWT nuevo y los mapas de sus capas."""
    hub = _hubs.pop(conexion, None)
    if hub is not None:
        hub.stop()
    _quitar_aviso(conexion, _vigilando["iface"])
    for capa in QgsProject.instance().mapLayers().values():
        if capa.providerType() != "geosian" or not capa.isValid():
            continue
        uri = getattr(capa.dataProvider(), "layer_uri", None)
        if uri is not None and uri.connection == conexion:
            subscribe(conexion, uri.map_id, _vigilando["iface"])


_vigilando = {"iface": None, "activo": False, "pedir": None}
_PROPIEDAD = "geosian_tiempo_real"


def _ofrecer_entrar(conexion, iface):
    """Un aviso con «Volver a entrar», uno por conexión mientras se vea.

    Con la sesión caducada no: ese aviso ya lo da ``gui/sesion.py`` y al volver a
    entrar se reconecta igual.
    """
    texto = (
        f"«{conexion}» no tiene tiempo real: los cambios hechos en GCC no llegarán "
        "solos hasta volver a entrar."
    )
    QgsMessageLog.logMessage(texto, LOG_TAG, Qgis.Info)
    iface = iface or _vigilando["iface"]
    if iface is None or conexion in connections.expired():
        return
    barra = iface.messageBar()
    if conexion in {w.property(_PROPIEDAD) for w in barra.items() if w is not None}:
        return
    aviso = barra.createMessage("Geosian", texto)
    aviso.setProperty(_PROPIEDAD, conexion)
    pedir = _vigilando["pedir"]
    if pedir is not None:
        boton = QPushButton("Volver a entrar")
        boton.clicked.connect(lambda _=False, n=conexion: pedir(n))
        aviso.layout().addWidget(boton)
    barra.pushWidget(aviso, Qgis.Warning)


def _quitar_aviso(conexion, iface):
    if iface is None:
        return
    barra = iface.messageBar()
    for aviso in list(barra.items()):
        if aviso is not None and aviso.property(_PROPIEDAD) == conexion:
            barra.popWidget(aviso)


def watch_project(iface=None, pedir=None):
    """Se suscribe a los mapas de toda capa de Geosian que entre en el proyecto.

    Da igual cómo entre: desde el panel o al abrir un proyecto guardado.

    Args:
        pedir: lo que abre el diálogo para volver a entrar; recibe el nombre de
            la conexión. Sin él, el aviso de «sin tiempo real» no lleva botón.
    """
    _vigilando["iface"] = iface
    _vigilando["pedir"] = pedir
    if not _vigilando["activo"]:
        QgsProject.instance().layersAdded.connect(_al_añadir_capas)
        _vigilando["activo"] = True


def unwatch_project():
    if _vigilando["activo"]:
        try:
            QgsProject.instance().layersAdded.disconnect(_al_añadir_capas)
        except TypeError:
            pass
        _vigilando["activo"] = False


def _al_añadir_capas(capas):
    for capa in capas:
        if capa.providerType() != "geosian" or not capa.isValid():
            continue
        uri = getattr(capa.dataProvider(), "layer_uri", None)
        if uri is not None:
            subscribe(uri.connection, uri.map_id, _vigilando["iface"])


def stop_all():
    for hub in list(_hubs.values()):
        hub.stop()
    _hubs.clear()


class RealtimeHub(QObject):
    mensaje = pyqtSignal(dict)

    def __init__(self, conexion, cliente, iface=None):
        super().__init__()
        self._conexion = conexion
        self._iface = iface
        self._pendientes = set()
        self._temporizador = QTimer(self)
        self._temporizador.setSingleShot(True)
        self._temporizador.timeout.connect(self._recargar)
        # La señal cruza del hilo del canal al de la interfaz.
        self.mensaje.connect(self._procesar)
        url = connections.ws_url(conexion) or realtime.ws_url(cliente.base_url)
        self._canal = realtime.LayerDataChannel(
            url, cliente.jwt, self.mensaje.emit, origin=realtime.origin_of(cliente.base_url)
        )
        self._canal.start()

    def subscribe(self, map_id):
        self._canal.subscribe(map_id)

    def stop(self):
        self._canal.stop()
        self._temporizador.stop()

    def _procesar(self, mensaje):
        tipo = mensaje.get("type")
        if tipo == "layer_data_changed" and mensaje.get("layer_id") is not None:
            self._pendientes.add(int(mensaje["layer_id"]))
            self._temporizador.start(AGRUPAR_MS)
        elif tipo == "layer_schema_changed":
            self._avisar(
                "Los campos de una capa han cambiado en GCC. Vuelve a añadirla para verlos."
            )
        elif tipo == "auth_failed":
            # El JWT ya no vale: se suelta el canal (reintentaría con el mismo) y
            # se ofrece volver a entrar, que abre uno nuevo.
            if _hubs.get(self._conexion) is self:
                del _hubs[self._conexion]
            self.stop()
            _ofrecer_entrar(self._conexion, self._iface)

    def _recargar(self):
        capas, self._pendientes = self._pendientes, set()
        for capa in QgsProject.instance().mapLayers().values():
            if capa.providerType() != "geosian":
                continue
            uri = getattr(capa.dataProvider(), "layer_uri", None)
            if uri is None or uri.connection != self._conexion or uri.layer_id not in capas:
                continue
            # Vacía la caché del proveedor y avisa a la tabla de atributos.
            capa.reload()
            capa.triggerRepaint()

    def _avisar(self, texto):
        if self._iface is not None:
            self._iface.messageBar().pushWarning("Geosian", texto)
        QgsMessageLog.logMessage(texto, LOG_TAG, Qgis.Warning)
