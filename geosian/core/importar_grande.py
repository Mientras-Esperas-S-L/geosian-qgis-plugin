"""Subir a Geosian una capa de QGIS con más elementos de los que caben en un lote.

Hasta ``crear_capa.MAX_ELEMENTOS`` la capa se crea y sus elementos suben con el guardado
de siempre. Por encima, la capa se empaqueta en un GeoPackage y sube a trozos a
``maps/<id>/layers/importar/``; el servidor la importa en segundo plano y solo la enseña
si entra entera. Sin interfaz, para poder probarlo; la tarea de QGIS está en
``gui/crear_capa.py``.
"""

import hashlib
import os
import time

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
    QgsCsException,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsProject,
    QgsVectorFileWriter,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant

from . import crear_capa as C
from .errors import ConflictError, GeosianError, HttpError, NetworkError

WKB = {
    "Point": QgsWkbTypes.Point,
    "MultiPoint": QgsWkbTypes.MultiPoint,
    "MultiLineString": QgsWkbTypes.MultiLineString,
    "MultiPolygon": QgsWkbTypes.MultiPolygon,
}
TIPO_QGIS = {
    "string": QVariant.String,
    "text": QVariant.String,
    "integer": QVariant.LongLong,
    "number": QVariant.Double,
    "calendar": QVariant.Date,
}
# Las veces que se repite un trozo que no llega, y la espera antes de cada intento (crece
# con cada uno, hasta ESPERA_MAXIMA).
REINTENTOS = 5
ESPERA = 3
ESPERA_MAXIMA = 30
# Mientras el servidor importa, un corte de red no es un fallo: se sigue preguntando
# unos diez minutos antes de rendirse (la capa puede entrar igual).
REINTENTOS_AL_ESPERAR = 25
# Un 502, 503 o 504 es el servidor reiniciándose (un despliegue): se repite como un corte.
DE_PASO = (502, 503, 504)


class Cancelado(Exception):
    pass


class NoSePuede(Exception):
    """La capa no se puede subir tal cual; el mensaje dice por qué."""


def empaquetar(origen, campos, correspondencia, tipo, ruta, avance=None, cancelado=None, total=None, contexto=None):
    """Escribe ``origen`` en un GeoPackage en 4326, con los nombres y valores de Geosian.

    ``origen`` es una capa o, desde una tarea en segundo plano, su
    ``QgsVectorLayerFeatureSource`` (con ``total`` y ``contexto`` sacados antes en el hilo
    principal: la capa y el proyecto no se tocan desde otro hilo).

    Igual que ``gui.crear_capa.subir_elementos``: sin Z ni M, multi si la capa lo es, y
    los valores convertidos con ``crear_capa.valor_para_geosian``. Los elementos sin
    geometría se saltan; con una geometría no válida no se sube nada (el servidor lo
    rechazaría y la importación entera fallaría al final).

    Devuelve ``(escritos, sin_geometria)``.
    """
    if tipo not in WKB:
        raise NoSePuede("no tiene geometría de punto, línea ni polígono")
    campos_gpkg = QgsFields()
    for campo in campos:
        campos_gpkg.append(QgsField(campo["name"], TIPO_QGIS[campo["type"]]))
    destino = QgsCoordinateReferenceSystem("EPSG:4326")
    opciones = QgsVectorFileWriter.SaveVectorOptions()
    opciones.driverName = "GPKG"
    opciones.layerName = "capa"
    escritor = QgsVectorFileWriter.create(
        ruta, campos_gpkg, WKB[tipo], destino, QgsCoordinateTransformContext(), opciones
    )
    if escritor.hasError() != QgsVectorFileWriter.NoError:
        raise NoSePuede(f"No se pudo preparar el fichero: {escritor.errorMessage()}")

    if contexto is None:
        contexto = QgsProject.instance().transformContext()
    transformacion = QgsCoordinateTransform(origen.crs(), destino, contexto)
    multi = QgsWkbTypes.isMultiType(WKB[tipo])
    tipos = {de_qgis: origen.fields().field(de_qgis).type() for de_qgis in correspondencia}
    indices = {de_qgis: campos_gpkg.indexFromName(en_geosian) for de_qgis, en_geosian in correspondencia.items()}
    # Con 0 elementos, ``total or …`` llamaba a featureCount(), que una
    # QgsVectorLayerFeatureSource no tiene: la tarea entera se caía.
    if total is None:
        total = origen.featureCount()
    total = max(total, 1)
    escritos = sin_geometria = 0
    no_validas, fuera_de_su_sistema = [], []
    try:
        for n, elemento in enumerate(origen.getFeatures(), 1):
            geometria = QgsGeometry(elemento.geometry())
            if geometria.isNull() or geometria.isEmpty():
                sin_geometria += 1
                continue
            if not geometria.isGeosValid():
                no_validas.append(elemento.id())
                continue
            try:
                geometria = C.geometria_para_geosian(geometria, transformacion, multi)
            except QgsCsException:
                fuera_de_su_sistema.append(elemento.id())
                continue
            nuevo = QgsFeature(campos_gpkg)
            nuevo.setGeometry(geometria)
            for de_qgis, indice in indices.items():
                if indice >= 0:
                    nuevo.setAttribute(indice, C.valor_para_geosian(elemento[de_qgis], tipos[de_qgis]))
            if not escritor.addFeature(nuevo):
                raise NoSePuede(f"No se pudo escribir el elemento {elemento.id()}: {escritor.errorMessage()}")
            escritos += 1
            if n % 2000 == 0:
                if cancelado and cancelado():
                    raise Cancelado()
                if avance:
                    avance(n / total)
    finally:
        del escritor
    if no_validas:
        muestra = ", ".join(str(i) for i in no_validas[:5])
        raise NoSePuede(
            f"{len(no_validas)} elementos tienen la geometría rota (por ejemplo: {muestra}). "
            "Arréglalos en QGIS (Vectorial › Herramientas de geometría › Reparar geometrías) y repite."
        )
    if fuera_de_su_sistema:
        raise NoSePuede(C.fuera_de_su_sistema(fuera_de_su_sistema))
    return escritos, sin_geometria


def huella(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def _de_paso(exc):
    """Un fallo que se arregla solo: sin red o el servidor reiniciándose."""
    return isinstance(exc, NetworkError) or (isinstance(exc, HttpError) and exc.status in DE_PASO)


def _con_reintentos(hacer, cancelado, espera=None, intentos=REINTENTOS):
    for intento in range(intentos):
        try:
            return hacer()
        except GeosianError as exc:
            if not _de_paso(exc) or intento == intentos - 1:
                raise
            pausa = min((ESPERA if espera is None else espera) * (intento + 1), ESPERA_MAXIMA)
            for _ in range(int(pausa * 10)):
                if cancelado and cancelado():
                    raise Cancelado()
                time.sleep(0.1)


def _confirmar(cliente, map_id, id_subida, cancelado, espera=None):
    """Confirma la subida sin poder confirmarla dos veces.

    Si la respuesta no llega, puede que la confirmación sí: repetirla daba 409 («ya está
    confirmada») y QGIS decía que había fallado mientras la capa se importaba. Antes de
    repetir se pregunta en qué está.
    """
    def una_vez():
        try:
            return cliente.confirmar_importacion(map_id, id_subida)
        except GeosianError as exc:
            if not (_de_paso(exc) or isinstance(exc, ConflictError)):
                raise
            estado = _con_reintentos(lambda: cliente.importacion(map_id, id_subida), cancelado, espera)
            if estado["estado"] != "subiendo":
                return estado
            raise

    return _con_reintentos(una_vez, cancelado, espera)


def _cancelar(cliente, map_id, id_subida):
    """Avisa al servidor de que la subida no sigue. Sin el aviso, la subida a medias cuenta
    como «en marcha» 24 horas y no deja empezar otra."""
    try:
        cliente.cancelar_importacion(map_id, id_subida)
    except GeosianError:
        pass


def subir(cliente, map_id, datos, ruta, avance=None, cancelado=None, espera=None):
    """Sube el GeoPackage a trozos y confirma. Devuelve la subida confirmada.

    Un trozo que no llega por la red se repite; los que ya llegaron no se mandan otra vez
    (el servidor dice cuáles ``faltan``).
    """
    tamano = os.path.getsize(ruta)
    subida = cliente.importar_capa(map_id, {**datos, "tamano": tamano, "huella": huella(ruta)})
    # Pase lo que pase a partir de aquí (cancelar, la red, la sesión, un fallo propio), la
    # subida no se queda abierta en el servidor.
    try:
        with open(ruta, "rb") as f:
            faltan = list(subida["faltan"])
            while faltan:
                for numero in faltan:
                    if cancelado and cancelado():
                        raise Cancelado()
                    f.seek(numero * subida["trozo"])
                    trozo = f.read(subida["trozo"])
                    estado = _con_reintentos(
                        lambda n=numero, t=trozo: cliente.importar_trozo(map_id, subida["id"], n, t), cancelado, espera
                    )
                    if avance:
                        avance(1 - len(estado["faltan"]) / subida["trozos"])
                faltan = _con_reintentos(lambda: cliente.importacion(map_id, subida["id"]), cancelado, espera)["faltan"]
        return _confirmar(cliente, map_id, subida["id"], cancelado, espera)
    except BaseException:
        _cancelar(cliente, map_id, subida["id"])
        raise


def esperar(cliente, map_id, id_subida, avance=None, cancelado=None, cada=3):
    """Espera a que el servidor acabe de importar. Devuelve el estado final."""
    while True:
        estado = _con_reintentos(
            lambda: cliente.importacion(map_id, id_subida), cancelado, intentos=REINTENTOS_AL_ESPERAR
        )
        if estado["estado"] not in ACTIVAS:
            return estado
        progreso = estado.get("progreso") or {}
        if avance and progreso.get("total"):
            avance(progreso["hechos"] / progreso["total"])
        if cancelado and cancelado():
            _cancelar(cliente, map_id, id_subida)
            _hasta_que_pare(cliente, map_id, id_subida, cada)
            raise Cancelado()
        for _ in range(int(cada * 10)):
            time.sleep(0.1)


ACTIVAS = ("subiendo", "importando")


def _hasta_que_pare(cliente, map_id, id_subida, cada, veces=20):
    """Tras cancelar una importación en curso, espera a que el servidor la corte de verdad
    (lo ve en su siguiente aviso de progreso, cada pocos segundos): así «cancelada» es
    cierto y la siguiente subida no choca con ella."""
    for _ in range(veces):
        try:
            if cliente.importacion(map_id, id_subida)["estado"] not in ACTIVAS:
                return
        except GeosianError:
            return
        for _ in range(int(max(cada, 0.5) * 10)):
            time.sleep(0.1)
