"""Fuente e iterador de elementos.

QGIS pide los elementos a través de un ``QgsFeatureRequest`` que dice qué
quiere: unos identificadores concretos, un recuadro, un subconjunto de campos,
sin geometría, con un límite. Aquí se atiende esa petición contra la caché que
mantiene el proveedor, pidiendo al servidor solo lo que falte.
"""

from qgis.core import (
    QgsAbstractFeatureIterator,
    QgsAbstractFeatureSource,
    QgsCoordinateTransform,
    QgsCsException,
    QgsFeatureIterator,
    QgsFeatureRequest,
)


class GeosianFeatureSource(QgsAbstractFeatureSource):
    """Instantánea de la capa que QGIS puede usar desde cualquier hilo."""

    def __init__(self, provider):
        super().__init__()
        self._provider = provider
        self._fields = provider.fields()
        self._crs = provider.crs()

    def getFeatures(self, request=None):
        return QgsFeatureIterator(
            GeosianFeatureIterator(self, request or QgsFeatureRequest())
        )

    @property
    def fields(self):
        return self._fields

    @property
    def crs(self):
        return self._crs

    @property
    def provider(self):
        return self._provider


class GeosianFeatureIterator(QgsAbstractFeatureIterator):
    """Recorre los elementos que pide un ``QgsFeatureRequest``."""

    def __init__(self, source, request):
        super().__init__(request)
        self._source = source
        self._request = request
        self._index = 0
        self._transform = None
        self._closed = False

        provider = source.provider
        self._fields = source.fields

        try:
            self._ids = provider.resolve_request(request)
        except Exception as exc:  # una capa rota no debe tumbar el render
            provider.log_error(f"No se pudieron obtener los elementos: {exc}")
            self._ids = []

        self._prepare_transform()

    def _prepare_transform(self):
        """Reproyección al vuelo, si QGIS pide los datos en otro sistema."""
        destino = self._request.destinationCrs()
        if destino.isValid() and destino != self._source.crs:
            self._transform = QgsCoordinateTransform(
                self._source.crs, destino, self._request.transformContext()
            )

    def fetchFeature(self, feature):
        if self._closed or self._index >= len(self._ids):
            feature.setValid(False)
            return False

        provider = self._source.provider
        flags = self._request.flags()
        sin_geometria = bool(flags & QgsFeatureRequest.NoGeometry)

        while self._index < len(self._ids):
            fid = self._ids[self._index]
            self._index += 1

            registro = provider.get_cached(fid)
            if registro is None:
                continue

            feature.setFields(self._fields, True)
            feature.setId(fid)
            feature.setAttributes(list(registro.attributes))
            feature.setValid(True)

            if sin_geometria:
                feature.clearGeometry()
            else:
                geom = registro.geometry
                if geom is not None and not geom.isNull():
                    feature.setGeometry(geom)
                    if self._transform is not None:
                        try:
                            self.geometryToDestinationCrs(feature, self._transform)
                        except QgsCsException:
                            # Fuera del dominio de la proyección: se devuelve
                            # el elemento sin geometría en vez de perderlo.
                            feature.clearGeometry()
                else:
                    feature.clearGeometry()

            return True

        feature.setValid(False)
        return False

    def rewind(self):
        if self._closed:
            return False
        self._index = 0
        return True

    def close(self):
        self._closed = True
        self._ids = []
        return True
