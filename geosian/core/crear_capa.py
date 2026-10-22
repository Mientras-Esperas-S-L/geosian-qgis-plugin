"""Lo que hace falta para crear en Geosian una capa a partir de una de QGIS.

Sin interfaz, para poder probarlo: el tipo de geometría que le toca, los campos que se
crean (nombre válido para Geosian, título y tipo) y los que no se pueden llevar. El LAD
que sale es mínimo a propósito: listas, partes y fotos se añaden después en la web.
"""

import re
import unicodedata

from qgis.core import QgsFeatureRequest, QgsWkbTypes
from qgis.PyQt.QtCore import QVariant

# Los tipos que admite Geosian para una capa creada desde QGIS.
TIPOS_DE_CAMPO = ("string", "text", "number", "integer", "calendar")
# Nombres que usa Geosian en las propiedades de un elemento (RESERVED_PROPERTY_KEYS e
# INTERNAL_ATTRIBUTE_KEYS del servidor): un campo así cambia de nombre.
RESERVADOS = frozenset({
    "id", "object_id", "object_status", "geometry_type", "created_at", "updated_at",
    "updated_at_iso", "longitud", "latitud", "in_succession_group", "additional_info",
    "_thumbnail", "nfc_uuid", "spatial_history_active_id", "_polygons",
})
MAX_ELEMENTOS = 20000

_ENTEROS = {QVariant.Int, QVariant.UInt, QVariant.LongLong, QVariant.ULongLong}


def tipo_de_geometria(capa):
    """El tipo de LAD que le toca a una capa de QGIS, o None si no tiene geometría útil."""
    tipo = capa.wkbType()
    familia = QgsWkbTypes.geometryType(tipo)
    if familia == QgsWkbTypes.PointGeometry:
        return "MultiPoint" if QgsWkbTypes.isMultiType(tipo) else "Point"
    if familia == QgsWkbTypes.LineGeometry:
        return "MultiLineString"
    if familia == QgsWkbTypes.PolygonGeometry:
        return "MultiPolygon"
    return None


def contar_elementos(capa):
    """Los elementos que se van a subir: los que deja ver el filtro de la capa.

    ``featureCount()`` no vale sola: con un filtro puesto, un GeoPackage sigue dando el
    total del fichero (1.078.380 con un filtro que deja 20.000), y un proveedor que no
    sabe contar da -1. En esos casos se cuentan de verdad, sin geometría ni atributos.
    """
    total = capa.featureCount()
    if total >= 0 and not capa.subsetString():
        return total
    peticion = QgsFeatureRequest().setFlags(QgsFeatureRequest.Flag.NoGeometry).setNoAttributes()
    return sum(1 for _ in capa.getFeatures(peticion))


def tipo_de_campo(campo):
    """El tipo de Geosian de un ``QgsField``, o None si no se puede llevar."""
    tipo = campo.type()
    if tipo in _ENTEROS:
        return "integer"
    if tipo == QVariant.Double:
        return "number"
    if tipo == QVariant.Date:
        return "calendar"
    # Con hora, texto: el calendario de la web guarda solo el día y la perdería al editar.
    if tipo in (QVariant.String, QVariant.Bool, QVariant.DateTime):
        return "string"
    return None


def nombre_valido(nombre, usados):
    """Un nombre que Geosian acepta: letras sin tilde, números y _, sin empezar por número."""
    limpio = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    limpio = re.sub(r"[^A-Za-z0-9_]+", "_", limpio).strip("_") or "campo"
    if limpio[0].isdigit():
        limpio = f"c_{limpio}"
    limpio = limpio[:60]
    if limpio.lower() in RESERVADOS or limpio.startswith("attr__"):
        limpio = f"{limpio}_qgis"
    base, n = limpio, 2
    while limpio.lower() in usados:
        limpio = f"{base}_{n}"
        n += 1
    usados.add(limpio.lower())
    return limpio


def campos_de(capa):
    """``(campos, fuera, correspondencia)`` de una capa de QGIS.

    - ``campos``: ``[{"name", "title", "type"}]`` para la API.
    - ``fuera``: los campos que no se pueden llevar, con el motivo.
    - ``correspondencia``: ``{nombre en QGIS: nombre en Geosian}``.
    """
    campos, fuera, correspondencia, usados = [], [], {}, set()
    # El «fid» de un GeoPackage es el número de fila del fichero, no un dato: llevarlo
    # dejaba en Geosian un campo siempre vacío.
    de_fichero = capa.dataProvider() is not None and capa.dataProvider().name() == "ogr"
    numero_de_fila = set(capa.primaryKeyAttributes()) if de_fichero else set()
    for indice, campo in enumerate(capa.fields()):
        if indice in numero_de_fila:
            continue
        tipo = tipo_de_campo(campo)
        if tipo is None:
            fuera.append(f"«{campo.name()}» ({campo.typeName() or 'tipo desconocido'})")
            continue
        nombre = nombre_valido(campo.name(), usados)
        correspondencia[campo.name()] = nombre
        campos.append({"name": nombre, "title": campo.alias() or campo.name(), "type": tipo})
    return campos, fuera, correspondencia


def valor_para_geosian(valor, tipo_qgis):
    """El valor de un campo de QGIS tal y como se guarda en su campo de Geosian."""
    if valor is None or (hasattr(valor, "isNull") and valor.isNull()):
        return None
    if tipo_qgis == QVariant.Bool:
        return "Sí" if valor else "No"
    if tipo_qgis == QVariant.DateTime and hasattr(valor, "toString"):
        return valor.toString("yyyy-MM-ddTHH:mm:ss")
    return valor
