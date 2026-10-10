"""El proveedor de datos.

Es la pieza que hace que una capa de QGIS sea una capa de Geosian. QGIS le
pregunta por campos, extensión y elementos igual que a cualquier otro
proveedor, y aquí se traduce a llamadas de la API.

Fase 1: solo lectura. Las capacidades de edición se declaran en la fase 2, y
hasta entonces la capa se abre en modo consulta, que es más honesto que
aceptar cambios que no se van a poder guardar.
"""

import math
import re
import threading
import time

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsDataProvider,
    QgsExpressionContext,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsFields,
    QgsMessageLog,
    QgsRectangle,
    QgsVectorDataProvider,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import (
    QCoreApplication,
    QObject,
    Qt,
    QTimeZone,
    QVariant,
    pyqtSignal,
)

from ..core import compat, connections, definitions, lad, media, views
from ..core import schema as S
from ..core.client import API_PREFIX
from ..core.errors import (
    AuthError,
    ForbiddenError,
    GeosianError,
    NetworkError,
    NotFoundError,
)
from .feature_source import GeosianFeatureSource
from .subset import parse as parse_subset
from .subset import server_params
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
# sabe, así que se cargan los primeros y se avisa. Una sola página: QGIS la carga en
# el hilo de la ventana y cada página la congela ~1 s (50.000 eran 15 s en Nueva York).
TABLE_CAP = PAGE_SIZE

# Elementos que se quieren a la vista como mucho en una capa grande. De aquí sale
# la escala a partir de la cual la capa deja de pintarse.
VISIBLE_TARGET = 20000

MUNDO = QgsRectangle(-180.0, -90.0, 180.0, 90.0)

# Página al pedir partes. La API no pone tope y un elemento rara vez pasa de unas
# decenas, así que casi siempre basta una.
INFO_PAGE_SIZE = 1000

# Lo que pide la ficha de un elemento a la tabla de sus partes: la relación de
# QGIS filtra por «"geodata_id" = N» (o un IN, si son varios).
_FILTRO_ELEMENTO = re.compile(r'"geodata_id"\s*(?:=\s*\'?(\d+)|IN\s*\(([^)]*)\))', re.IGNORECASE)

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

    __slots__ = ("attributes", "geometry", "object_id")

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
    def createProvider(cls, uri, providerOptions, flags=None):
        if flags is None:
            flags = QgsDataProvider.ReadFlags()
        return GeosianProvider(uri, providerOptions, flags)

    # ------------------------------------------------------------------

    def __init__(self, uri="", providerOptions=None, flags=None):
        super().__init__(uri)
        self._uri_text = uri
        self._valid = False
        self._error = ""
        self._fields = None
        self._listas = None
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
        self._tabla_avisada = False
        # Lo que había antes de recargar: si la recarga falla por red, se repone.
        self._respaldo = None
        # Elementos que llegaron sin forma (la tabla de una capa grande): si luego
        # hace falta la forma de uno, se vuelve a pedir.
        self._sin_forma = set()
        self._view = None
        self._filter = {}
        # Partes (información adicional): elementos cuyos partes ya se pidieron.
        self._partes_de = {}
        # Fotos y ficheros de cada parte, que llegan con el listado.
        self._medios = {}
        # El filtro de la capa («Filtrar…»): el texto, la expresión, lo que se
        # manda a la API y lo ya evaluado por elemento.
        self._subset = ""
        self._subset_expr = None
        self._subset_params = {}
        self._pasa = {}
        # Los filtros por partes y fechas de la URI, como parámetros de la API.
        self._filtros_uri = {}
        self._ai_attr = None
        # Lo que respondió la API al abrir la capa, para guardarlo; y lo guardado,
        # cuando se abre sin sesión (``core/definitions.py``).
        self._respuestas = {}
        self._guardada = None

        try:
            self._uri = parse_uri(uri)
        except ValueError as exc:
            self._error = str(exc)
            self.log_error(f"URI no válida: {exc}")
            return

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
            if self._uri.subset and not self.setSubsetString(self._uri.subset):
                self.log_warning(f"Filtro guardado no válido, se ignora: {self._uri.subset}")
        except AuthError:
            # Lo normal al reabrir un proyecto días después. Con la definición
            # guardada la capa abre vacía y con sus campos, sin que QGIS la dé por
            # «no disponible»; sin ella, queda no disponible. En los dos casos se
            # recupera al volver a entrar.
            connections.mark_expired(self._uri.connection)
            self._error = (
                f"La sesión de «{self._uri.connection}» ha caducado o no es válida. "
                "Hay que volver a entrar desde el panel de Geosian; las capas se "
                "recuperan solas."
            )
            if self._abrir_sin_sesion():
                self.log_warning(self._error)
            else:
                self.log_error(self._error)
        except NotFoundError:
            self._error = (
                f"La capa {self._uri.layer_id} ya no existe en GCC o ha cambiado de mapa. "
                "Quítala del proyecto y vuelve a añadirla desde el panel de Geosian."
            )
            self.log_error(self._error)
        except ForbiddenError:
            self._error = (
                f"No tienes permiso para ver la capa {self._uri.layer_id} en GCC. "
                "Pídelo a quien administre el mapa."
            )
            self.log_error(self._error)
        except NetworkError as exc:
            connections.mark_offline(self._uri.connection)
            self._error = f"No se pudo conectar con GCC: {exc}"
            self.log_error(self._error)
        except GeosianError as exc:
            self._error = str(exc)
            self.log_error(f"No se pudo abrir la capa: {exc}")
        except Exception as exc:
            self._error = str(exc)
            self.log_error(f"Error inesperado al abrir la capa: {exc}")

    # ------------------------------------------------------------------
    # Carga
    # ------------------------------------------------------------------

    def _abrir_sin_sesion(self):
        """Abre la capa con la definición guardada, sin elementos. ``False`` si no hay."""
        guardada = definitions.load(self._uri.connection, self._client.base_url, self._uri)
        if guardada is None:
            return False
        self._guardada = guardada
        try:
            self._load_definition()
        except (GeosianError, AttributeError, KeyError, TypeError, ValueError) as exc:
            self._guardada = None
            self.log_warning(f"Definición guardada no válida: {exc}")
            return False
        self._valid = True
        return True

    def _pedir(self, nombre, funcion, *args):
        """Una respuesta de la API para la definición: de la red o de lo guardado."""
        if self._guardada is not None:
            return self._guardada.get(nombre)
        valor = funcion(*args)
        self._respuestas[nombre] = valor
        return valor

    def _load_definition(self):
        """Campos, tipo de geometría, extensión y recuento. Sin datos."""
        self._respuestas = {}
        if self._uri.info_name:
            self._load_info_definition()
        else:
            self._load_layer_definition()
        if self._guardada is None:
            definitions.save(
                self._uri.connection, self._client.base_url, self._uri, self._respuestas
            )

    def _load_layer_definition(self):
        if self._uri.view_id:
            self._view = self._pedir("vista", self._client.layer_view, self._uri.view_id) or {}
            self._filter, avisos = views.filter_params(self._view.get("filter_config"))
            for aviso in avisos:
                self.log_warning(f"Vista «{self._view.get('name')}»: {aviso}")
        definiciones = self._pedir(
            "definiciones", self._client.layer_attributes, self._uri.layer_id
        )
        self._schema = self._pick_schema(definiciones)
        self._fields, self._attr_map = lad.build_fields(self._schema)
        self._filtros_uri = self._filtros_de_partes()
        self._campo_de_partes()

        metadatos = {}
        try:
            metadatos = (
                self._pedir(
                    "metadatos",
                    self._client.layer_metadata,
                    self._uri.layer_id,
                    self._uri.map_id,
                )
                or {}
            )
        except (NotFoundError, ForbiddenError):
            # Sin permiso sobre el mapa no es «sin metadatos»: la capa se abría válida
            # y vacía (la API da [] en /layer-attributes/ en vez de un 403).
            raise
        except GeosianError as exc:
            # Sin metadatos se puede trabajar: el recuento y la extensión se
            # calculan al cargar los datos. No merece la pena fallar por esto.
            self.log_warning(f"Sin metadatos de la capa: {exc}")

        self._layer_name = metadatos.get("name") or self._schema.get("title") or ""
        self._wkb_type = self._resolve_wkb_type(metadatos)
        self._feature_count = int(metadatos.get("feature_count") or 0)
        self._by_zone = self._feature_count > LARGE_LAYER
        if (self._uri.view_id or self._filtros_uri) and not self._by_zone:
            # El recuento de los metadatos es el de la capa entera; el de la
            # vista o el filtro se sabe al descargarla.
            self._feature_count = 0

        bbox = metadatos.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            self._extent = QgsRectangle(
                float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
            )

    def _campo_de_partes(self):
        """El campo de un parte por el que colorea o pesa la vista, si lo hay.

        Se llama como lo escribe la web (``additional_info.<tipo>.<campo>``), así el
        estilo de la vista lo encuentra sin más; se pide con ``include_ai_attr``.
        """
        self._ai_attr = views.ai_attribute((self._view or {}).get("style_config"))
        if self._ai_attr is None:
            return
        tipo, campo = self._ai_attr
        info = next((i for i in self._schema.get("additional_information") or []
                     if isinstance(i, dict) and i.get("name") == tipo), {})
        definicion = next((a for a in S.flatten_attributes(info) if a.get("name") == campo), {})
        nuevo = QgsField(f"{views.PREFIJO_PARTES}{tipo}.{campo}", QVariant.String)
        nuevo.setAlias(f"{info.get('title') or tipo} · {S.field_title(definicion) or campo}")
        self._fields.append(nuevo)

    def _filtros_de_partes(self):
        """Los filtros por partes y fechas de la URI, comprobados contra el esquema."""
        tipos = {
            info.get("name")
            for info in self._schema.get("additional_information") or []
            if isinstance(info, dict)
        }
        for clave, _ in self._uri.partes:
            tipo = clave.split("__", 1)[0]
            if tipo not in tipos:
                raise GeosianError(
                    f"La capa no tiene partes «{tipo}» o no tienes permiso para verlos; "
                    "quita ese filtro de la capa."
                )
        zona = bytes(QTimeZone.systemTimeZoneId()).decode() or None
        return self._uri.server_filters(zona)

    def _load_info_definition(self):
        """Una tabla sin geometría con los partes de un tipo."""
        definiciones = self._pedir(
            "definiciones", self._client.layer_attributes, self._uri.layer_id
        )
        esquema = self._pick_schema(definiciones)
        tipos = esquema.get("additional_information") or []
        info = next(
            (t for t in tipos if isinstance(t, dict) and t.get("name") == self._uri.info_name),
            None,
        )
        if info is None:
            # La API quita los tipos que los grupos del usuario no pueden ver.
            raise GeosianError(
                f"La capa no tiene partes «{self._uri.info_name}» o no tienes permiso "
                "para verlos."
            )
        self._schema = info
        self._fields, self._attr_map = lad.build_info_fields(info)
        self._layer_name = info.get("title") or info.get("name") or ""
        self._wkb_type = QgsWkbTypes.NoGeometry
        self._lad_geometry = _GEOMETRY_TYPE_TO_LAD.get(self._uri.geometry_type) or (
            (definiciones[0] or {}).get("geometry_type") if definiciones else None
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
        if not self._red():
            return
        if self._respaldo is not None:
            # Un reintento tras un fallo: se baja limpio, sin lo repuesto.
            self._cache.clear()
            self._sin_forma.clear()
        try:
            total = self._download_all()
        except GeosianError as exc:
            self._fallo(exc, "No se pudieron descargar los datos")
            # Sin red se vuelve a intentar pasada la pausa; con otro error no,
            # para no repetir la misma petición fallida en cada repintado.
            if not isinstance(exc, NetworkError):
                self._loaded = True
            self._reponer()
            return

        self._loaded = True
        self._respaldo = None
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
        if self._uri.info_name:
            return self._download_partes()
        pagina = 1
        total = 0
        while True:
            datos = self._client.geodata_paginated(
                self._uri.layer_id,
                page=pagina,
                page_size=PAGE_SIZE,
                data_type=self._uri.geometry_type,
                extra=self._extra(),
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

    def _reponer(self):
        """Tras una recarga fallida, la capa vuelve a enseñar lo que tenía."""
        if self._respaldo is None:
            return
        cache, sin_forma = self._respaldo
        for fid, registro in cache.items():
            self._cache.setdefault(fid, registro)
        self._sin_forma |= {f for f in sin_forma if self._cache.get(f) is cache.get(f)}

    def _extra(self):
        """Parámetros de filtro para la API: los de la vista, los de partes y fechas
        de la URI y los del filtro.

        Si los dos tocan el mismo atributo, se manda el de la vista y el del
        filtro lo evalúa QGIS.
        """
        extra = dict(self._filter)
        if getattr(self, "_ai_attr", None):
            extra["include_ai_attr"] = ".".join(self._ai_attr)
        for clave, valor in self._filtros_uri.items():
            extra.setdefault(clave, valor)
        for clave, valor in self._subset_params.items():
            extra.setdefault(clave, valor)
        return extra

    def _pasa_filtro(self, fid):
        """Si un elemento cumple el filtro de la capa. Se recuerda por elemento."""
        if self._subset_expr is None:
            return True
        if fid not in self._pasa:
            registro = self._cache.get(fid)
            if registro is None:
                return False
            elemento = QgsFeature(self._fields, fid)
            elemento.setAttributes(list(registro.attributes))
            if registro.geometry is not None:
                elemento.setGeometry(registro.geometry)
            contexto = QgsExpressionContext()
            contexto.setFields(self._fields)
            contexto.setFeature(elemento)
            self._pasa[fid] = bool(self._subset_expr.evaluate(contexto))
        return self._pasa[fid]

    def _download_partes(self, geodata_id=None):
        """Trae los partes de la capa, o los de un elemento, por páginas."""
        pagina = 1
        guardados = []
        while True:
            datos = self._client.additional_information(
                self._uri.layer_id,
                self._uri.info_name,
                self._lad_geometry,
                geodata_id=geodata_id,
                page=pagina,
                page_size=INFO_PAGE_SIZE,
            )
            partes = _features_from(datos)
            for parte in partes:
                fid = self._store_parte(parte)
                if fid is not None:
                    guardados.append(fid)
            paginacion = (datos.get("pagination") or {}) if isinstance(datos, dict) else {}
            if not paginacion.get("has_more") or not partes:
                break
            if geodata_id is None and len(guardados) >= TABLE_CAP:
                self.log_warning(
                    f"«{self._layer_name}» tiene {paginacion.get('total_items')} partes; la "
                    f"tabla muestra los primeros {len(guardados)}."
                )
                break
            pagina += 1
        return len(guardados) if geodata_id is None else guardados

    def _store_parte(self, parte):
        """Guarda un parte de /additional-information/. Devuelve su id."""
        try:
            fid = int(parte.get("id"))
        except (TypeError, ValueError):
            return None
        atributos = parte.get("attributes") or {}
        sistema = {
            "id": fid,
            "geodata_id": parte.get("geodata"),
            "usuario": parte.get("user"),
            "created_at": parte.get("created_at"),
            "updated_at": parte.get("updated_at"),
        }
        valores = []
        for campo in self._fields:
            nombre = campo.name()
            attr = self._attr_map.get(nombre)
            if attr is not None:
                valores.append(atributos.get(attr.get("name")))
            else:
                valores.append(sistema.get(nombre))
        self._cache[fid] = CachedFeature(None, valores)
        self._medios[fid] = {"pictures": parte.get("pictures"), "files": parte.get("files")}
        return fid

    def _ensure_partes_de(self, geodata_ids):
        """Pide los partes de unos elementos, los que no se hayan pedido ya."""
        for gid in geodata_ids:
            if gid in self._partes_de:
                continue
            if self._loaded:
                # La tabla entera ya está: se saca de ahí sin ir a la red.
                indice = self._fields.indexOf("geodata_id")
                self._partes_de[gid] = [
                    fid for fid, r in self._cache.items() if r.attributes[indice] == gid
                ]
                continue
            if not self._red():
                return
            try:
                self._partes_de[gid] = self._download_partes(geodata_id=gid)
            except GeosianError as exc:
                self._fallo(exc, f"No se pudieron pedir los partes del elemento {gid}")
                return

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
            geometria = compat.geometry_from_geojson(geojson)

        self._cache[fid] = CachedFeature(
            geometria,
            self._attributes_from(propiedades, fid),
            propiedades.get("object_id"),
        )
        if geojson:
            self._sin_forma.discard(fid)
        return True

    def _attributes_from(self, propiedades, fid):
        """Ordena las propiedades del GeoJSON según los campos de la capa."""
        valores = self._valores_de(propiedades, fid)
        for i in self._campos_lista():
            valores[i] = _como_lista(valores[i])
        return valores

    def _campos_lista(self):
        """Índices de los campos de selección múltiple, calculados una vez por esquema."""
        if self._listas is None or self._listas[0] is not self._fields:
            indices = [
                i for i in range(self._fields.count())
                if self._fields.at(i).type() == QVariant.StringList
            ]
            self._listas = (self._fields, indices)
        return self._listas[1]

    def _valores_de(self, propiedades, fid):
        valores = []
        for campo in self._fields:
            nombre = campo.name()
            if nombre == "id":
                valores.append(fid)
                continue

            if nombre.startswith(views.PREFIJO_PARTES):
                # Lo que la API añade con include_ai_attr, anidado por tipo de parte.
                tipo, _, de = nombre[len(views.PREFIJO_PARTES):].partition(".")
                partes = propiedades.get("additional_info") or {}
                valor = (partes.get(tipo) or {}).get(de) if isinstance(partes, dict) else None
                valores.append(_como_texto(valor))
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
        # Nunca None: QGIS pregunta también a las capas que no abren, y un None
        # en C++ tumba QGIS al leer el proyecto.
        return self._fields if self._fields is not None else QgsFields()

    def wkbType(self):
        return self._wkb_type

    def featureCount(self):
        if self._guardada is not None:
            return 0  # sin sesión no hay elementos que enseñar
        if self._subset_expr is not None:
            if self._by_zone:
                # Habría que bajar la capa entera para contarlos.
                return -1
            self._ensure_loaded()
            with self._lock:
                return sum(1 for fid in list(self._cache) if self._pasa_filtro(fid))
        if not self._loaded and self._feature_count:
            return self._feature_count
        self._ensure_loaded()
        return len(self._cache)

    def supportsSubsetString(self):
        return True

    def subsetString(self):
        return self._subset

    def setSubsetString(self, subset, updateFeatureCount=True):
        """El filtro de la capa: lo que entiende la API va al servidor, como en la
        web; lo demás, y siempre la expresión entera, lo evalúa QGIS."""
        texto = (subset or "").strip()
        expresion = None
        if texto:
            expresion = parse_subset(texto)
            if expresion is None:
                return False
            expresion.prepare(QgsExpressionContext())
        with self._lock:
            self._subset = texto
            self._uri.subset = texto
            self._subset_expr = expresion
            self._subset_params = (
                {} if expresion is None or self._uri.info_name
                else server_params(expresion, self._attr_map)
            )
            self._cache.clear()
            self._sin_forma.clear()
            self._zones = []
            self._loaded = False
            self._tabla_cargada = False
            self._partes_de = {}
            self._pasa = {}
        return True

    def extent(self):
        if self._uri.info_name:
            return self._extent  # sin geometría: nada que calcular
        if self._extent.isNull() or self._extent.isEmpty() or self._view is not None:
            self._ensure_loaded()
        return self._extent

    def metadata_extent(self):
        """La extensión de la capa entera según sus metadatos, sin bajar nada.

        ``extent()`` con una vista baja los elementos para ajustarla al filtro.
        """
        return QgsRectangle(self._extent)

    def isValid(self):
        return self._valid

    def crs(self):
        return self._crs

    def name(self):
        return PROVIDER_KEY

    def storageType(self):
        return "Geosian REST API"

    def dataSourceUri(self, expandAuthConfig=False):
        if getattr(self, "_uri", None) is None:
            return self._uri_text
        return str(self._uri)

    def capabilities(self):
        # Fase 1: solo lectura. La edición llega en la fase 2, junto con el
        # bloqueo optimista que evita pisar el trabajo de otros.
        return QgsVectorDataProvider.SelectAtId

    def error(self):
        return self._error

    def errorMessage(self):
        return self._error

    def reloadData(self):
        """Vacía la caché. Es el gancho del WebSocket y del botón de recargar.

        Si la capa se abrió sin sesión, vuelve a pedir la definición: tras volver a
        entrar, «recargar» es lo que la recupera.
        """
        if self._guardada is not None:
            guardada, self._guardada = self._guardada, None
            try:
                self._load_definition()
            except GeosianError as exc:
                self._guardada = guardada
                self._fallo(exc, "Recuperar la capa")
        with self._lock:
            if self._cache:
                self._respaldo = (dict(self._cache), set(self._sin_forma))
            self._cache.clear()
            self._sin_forma.clear()
            self._zones = []
            self._loaded = False
            self._tabla_cargada = False
            self._partes_de = {}
            self._pasa = {}

    def reload_definition(self):
        """Vuelve a pedir campos y esquema: han cambiado en GCC.

        Si falla, la capa se queda con la definición que tenía.
        """
        self._client.forget_layer_attributes(self._uri.layer_id)
        self._load_definition()
        self.reloadData()

    def invalidate_feature(self, fid):
        """Olvida un elemento suelto, para refrescar solo lo que cambió."""
        self._cache.pop(int(fid), None)
        self._pasa.pop(int(fid), None)

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
                if mejor is None or ((valor < mejor) if minimo else (valor > mejor)):
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
        """Identificadores que satisfacen una petición de QGIS y el filtro de la capa."""
        with self._lock:
            ids = self._resolve_request(request)
            if self._subset_expr is not None:
                ids = [fid for fid in ids if self._pasa_filtro(fid)]
        # El límite va después del filtro: antes, «dame uno» podía no dar ninguno.
        limite = request.limit()
        return ids[:limite] if limite and limite > 0 else ids

    def _resolve_request(self, request):
        con_forma = not request.flags() & QgsFeatureRequest.Flag.NoGeometry
        fid = request.filterFid()
        if fid is not None and fid >= 0:
            self._ensure_ids([fid], con_forma)
            return [fid] if fid in self._cache else []

        fids = request.filterFids()
        if fids:
            pedidos = [int(f) for f in fids]
            self._ensure_ids(pedidos, con_forma)
            return [f for f in pedidos if f in self._cache]

        if self._uri.info_name:
            elementos = _elementos_del_filtro(request)
            if elementos:
                self._ensure_partes_de(elementos)
                return [f for g in elementos for f in self._partes_de.get(g, [])]

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

        return seleccion

    def _ensure_ids(self, fids, con_forma=True):
        """Pide al servidor los elementos que no estén en la caché.

        Con ``con_forma``, también los que llegaron sin ella (de la tabla).
        """
        faltan = [
            f for f in fids if f not in self._cache or (con_forma and f in self._sin_forma)
        ]
        if not faltan:
            return
        if self._loaded:
            # Ya se descargó todo: lo que falta es que no existe o que el
            # usuario no lo puede ver.
            return
        if not self._red():
            return
        try:
            datos = self._client.geodata_paginated(
                self._uri.layer_id,
                page_size=max(len(faltan), 1),
                data_type=self._uri.geometry_type,
                ids=faltan,
                extra=self._extra(),
            )
            for elemento in _features_from(datos):
                self._store(elemento)
        except GeosianError as exc:
            self._fallo(exc, "No se pudieron pedir elementos sueltos")

    def _ensure_zone(self, recuadro):
        """Trae lo que cae en un recuadro, si no se trajo ya."""
        if not self._red():
            return
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
                    extra=self._extra(),
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
            self._fallo(exc, "No se pudo traer la zona")
            self._reponer()
            return

        self._zones.append(QgsRectangle(*area))

    def _ensure_tabla(self):
        """Carga hasta TABLE_CAP elementos de una capa grande, por páginas."""
        if self._tabla_cargada or not self._red():
            return
        self._tabla_cargada = True
        pagina = 1
        total = 0
        try:
            while total < TABLE_CAP:
                # La tabla no pinta formas: solo los atributos, que pesan mucho menos.
                # Una API sin ``no_geometry`` lo ignora y las manda igual.
                datos = self._client.geodata_paginated(
                    self._uri.layer_id,
                    page=pagina,
                    page_size=PAGE_SIZE,
                    data_type=self._uri.geometry_type,
                    extra={**self._extra(), "no_geometry": "true"},
                )
                elementos = _features_from(datos)
                for elemento in elementos:
                    if self._store(elemento) and not elemento.get("geometry"):
                        fid = (elemento.get("properties") or {}).get("id", elemento.get("id"))
                        self._sin_forma.add(int(fid))
                total += len(elementos)
                if len(elementos) < PAGE_SIZE:
                    break
                pagina += 1
        except GeosianError as exc:
            self._fallo(exc, "No se pudo cargar la tabla")
            if isinstance(exc, NetworkError):
                self._tabla_cargada = False
            return
        if self._feature_count > total:
            texto = (
                f"«{self._layer_name}» tiene {self._feature_count} elementos; la tabla "
                f"muestra los primeros {total}. Para ver otros, filtra la tabla por "
                "«objetos visibles en el mapa» y muévete por el mapa."
            )
            self.log_warning(texto)
            if not self._tabla_avisada:
                self._tabla_avisada = _a_la_vista(texto)

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

    def media_of(self, fid):
        """Fotos y ficheros de un elemento o de un parte (:class:`media.MediaItem`).

        Los de un parte llegaron con el listado; los de un elemento se piden a
        su detalle, que es lo que hace la web al abrir la ficha.
        """
        if self._uri.info_name:
            return media.items_from(
                self._medios.get(int(fid)),
                image_url=f"{API_PREFIX}/additional-information/image/{{id}}/",
                file_url=f"{API_PREFIX}/additional-information/file/{{id}}/",
            )
        detalle = self._client.element_detail(fid, self._uri.geometry_type)
        return media.items_from(
            detalle,
            image_url=f"{API_PREFIX}/geodata/image/{{id}}/",
            file_url=f"{API_PREFIX}/geodata/file/{{id}}/",
        )

    def media_bytes(self, item, thumb=False):
        """El contenido de una foto o un fichero: el incrustado o pedido a la API.

        Con ``thumb``, la miniatura si la hay (para la galería).
        """
        if thumb and item.thumb_url:
            return self._client.download(item.thumb_url)
        if item.data is not None:
            return item.data
        return self._client.download(item.url)

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

    @property
    def _client(self):
        """El cliente vigente de la conexión, no el de cuando se abrió la capa.

        Al volver a entrar se crea uno nuevo con la sesión nueva; si la capa se
        quedara con el viejo, seguiría pidiendo con la credencial caducada.
        """
        return connections.client_for(self._uri.connection)

    def _red(self):
        """Si se puede ir a la red: tras un fallo de red, la conexión se pausa.

        Abierta sin sesión no se pide nada hasta recargarla al volver a entrar.
        """
        if self._guardada is not None:
            return False
        return not connections.is_offline(self._uri.connection)

    def _fallo(self, exc, que):
        """Un fallo al pedir datos: se anota lo que toca y se registra.

        Sin red, la conexión entera se pausa un rato (cada intento bloquea la
        interfaz hasta agotar la espera); con la sesión rechazada, la conexión
        queda para volver a entrar.
        """
        if isinstance(exc, NetworkError):
            connections.mark_offline(self._uri.connection)
            texto = (
                f"Sin conexión con GCC («{self._uri.connection}»): se enseña lo último "
                f"que llegó y se reintenta dentro de {connections.PAUSA_SIN_RED} s."
            )
            self.log_warning(f"{que}: {texto} ({exc})")
            ahora = time.monotonic()
            if ahora - _avisado_sin_red.get(self._uri.connection, -AVISO_SIN_RED) >= AVISO_SIN_RED:
                _avisado_sin_red[self._uri.connection] = ahora
                _a_la_vista(texto)
            return
        if isinstance(exc, AuthError):
            connections.mark_expired(self._uri.connection)
            self.log_warning(f"{que}: la sesión de «{self._uri.connection}» ha caducado.")
            return
        self.log_warning(f"{que}: {exc}")

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


# Cada cuánto, como mucho, se avisa en la barra de que una conexión no tiene red.
AVISO_SIN_RED = 300
_avisado_sin_red = {}


class _Avisos(QObject):
    """Lleva los avisos a la barra de QGIS desde cualquier hilo.

    Se encolan siempre, también desde el de la ventana: quien avisa está dentro de
    la carga de la tabla o del pintado, con la caché bloqueada, y no es sitio para
    crear widgets.
    """

    aviso = pyqtSignal(str)

    def mostrar(self, texto):
        from qgis.utils import iface

        if iface is not None:
            iface.messageBar().pushWarning("Geosian", texto)


_avisos = {"objeto": None}


def _como_lista(valor):
    """Una selección múltiple con un valor suelto, como lista de uno.

    Los datos guardan a veces un texto donde el esquema dice ``multiple``; la web
    acepta las dos formas, y QGIS pintaba el texto letra a letra.
    """
    if valor is None or isinstance(valor, list):
        return valor
    if isinstance(valor, str):
        return [valor] if valor.strip() else None
    return [valor]


def _como_texto(valor):
    """Un valor de parte como lo escribe ``String()`` en la web, que es con lo que casa
    las categorías de la vista: ``["Poda", "Tala"]`` es ``"Poda,Tala"``."""
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, list):
        return ",".join("" if v is None else _como_texto(v) for v in valor)
    return valor


def _a_la_vista(texto):
    """Un aviso en la barra de QGIS. ``False`` si no hay aplicación."""
    app = QCoreApplication.instance()
    if app is None:
        return False
    if _avisos["objeto"] is None:
        avisos = _Avisos()
        avisos.moveToThread(app.thread())
        avisos.aviso.connect(avisos.mostrar, Qt.ConnectionType.QueuedConnection)
        _avisos["objeto"] = avisos
    _avisos["objeto"].aviso.emit(texto)
    return True


def _elementos_del_filtro(request):
    """Elementos a los que se ciñe una petición por ``geodata_id``, o ``[]``.

    Es lo que pide la ficha de un elemento a la tabla de sus partes. Se responde
    con solo esos partes, sin descargar la tabla entera; QGIS vuelve a evaluar
    la expresión sobre lo devuelto, así que basta con no quedarse corto.
    """
    if request.filterType() != QgsFeatureRequest.FilterExpression:
        return []
    expresion = request.filterExpression()
    texto = expresion.expression() if expresion is not None else ""
    # Solo si no hay un OR que ensanche el filtro a otros partes.
    if not texto or re.search(r"\bOR\b", texto, re.IGNORECASE):
        return []
    elementos = []
    for igual, lista in _FILTRO_ELEMENTO.findall(texto):
        valores = [igual] if igual else re.findall(r"\d+", lista)
        elementos.extend(int(v) for v in valores)
    return elementos


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
