"""Vistas de hexágonos y H3: las celdas del servidor como polígonos enteros.

El servidor agrega los puntos en hexágonos por tesela (``agg=hex``) y manda cada hexágono
entero, sin recortar, en la tesela que contiene su centro. La capa de teselas de QGIS
recortaba cada uno al borde de su tesela y se veían costuras; la web no recorta
(``noClip``). Aquí se leen las teselas que se ven, al zoom en que las pide la web, y sus
celdas van a una capa de polígonos en memoria (EPSG:3857), que se rehace al mover o
acercar el mapa y con el tiempo real.
"""

import json
from collections import OrderedDict

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsTask,
    QgsTileMatrixSet,
    QgsVectorLayer,
)
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QTimer

from ..core import aggregated, connections, mvt, symbology

TIPO = "celdas"
CAMPOS = ("count", "weight", "density")
# Teselas que se guardan por capa para no volver a pedirlas al ir y venir.
CACHE = 256
ESPERA_MS = 250


def crear(nombre, info, estilo):
    """La capa de celdas de una vista; se rellena con ``actualizar``."""
    campos = "&".join(f"field={c}:double" for c in CAMPOS)
    capa = QgsVectorLayer(f"MultiPolygon?crs=EPSG:3857&{campos}", nombre, "memory")
    if not capa.isValid():
        return None
    guardado = {"ramp": estilo["ramp"], "color_max": estilo["color_max"]}
    capa.setCustomProperty(aggregated.PROPIEDAD, json.dumps(dict(info, tipo=TIPO, estilo=guardado)))
    capa.setRenderer(symbology.cells_renderer(guardado))
    return capa


def es_de_celdas(capa):
    try:
        return json.loads(capa.customProperty(aggregated.PROPIEDAD) or "{}").get("tipo") == TIPO
    except (TypeError, ValueError):
        return False


def extension(capa):
    """La extensión (grados) de los datos de la vista, para encuadrar: la capa nace vacía."""
    from qgis.core import QgsRectangle

    bbox = json.loads(capa.customProperty(aggregated.PROPIEDAD) or "{}").get("bbox")
    if not bbox:
        vacia = QgsRectangle()
        vacia.setNull()
        return vacia
    return QgsRectangle(*bbox)


# Por capa: la caché de teselas ya leídas, lo que se pidió la última vez, la versión de
# las teselas (tiempo real) y un contador para descartar respuestas que llegan tarde.
_estado = {}
# Las tareas en curso: QGIS no guarda la referencia de Python y se recogerían a medias.
_tareas = {}


def _de(capa):
    return _estado.setdefault(capa.id(), {"cache": OrderedDict(), "version": None, "turno": 0, "vista": None})


def actualizar(capa, extension, z):
    """Pide (en segundo plano) las teselas de ``z`` que cubren ``extension`` (EPSG:3857)
    que no estén ya, y rellena la capa con sus celdas."""
    info = json.loads(capa.customProperty(aggregated.PROPIEDAD))
    estado = _de(capa)
    z = max(0, min(aggregated.ZOOM_MAXIMO, int(z)))
    teselas = aggregated.tiles_in_extent(extension, z)[: aggregated.MAX_TESELAS]
    version = estado["version"]
    estado["vista"] = (z, tuple(teselas), version)
    estado["turno"] += 1
    turno = estado["turno"]
    faltan = [(z, x, y) for x, y in teselas if (z, x, y, version) not in estado["cache"]]
    if not faltan:
        _rellenar(capa)
        return
    cliente = connections.client_for(info["conexion"])
    if cliente is None:
        return
    extra = dict(info.get("extra") or {})
    if version is not None:
        extra["_v"] = version
    plantilla = aggregated.tile_url(info["base_url"], info["layer_id"], info["params"], extra)
    clave = capa.id()

    def al_terminar(error, leidas=None):
        _tareas.pop((clave, turno), None)
        if error is not None or leidas is None or sip.isdeleted(capa):
            return
        cache = estado["cache"]
        for tesela, celdas in leidas.items():
            cache[tesela + (version,)] = celdas
            cache.move_to_end(tesela + (version,))
        while len(cache) > CACHE:
            cache.popitem(last=False)
        if turno == estado["turno"]:
            _rellenar(capa)

    tarea = QgsTask.fromFunction(
        f"Geosian: celdas de «{capa.name()}»",
        lambda _tarea: _leer(cliente, plantilla, faltan),
        on_finished=al_terminar,
        flags=QgsTask.Flag.CanCancel,
    )
    _tareas[(clave, turno)] = tarea
    QgsApplication.taskManager().addTask(tarea)


def _leer(cliente, plantilla, teselas):
    """``{(z, x, y): [(polígonos, count, weight, density)]}``, fuera de la ventana."""
    urls = [plantilla.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))
            for z, x, y in teselas]
    leidas = {}
    for (z, x, y), cuerpo in zip(teselas, cliente.tiles(urls)):
        if cuerpo is None:
            continue  # se volverá a pedir la próxima vez
        celdas = []
        for objeto in mvt.decode_features(cuerpo).get(aggregated.CAPA_MVT, []):
            poligonos = aggregated.polygons_in_mercator(objeto["rings"], z, x, y, objeto["extent"])
            if poligonos:
                p = objeto["props"]
                celdas.append((poligonos, p.get("count"), p.get("weight"), p.get("density")))
        leidas[(z, x, y)] = celdas
    return leidas


def _rellenar(capa):
    estado = _de(capa)
    z, teselas, version = estado["vista"]
    nuevos = []
    for x, y in teselas:
        for poligonos, cuenta, peso, densidad in estado["cache"].get((z, x, y, version), []):
            elemento = QgsFeature(capa.fields())
            elemento.setGeometry(QgsGeometry.fromMultiPolygonXY(
                [[[QgsPointXY(px, py) for px, py in anillo] for anillo in poligono] for poligono in poligonos]
            ))
            elemento.setAttributes([cuenta, peso, densidad])
            nuevos.append(elemento)
    proveedor = capa.dataProvider()
    proveedor.truncate()
    proveedor.addFeatures(nuevos)
    capa.updateExtents()
    capa.triggerRepaint()


def recalcular(capa, version=None):
    """Tras un cambio (tiempo real): teselas nuevas con ``version``, como la web (``_v``)."""
    estado = _de(capa)
    estado["version"] = version
    estado["cache"].clear()
    if _lienzo is not None:
        _al_mover()
    elif estado["vista"]:
        z, teselas, _ = estado["vista"]
        actualizar(capa, _cubre(z, teselas), z)


def _cubre(z, teselas):
    limites = [aggregated.tile_bounds(z, x, y) for x, y in teselas]
    return (min(b[0] for b in limites) + 1, min(b[1] for b in limites) + 1,
            max(b[2] for b in limites) - 1, max(b[3] for b in limites) - 1)


# ----------------------------------------------------------------------
# El lienzo: al mover o acercar, se piden las teselas que se ven
# ----------------------------------------------------------------------

_lienzo = None
_temporizador = None
_MATRIZ = None


def zoom_del_lienzo(lienzo):
    """El zoom de teselas para lo que muestra el lienzo, como lo elige QGIS para sus capas
    de teselas: es el mismo que redondea deck.gl en la web (medido: 13 y 13)."""
    global _MATRIZ
    if _MATRIZ is None:
        _MATRIZ = QgsTileMatrixSet()
        _MATRIZ.addGoogleCrs84QuadTiles(0, aggregated.ZOOM_MAXIMO)
    return _MATRIZ.scaleToZoomLevel(lienzo.scale())


def vigilar(lienzo):
    """Rehace las capas de celdas al mover el lienzo y al añadirlas al proyecto."""
    global _lienzo, _temporizador
    dejar_de_vigilar()
    _lienzo = lienzo
    _temporizador = QTimer()
    _temporizador.setSingleShot(True)
    _temporizador.setInterval(ESPERA_MS)
    _temporizador.timeout.connect(_al_mover)
    lienzo.extentsChanged.connect(_temporizador.start)
    QgsProject.instance().layersAdded.connect(_al_anadir)


def dejar_de_vigilar():
    global _lienzo, _temporizador
    if _lienzo is not None and not sip.isdeleted(_lienzo):
        try:
            _lienzo.extentsChanged.disconnect(_temporizador.start)
        except TypeError:
            pass
    try:
        QgsProject.instance().layersAdded.disconnect(_al_anadir)
    except TypeError:
        pass
    if _temporizador is not None:
        _temporizador.stop()
    _lienzo = _temporizador = None


def _al_anadir(capas):
    if any(es_de_celdas(c) for c in capas) and _temporizador is not None:
        _temporizador.start()


def _al_mover():
    if _lienzo is None or sip.isdeleted(_lienzo):
        return
    ajustes = _lienzo.mapSettings()
    mercator = QgsCoordinateReferenceSystem("EPSG:3857")
    a_mercator = QgsCoordinateTransform(ajustes.destinationCrs(), mercator, QgsProject.instance())
    try:
        r = a_mercator.transformBoundingBox(ajustes.visibleExtent())
    except Exception:
        return
    z = zoom_del_lienzo(_lienzo)
    raiz = QgsProject.instance().layerTreeRoot()
    for capa in QgsProject.instance().mapLayers().values():
        if not es_de_celdas(capa):
            continue
        nodo = raiz.findLayer(capa.id())
        if nodo is not None and not nodo.isVisible():
            continue
        actualizar(capa, (r.xMinimum(), r.yMinimum(), r.xMaximum(), r.yMaximum()), z)
