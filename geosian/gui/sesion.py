"""Sesiones caducadas: avisar y recuperar las capas al volver a entrar.

Al reabrir un proyecto con la sesión caducada, sus capas de Geosian quedan «no
disponibles» (``provider.py`` lo anota en ``connections.mark_expired``). QGIS
conserva su estilo, su formulario y su sitio en el árbol, así que basta con
volver a crear el proveedor cuando haya sesión.
"""

from qgis.core import Qgis, QgsDataProvider, QgsProject
from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.PyQt.QtWidgets import QPushButton

from ..core import connections
from ..provider.uri import parse_uri


def expired():
    return connections.expired()


def clear_expired(nombre=None):
    connections.clear_expired(nombre)


def repair_layers(nombre, capas=None):
    """Vuelve a abrir las capas de una conexión tras volver a entrar.

    Las no disponibles se vuelven a crear; las que se abrieron bien pero se
    quedaron sin datos al caducar la sesión, se recargan. Devuelve cuántas
    quedaron disponibles.
    """
    if capas is None:
        capas = list(QgsProject.instance().mapLayers().values())
    reparadas = 0
    pendientes = 0
    for capa in capas:
        if capa.providerType() != "geosian":
            continue
        try:
            if parse_uri(capa.source()).connection != nombre:
                continue
        except ValueError:
            continue
        if capa.isValid():
            capa.reload()
            capa.triggerRepaint()
            continue
        capa.setDataSource(capa.source(), capa.name(), "geosian", QgsDataProvider.ProviderOptions())
        if capa.isValid():
            reparadas += 1
        else:
            pendientes += 1
    if not pendientes:
        connections.clear_expired(nombre)
    return reparadas


def offer_reconnect(iface, pedir):
    """Un aviso con «Volver a entrar» por cada conexión con la sesión caducada.

    Args:
        pedir: lo que abre el diálogo de la conexión; recibe su nombre.
    """
    for nombre in sorted(connections.expired()):
        aviso = iface.messageBar().createMessage(
            "Geosian",
            f"La sesión de «{nombre}» ha caducado: sus capas están sin datos hasta "
            "volver a entrar.",
        )
        boton = QPushButton("Volver a entrar")
        boton.clicked.connect(lambda _=False, n=nombre: pedir(n))
        aviso.layout().addWidget(boton)
        iface.messageBar().pushWidget(aviso, Qgis.Warning)


class _Avisador(QObject):
    """Lleva el aviso al hilo de la interfaz: la sesión puede caducar al pintar."""

    caducada = pyqtSignal(str)


_avisador = {"objeto": None, "oyente": None}


def watch_expired(funcion):
    """Llama a ``funcion(nombre)`` la primera vez que caduca una conexión."""
    unwatch_expired()
    avisador = _Avisador()
    avisador.caducada.connect(funcion)

    def oyente(nombre):
        avisador.caducada.emit(nombre)

    # Se guarda la misma función que se registra: un «avisador.caducada.emit»
    # nuevo no es igual al registrado, no se quitaría y quedaría llamando a un
    # objeto de Qt ya destruido.
    _avisador.update(objeto=avisador, oyente=oyente)
    connections.add_expired_listener(oyente)


def unwatch_expired():
    if _avisador["oyente"] is not None:
        connections.remove_expired_listener(_avisador["oyente"])
    _avisador.update(objeto=None, oyente=None)
