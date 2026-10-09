"""Tiempo real en QGIS: lo que cambia en GCC se vuelve a pedir.

Un canal (``core/realtime.py``) por conexión, suscrito a los mapas que se han
abierto. Cuando el servidor avisa de un cambio en una capa, se recargan las
capas de QGIS que la muestran, como hace la web. Los avisos se agrupan medio
segundo: una importación manda muchos seguidos y basta con recargar una vez.
"""

from qgis.core import Qgis, QgsMessageLog, QgsProject
from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal

from ..core import connections, realtime

LOG_TAG = "Geosian"
AGRUPAR_MS = 500

_hubs = {}


def subscribe(conexion, map_id, iface=None):
    """Suscribe la conexión a un mapa, abriendo el canal si hace falta."""
    hub = _hubs.get(conexion)
    if hub is None:
        cliente = connections.client_for(conexion)
        if cliente is None or not getattr(cliente, "jwt", None):
            # Sin JWT (una sesión antigua) no hay tiempo real: hay que volver a entrar.
            QgsMessageLog.logMessage(
                f"«{conexion}»: sin tiempo real; vuelve a entrar para activarlo.", LOG_TAG, Qgis.Info
            )
            return None
        hub = _hubs[conexion] = RealtimeHub(conexion, cliente, iface)
    hub.subscribe(int(map_id))
    return hub


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
            self._avisar(f"El tiempo real de «{self._conexion}» necesita volver a entrar.")

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
