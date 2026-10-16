"""Tiempo real en QGIS: lo que cambia en GCC se vuelve a pedir.

Un canal (``core/realtime.py``) por conexión, suscrito a los mapas que se han
abierto. Cuando el servidor avisa de un cambio en una capa, se recargan las
capas de QGIS que la muestran, como hace la web. Los avisos se agrupan medio
segundo: una importación manda muchos seguidos y basta con recargar una vez.
"""

import json
import time

from qgis.core import Qgis, QgsDataProvider, QgsMessageLog, QgsProject
from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal
from qgis.PyQt.QtWidgets import QPushButton

from ..core import aggregated, connections, realtime
from ..core.errors import GeosianError
from . import celdas, contornos, formulario, leyendas

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
    for capa, de, map_id, _ in _de_geosian(QgsProject.instance().mapLayers().values()):
        if de == conexion:
            subscribe(conexion, map_id, _vigilando["iface"])


def _de_geosian(capas):
    """``(capa, conexión, mapa, capa de GCC)`` de las capas de Geosian del proyecto.

    Las de su proveedor y las agregadas (teselas del servidor), que guardan de dónde
    vienen en una propiedad de la capa.
    """
    for capa in capas:
        if not capa.isValid():
            continue
        if capa.providerType() == "geosian":
            uri = getattr(capa.dataProvider(), "layer_uri", None)
            if uri is not None:
                yield capa, uri.connection, uri.map_id, uri.layer_id
            continue
        info = _agregada(capa)
        if info:
            yield capa, info["conexion"], info["map_id"], info["layer_id"]


def _agregada(capa):
    guardada = capa.customProperty(aggregated.PROPIEDAD)
    if not guardada:
        return None
    try:
        return json.loads(guardada)
    except (TypeError, ValueError):
        return None


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
    for _, conexion, map_id, _ in _de_geosian(capas):
        subscribe(conexion, map_id, _vigilando["iface"])


def _repedir_teselas(capa, version):
    """Las teselas de una capa agregada, otra vez: con la versión nueva, como la web.

    Cambia la URI (``_v``) para que ni la caché de QGIS ni la de red sirvan las de
    antes. Sin versión en el aviso, la hora. El estilo y la leyenda se conservan.
    """
    info = _agregada(capa)
    if not info:
        return
    if info.get("tipo") == "contour":
        contornos.recalcular(capa)  # se recalcula con las celdas nuevas
        return
    if info.get("tipo") == celdas.TIPO:
        celdas.recalcular(capa, version if version is not None else int(time.time()))
        return
    renderizador = capa.renderer().clone() if capa.renderer() else None
    leyenda = capa.customProperty(leyendas.PROPIEDAD)
    capa.setDataSource(
        aggregated.uri_for(info, version if version is not None else int(time.time())),
        capa.name(), capa.providerType(), QgsDataProvider.ProviderOptions(),
    )
    if renderizador is not None:
        capa.setRenderer(renderizador)
    if leyenda:
        leyendas.poner_leyenda_de_densidad(capa, json.loads(leyenda))


_DIFERIDO = "geosian_recarga_diferida"


def recargar_capa(capa):
    """Vuelve a pedir una capa de Geosian, como la web al recibir un aviso.

    Con cambios sin guardar, no: la recarga espera a que se guarden o se descarten
    (lo pendiente se compara al confirmar con la versión que se editó, y recargar a
    mitad solo movería lo que el técnico tiene delante). En edición sin cambios sí
    se recarga, y lo que se ve pasa a ser la versión de partida.
    """
    if capa.isEditable() and capa.isModified():
        _diferir(capa, "datos")
        return False
    # Vacía la caché del proveedor y avisa a la tabla de atributos.
    capa.reload()
    proveedor = capa.dataProvider()
    if capa.isEditable() and hasattr(proveedor, "empezar_edicion"):
        proveedor.empezar_edicion()
    return True


def _diferir(capa, que):
    pendiente = set(filter(None, str(capa.property(_DIFERIDO) or "").split(",")))
    pendiente.add(que)
    capa.setProperty(_DIFERIDO, ",".join(sorted(pendiente)))
    if not capa.property(_DIFERIDO + "_conectada"):
        capa.afterCommitChanges.connect(lambda: _al_terminar(capa))
        capa.afterRollBack.connect(lambda: _al_terminar(capa))
        capa.setProperty(_DIFERIDO + "_conectada", True)


def _al_terminar(capa):
    """Tras guardar o descartar: lo que llegó mientras había cambios sin guardar."""
    pendiente = str(capa.property(_DIFERIDO) or "")
    if not pendiente or (capa.isEditable() and capa.isModified()):
        return
    capa.setProperty(_DIFERIDO, "")
    if "esquema" in pendiente:
        error = _rehacer_esquema(capa)
        if error:
            QgsMessageLog.logMessage(error, LOG_TAG, Qgis.Warning)
    else:
        recargar_capa(capa)
    capa.triggerRepaint()


def _rehacer_esquema(capa):
    """Campos y ficha nuevos. Devuelve el error, si lo hubo."""
    try:
        capa.dataProvider().reload_definition()
    except GeosianError as exc:
        return f"No se pudieron leer los campos nuevos de «{capa.name()}»: {exc}"
    capa.reload()
    formulario.rehacer(capa)
    return None


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
        self._pendientes = {}
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
            capa = int(mensaje["layer_id"])
            version = mensaje.get("tile_version")
            anterior = self._pendientes.get(capa)
            if version is None:
                self._pendientes.setdefault(capa, None)
            elif anterior is None or version > anterior:
                self._pendientes[capa] = version
            self._temporizador.start(AGRUPAR_MS)
        elif tipo == "layer_schema_changed" and mensaje.get("layer_id") is not None:
            self._recargar_esquema(int(mensaje["layer_id"]))
        elif tipo == "auth_failed":
            # El JWT ya no vale: se suelta el canal (reintentaría con el mismo) y
            # se ofrece volver a entrar, que abre uno nuevo.
            if _hubs.get(self._conexion) is self:
                del _hubs[self._conexion]
            self.stop()
            _ofrecer_entrar(self._conexion, self._iface)

    def _recargar(self):
        capas, self._pendientes = self._pendientes, {}
        for capa, conexion, _, layer_id in list(_de_geosian(QgsProject.instance().mapLayers().values())):
            if conexion != self._conexion or layer_id not in capas:
                continue
            if capa.providerType() == "geosian":
                recargar_capa(capa)
            else:
                _repedir_teselas(capa, capas[layer_id])
            capa.triggerRepaint()

    def _recargar_esquema(self, layer_id):
        """Campos y ficha nuevos en las capas y tablas de partes de esa capa."""
        for capa in QgsProject.instance().mapLayers().values():
            if capa.providerType() != "geosian" or not capa.isValid():
                continue
            proveedor = capa.dataProvider()
            uri = getattr(proveedor, "layer_uri", None)
            if uri is None or uri.connection != self._conexion or uri.layer_id != layer_id:
                continue
            if capa.isEditable() and capa.isModified():
                # Los campos nuevos moverían los de lo pendiente: al guardar o descartar.
                _diferir(capa, "esquema")
                continue
            error = _rehacer_esquema(capa)
            if error:
                self._avisar(error)
                continue
            capa.triggerRepaint()

    def _avisar(self, texto):
        if self._iface is not None:
            self._iface.messageBar().pushWarning("Geosian", texto)
        QgsMessageLog.logMessage(texto, LOG_TAG, Qgis.Warning)
