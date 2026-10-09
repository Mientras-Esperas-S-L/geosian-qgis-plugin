"""El proveedor de datos.

Es la pieza que hace que una capa de QGIS sea una capa de Geosian. QGIS le
pregunta por campos, extensión y elementos igual que a cualquier otro
proveedor, y aquí se traduce a llamadas de la API.

Fase 1: solo lectura. Las capacidades de edición se declaran en la fase 2, y
hasta entonces la capa se abre en modo consulta, que es más honesto que
aceptar cambios que no se van a poder guardar.
"""

import json
import math
import threading

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsDataProvider,
    QgsFeatureRequest,
    QgsGeometry,
    QgsJsonUtils,
    QgsMessageLog,
    QgsRectangle,
    QgsVectorDataProvider,
    QgsWkbTypes,
    Qgis,
)

from ..core import connections, lad, views
from ..core import schema as S
from ..core.errors import GeosianError
from .feature_source import GeosianFeatureSource
from .uri import parse_uri

PROVIDER_KEY = "geosian"
PROVIDER_DESCRIPTION = "Geosian API"
LOG_TAG = "Geosian"

# Tamaño de página al descargar. La API rechaza el endpoint sin paginar por
# encima de 100.000 elementos, así que las capas grandes entran por páginas.
PAGE_SIZE = 5000

# Por encima de este número de elementos la capa no se descarga entera: se pide
# solo la zona que QGIS va a pintar. Una capa de un millón de árboles bloquearía
# QGIS minutos y se comería la memoria.
LARGE_LAYER = 50000

# Tope por zona en las capas grandes. Si la zona trae más, se pinta lo que llegó
# y no se da por cubierta, para volver a pedirla al acercarse.
ZONE_CAP = 50000

# Cuánto se agranda la zona pedida por cada lado. Al desplazar el mapa un poco,
# lo nuevo ya está en la caché y no hay que volver a la red.
ZONE_MARGIN = 0.25

# Lo que se carga de una capa grande cuando QGIS la pide entera, sin recuadro: la
# tabla de atributos. La web la pagina en el servidor (Listas); la tabla de QGIS no
# sabe, así que se cargan los primeros y se avisa.
TABLE_CAP = 50000

# Elementos que se quieren a la vista como mucho en una capa grande. De aquí sale
# la escala a partir de la cual la capa deja de pintarse.
VISIBLE_TARGET = 20000

MUNDO = QgsRectangle(-180.0, -90.0, 180.0, 90.0)

GEOMETRY_TYPES = {
    "points": QgsWkbTypes.Point,
    "multi_points": QgsWkbTypes.MultiPoint,
    "lines": QgsWkbTypes.LineString,
    "multi_lines": QgsWkbTypes.MultiLineString,
    "polygons": QgsWkbTypes.Polygon,
    "multi_polygons": QgsWkbTypes.MultiPolygon,
    "geometry_collections": QgsWkbTypes.GeometryCollection,
}


class CachedFeature:
    """Un elemento tal y como lo guarda el proveedor."""

    __slots__ = ("geometry", "attributes", "object_id")

    def __init__(self, geometry, attributes, object_id=None):
        self.geometry = geometry
        self.attributes = attributes
        self.object_id = object_id


class GeosianProvider(QgsVectorDataProvider):
    """Proveedor de solo lectura contra la API de Geosian."""

    # ------------------------------------------------------------------
    # Registro
    # ------------------------------------------------------------------

    @classmethod
    def providerKey(cls):
        return PROVIDER_KEY

    @classmethod
    def description(cls):
        return PROVIDER_DESCRIPTION

    @classmethod
    def createProvider(cls, uri, providerOptions, flags=QgsDataProvider.ReadFlags()):
        return GeosianProvider(uri, providerOptions, flags)

    # ------------------------------------------------------------------

    def __init__(self, uri="", providerOptions=None, flags=None):
        super().__init__(uri)
        self._uri_text = uri
        self._valid = False
        self._error = ""
        self._fields = None
        self._attr_map = {}
        self._schema = {}
        self._wkb_type = QgsWkbTypes.Unknown
        self._extent = QgsRectangle()
        self._feature_count = 0
        self._cache = {}
        self._loaded = False
        self._layer_name = ""
        # La caché se toca desde los hilos de render y desde la interfaz.
        self._lock = threading.RLock()
        self._by_zone = False
        self._zones = []
        self._tabla_cargada = False
        self._view = None
        self._filter = {}

        try:
            self._uri = parse_uri(uri)
        except ValueError as exc:
            self._error = str(exc)
            self.log_error(f"URI no válida: {exc}")
            return

        self._client = connections.client_for(self._uri.connection)
        if self._client is None:
            self._error = (
                f"No hay ninguna conexión guardada con el nombre "
                f"«{self._uri.connection}»"
            )
            self.log_error(self._error)
            return

        self._crs = QgsCoordinateReferenceSystem(self._uri.crs)
        if not self._crs.isValid():
            self._crs = QgsCoordinateReferenceSystem("EPSG:4326")

        try:
            self._load_definition()
            self._valid = True
        except GeosianError as exc:
            self._error = str(exc)
            self.log_error(f"No se pudo abrir la capa: {exc}")
        except Exception as exc:
            self._error = str(exc)
            self.log_error(f"Error inesperado al abrir la capa: {exc}")

    # ------------------------------------------------------------------
    # Carga
    # ------------------------------------------------------------------

    def _load_definition(self):
        """Campos, tipo de geometría, extensión y recuento. Sin datos."""
        if self._uri.view_id:
            self._view = self._client.layer_view(self._uri.view_id)
            self._filter, avisos = views.filter_params(self._view.get("filter_config"))
            for aviso in avisos:
                self.log_warning(f"Vista «{self._view.get('name')}»: {aviso}")
        definiciones = self._client.layer_attributes(self._uri.layer_id)
        self._schema = self._pick_schema(definiciones)
        self._fields, self._attr_map = lad.build_fields(self._schema)

        metadatos = {}
        try:
            metadatos = (
                self._client.layer_metadata(self._uri.layer_id, self._uri.map_id)
                or {}
            )
        except GeosianError as exc:
            # Sin metadatos se puede trabajar: el recuento y la extensión se
            # calculan al cargar los datos. No merece la pena fallar por esto.
            self.log_warning(f"Sin metadatos de la capa: {exc}")

        self._layer_name = metadatos.get("name") or self._schema.get("title") or ""
        self._wkb_type = self._resolve_wkb_type(metadatos)
        self._feature_count = int(metadatos.get("feature_count") or 0)
        self._by_zone = self._feature_count > LARGE_LAYER
        if self._uri.view_id and not self._by_zone:
            # El recuento de los metadatos es el de la capa entera; el de la
            # vista se sabe al descargarla.
            self._feature_count = 0

        bbox = metadatos.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            self._extent = QgsRectangle(
                float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
            )

    def _pick_schema(self, definiciones):
        """Elige la definición que toca cuando la capa tiene varias.

        Una capa puede declarar un esquema por tipo de geometría. Si la URI pide
        un tipo concreto se usa el suyo; si no, el primero, que es el caso
        normal porque casi todas las capas tienen uno solo.
        """
        if not definiciones:
            return {}

        pedido = self._uri.geometry_type
        if pedido:
            objetivo = _GEOMETRY_TYPE_TO_LAD.get(pedido)
            for definicion in definiciones:
                if definicion.get("geometry_type") == objetivo:
                    return definicion.get("schema") or {}

        return definiciones[0].get("schema") or {}

    def _resolve_wkb_type(self, metadatos):
        """Tipo de geometría de la capa.

        QGIS exige uno fijo por capa, así que si la URI no lo dice se coge el
        que traen los metadatos. Con varios tipos presentes se coge el primero
        y se avisa: el usuario debería abrir una capa por tipo.
        """
        if self._uri.geometry_type:
            return GEOMETRY_TYPES.get(self._uri.geometry_type, QgsWkbTypes.Unknown)

        tipos = metadatos.get("geometry_types") or []
        if isinstance(tipos, dict):
            tipos = list(tipos.keys())
        tipos = [t for t in tipos if t in GEOMETRY_TYPES]

        if len(tipos) > 1:
            self.log_warning(
                f"La capa tiene varios tipos de geometría ({', '.join(tipos)}); "
                f"se abre «{tipos[0]}». Añade geometry_type a la URI para elegir."
            )
        if tipos:
            self._uri.geometry_type = tipos[0]
            return GEOMETRY_TYPES[tipos[0]]

        return QgsWkbTypes.Unknown

    def _ensure_loaded(self):
        """Descarga los elementos la primera vez que hacen falta."""
        if self._loaded or self._by_zone:
            return
        with self._lock:
            if not self._loaded:
                self._load_all()

    def _load_all(self):
        try:
            total = self._download_all()
        except GeosianError as exc:
            self.log_error(f"No se pudieron descargar los datos: {exc}")
            self._loaded = True
            return

        self._loaded = True
        self._feature_count = total
        # La extensión de los metadatos es la de la capa entera; con una vista
        # se queda grande, así que se calcula con lo que el filtro devolvió.
        if self._extent.isNull() or self._extent.isEmpty() or self._view is not None:
            self._recompute_extent()

    def _download_all(self):
        """Trae la capa entera, por páginas si hace falta.

        Fase 1: se carga todo. La carga por recuadro visible depende de que la
        API acepte un filtro espacial, y está anotada como pendiente en el
        diseño; hasta entonces, las capas muy grandes tardarán en abrir.
        """
        pagina = 1
        total = 0
        while True:
            datos = self._client.geodata_paginated(
                self._uri.layer_id,
                page=pagina,
                page_size=PAGE_SIZE,
                data_type=self._uri.geometry_type,
                extra=self._filter,
            )
            elementos = _features_from(datos)
            for elemento in elementos:
                if self._store(elemento):
                    total += 1

            if len(elementos) < PAGE_SIZE:
                break
            pagina += 1
            if pagina > 200:  # 1.000.000 de elementos: algo va mal
                self.log_warning(
                    "Se alcanzó el límite de páginas al descargar la capa."
                )
                break
        return total

    def _store(self, elemento):
        """Guarda un elemento del GeoJSON en la caché. Devuelve si se guardó."""
        propiedades = elemento.get("properties") or {}
        fid = propiedades.get("id", elemento.get("id"))
        try:
            fid = int(fid)
        except (TypeError, ValueError):
            return False

        geometria = None
        geojson = elemento.get("geometry")
        if geojson:
            geometria = QgsJsonUtils.geometryFromGeoJson(json.dumps(geojson))
            if geometria is not None and geometria.isNull():
                geometria = None

        self._cache[fid] = CachedFeature(
            geometria,
            self._attributes_from(propiedades, fid),
            propiedades.get("object_id"),
        )
        return True

    def _attributes_from(self, propiedades, fid):
        """Ordena las propiedades del GeoJSON según los campos de la capa."""
        valores = []
        for campo in self._fields:
            nombre = campo.name()
            if nombre == "id":
                valores.append(fid)
                continue

            if nombre in propiedades:
                valores.append(propiedades[nombre])
                continue

            # Un atributo renombrado por colisión con un nombre reservado
            # sigue viniendo con su nombre original en los datos.
            if nombre.startswith(S.RESERVED_PREFIX):
                original = nombre[len(S.RESERVED_PREFIX):]
                if original in propiedades:
                    valores.append(propiedades[original])
                    continue

            # Los atributos del esquema pueden venir anidados bajo
            # "attributes" según el endpoint que los sirva.
            anidados = propiedades.get("attributes")
            if isinstance(anidados, dict) and nombre in anidados:
                valores.append(anidados[nombre])
                continue

            valores.append(None)
        return valores

    def _recompute_extent(self):
        extension = QgsRectangle()
        extension.setNull()
        for registro in self._cache.values():
            if registro.geometry is not None and not registro.geometry.isNull():
                extension.combineExtentWith(registro.geometry.boundingBox())
        self._extent = extension

    # ------------------------------------------------------------------
    # Lo que QGIS pregunta
    # ------------------------------------------------------------------

    def featureSource(self):
        return GeosianFeatureSource(self)

    def getFeatures(self, request=None):
        return self.featureSource().getFeatures(request or QgsFeatureRequest())

    def fields(self):
        return self._fields

    def wkbType(self):
        return self._wkb_type

    def featureCount(self):
        if not self._loaded and self._feature_count:
            return self._feature_count
        self._ensure_loaded()
        return len(self._cache)

    def extent(self):
        if self._extent.isNull() or self._extent.isEmpty() or self._view is not None:
            self._ensure_loaded()
        return self._extent

    def isValid(self):
        return self._valid

    def crs(self):
        return self._crs

    def name(self):
        return PROVIDER_KEY

    def storageType(self):
        return "Geosian REST API"

    def dataSourceUri(self, expandAuthConfig=False):
        return self._uri_text

    def capabilities(self):
        # Fase 1: solo lectura. La edición llega en la fase 2, junto con el
        # bloqueo optimista que evita pisar el trabajo de otros.
        return QgsVectorDataProvider.SelectAtId

    def error(self):
        return self._error

    def errorMessage(self):
        return self._error

    def reloadData(self):
        """Vacía la caché. Es el gancho del WebSocket y del botón de recargar."""
        with self._lock:
            self._cache.clear()
            self._zones = []
            self._loaded = False
            self._tabla_cargada = False

    def invalidate_feature(self, fid):
        """Olvida un elemento suelto, para refrescar solo lo que cambió."""
        self._cache.pop(int(fid), None)

    # ------------------------------------------------------------------
    # Agregaciones: se responden sin recorrer la capa
    # ------------------------------------------------------------------

    def uniqueValues(self, index, limit=-1):
        """Valores distintos de un campo.

        Cuando el esquema declara los valores permitidos, esa lista es la
        respuesta y no hay que tocar ni la red ni la caché. Es lo que evita que
        abrir la simbología graduada de una capa grande se la descargue entera.
        """
        campo = self._field_at(index)
        if campo is None:
            return set()

        attr = self._attr_map.get(campo.name())
        if attr:
            valores = lad.unique_values_from_schema(attr)
            if valores:
                return set(valores[:limit] if limit > 0 else valores)

        self._ensure_loaded()
        distintos = set()
        with self._lock:
            registros = list(self._cache.values())
        for registro in registros:
            if index < len(registro.attributes):
                valor = registro.attributes[index]
                if valor is not None:
                    distintos.add(valor)
            if limit > 0 and len(distintos) >= limit:
                break
        return distintos

    def minimumValue(self, index):
        return self._extreme(index, minimo=True)

    def maximumValue(self, index):
        return self._extreme(index, minimo=False)

    def _extreme(self, index, minimo):
        self._ensure_loaded()
        mejor = None
        with self._lock:
            registros = list(self._cache.values())
        for registro in registros:
            if index >= len(registro.attributes):
                continue
            valor = registro.attributes[index]
            if valor is None:
                continue
            try:
                if mejor is None:
                    mejor = valor
                elif (valor < mejor) if minimo else (valor > mejor):
                    mejor = valor
            except TypeError:
                continue
        return mejor

    def _field_at(self, index):
        if self._fields is None or index < 0 or index >= self._fields.count():
            return None
        return self._fields.at(index)

    # ------------------------------------------------------------------
    # Servicio para el iterador
    # ------------------------------------------------------------------

    def resolve_request(self, request):
        """Identificadores que satisfacen una petición de QGIS."""
        with self._lock:
            return self._resolve_request(request)

    def _resolve_request(self, request):
        fid = request.filterFid()
        if fid is not None and fid >= 0:
            self._ensure_ids([fid])
            return [fid] if fid in self._cache else []

        fids = request.filterFids()
        if fids:
            pedidos = [int(f) for f in fids]
            self._ensure_ids(pedidos)
            return [f for f in pedidos if f in self._cache]

        self._ensure_loaded()

        recuadro = request.filterRect()
        if self._by_zone and recuadro is not None and not recuadro.isNull():
            self._ensure_zone(recuadro)
        elif self._by_zone:
            # Sin recuadro (la tabla de atributos): los primeros TABLE_CAP.
            self._ensure_tabla()

        if recuadro is not None and not recuadro.isNull():
            seleccion = [
                fid
                for fid, registro in self._cache.items()
                if registro.geometry is not None
                and registro.geometry.boundingBoxIntersects(recuadro)
            ]
        else:
            seleccion = list(self._cache.keys())

        limite = request.limit()
        if limite and limite > 0:
            seleccion = seleccion[:limite]
        return seleccion

    def _ensure_ids(self, fids):
        """Pide al servidor los elementos que no estén en la caché."""
        faltan = [f for f in fids if f not in self._cache]
        if not faltan:
            return
        if self._loaded:
            # Ya se descargó todo: lo que falta es que no existe o que el
            # usuario no lo puede ver.
            return
        try:
            datos = self._client.geodata_paginated(
                self._uri.layer_id,
                page_size=max(len(faltan), 1),
                data_type=self._uri.geometry_type,
                ids=faltan,
                extra=self._filter,
            )
            for elemento in _features_from(datos):
                self._store(elemento)
        except GeosianError as exc:
            self.log_warning(f"No se pudieron pedir elementos sueltos: {exc}")

    def _ensure_zone(self, recuadro):
        """Trae lo que cae en un recuadro, si no se trajo ya."""
        for zona in self._zones:
            if zona.contains(recuadro):
                return

        # QGIS pasa el recuadro en el sistema de la capa, que es EPSG:4326.
        # Cuando no puede transformar la vista (un lienzo de tamaño cero, por
        # ejemplo) llega en las unidades del proyecto, metros, y mandarlo al
        # servidor era pedirle un polígono sin sentido que tardaba minutos.
        if not MUNDO.intersects(recuadro) or recuadro.width() > 360 or recuadro.height() > 180:
            self.log_warning(
                f"Recuadro fuera de los grados válidos ({recuadro.toString(0)}); no se pide."
            )
            return

        ampliado = QgsRectangle(recuadro)
        ampliado.grow(max(recuadro.width(), recuadro.height()) * ZONE_MARGIN)
        ampliado = ampliado.intersect(MUNDO)
        area = (
            ampliado.xMinimum(),
            ampliado.yMinimum(),
            ampliado.xMaximum(),
            ampliado.yMaximum(),
        )

        pagina = 1
        total = 0
        try:
            while True:
                datos = self._client.geodata_paginated(
                    self._uri.layer_id,
                    page=pagina,
                    page_size=PAGE_SIZE,
                    data_type=self._uri.geometry_type,
                    area=area,
                    extra=self._filter,
                )
                elementos = _features_from(datos)
                for elemento in elementos:
                    self._store(elemento)
                total += len(elementos)
                if len(elementos) < PAGE_SIZE:
                    break
                if total >= ZONE_CAP:
                    self.log_warning(
                        f"La zona trae más de {ZONE_CAP} elementos; se pinta una "
                        "parte. Acerca el mapa para verlos todos."
                    )
                    return
                pagina += 1
        except GeosianError as exc:
            self.log_warning(f"No se pudo traer la zona: {exc}")
            return

        self._zones.append(QgsRectangle(*area))

    def _ensure_tabla(self):
        """Carga hasta TABLE_CAP elementos de una capa grande, por páginas."""
        if self._tabla_cargada:
            return
        self._tabla_cargada = True
        pagina = 1
        total = 0
        try:
            while total < TABLE_CAP:
                datos = self._client.geodata_paginated(
                    self._uri.layer_id,
                    page=pagina,
                    page_size=PAGE_SIZE,
                    data_type=self._uri.geometry_type,
                    extra=self._filter,
                )
                elementos = _features_from(datos)
                for elemento in elementos:
                    self._store(elemento)
                total += len(elementos)
                if len(elementos) < PAGE_SIZE:
                    break
                pagina += 1
        except GeosianError as exc:
            self.log_warning(f"No se pudo cargar la tabla: {exc}")
            return
        if self._feature_count > total:
            self.log_warning(
                f"«{self._layer_name}» tiene {self._feature_count} elementos; la tabla "
                f"muestra los primeros {total}. Para ver otros, filtra la tabla por "
                "«objetos visibles en el mapa» y muévete por el mapa."
            )

    def suggested_min_scale(self):
        """Escala más alejada a la que conviene pintar una capa grande.

        Sale de la densidad media de la capa: a esa escala, en una pantalla
        normal caben unos ``VISIBLE_TARGET`` elementos. ``0`` si la capa es
        pequeña y se puede ver entera.
        """
        if not self._by_zone or self._extent.isNull() or self._extent.isEmpty():
            return 0
        latitud = math.radians(self._extent.center().y())
        ancho = self._extent.width() * 111320 * max(math.cos(latitud), 0.01)
        alto = self._extent.height() * 110540
        densidad = self._feature_count / max(ancho * alto, 1.0)
        # Una pantalla de unos 40 x 25 cm: a escala 1:E ve 0,1·E² m².
        escala = math.sqrt(VISIBLE_TARGET / (0.1 * densidad))
        # Redondeo hacia abajo a 1, 2 o 5 por potencia de diez.
        potencia = 10 ** math.floor(math.log10(escala))
        for paso in (5, 2, 1):
            if escala >= paso * potencia:
                return int(paso * potencia)
        return int(potencia)

    @property
    def by_zone(self):
        return self._by_zone

    def get_cached(self, fid):
        return self._cache.get(int(fid))

    @property
    def schema(self):
        return self._schema

    @property
    def view(self):
        """La vista de GCC que filtra esta capa, o ``None``."""
        return self._view

    @property
    def attr_map(self):
        """Nombre de campo de QGIS → atributo del esquema."""
        return self._attr_map

    @property
    def layer_uri(self):
        return self._uri

    # ------------------------------------------------------------------

    def log_error(self, mensaje):
        QgsMessageLog.logMessage(mensaje, LOG_TAG, Qgis.Critical)

    def log_warning(self, mensaje):
        QgsMessageLog.logMessage(mensaje, LOG_TAG, Qgis.Warning)


# Los tipos que usa la URI y los datos no se llaman igual que los del esquema.
_GEOMETRY_TYPE_TO_LAD = {
    "points": "Point",
    "multi_points": "MultiPoint",
    "lines": "LineString",
    "multi_lines": "MultiLineString",
    "polygons": "Polygon",
    "multi_polygons": "MultiPolygon",
    "geometry_collections": "GeometryCollection",
}


def _features_from(datos):
    """Saca la lista de elementos venga como venga la respuesta."""
    if not datos:
        return []
    if isinstance(datos, list):
        return datos
    if isinstance(datos, dict):
        for clave in ("features", "results", "data"):
            valor = datos.get(clave)
            if isinstance(valor, list):
                return valor
            # El endpoint paginado envuelve la colección GeoJSON.
            if isinstance(valor, dict) and isinstance(valor.get("features"), list):
                return valor["features"]
    return []
