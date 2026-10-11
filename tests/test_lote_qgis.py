"""Viabilidad del «todo o nada» al confirmar una edición en QGIS.

QGIS no confirma de una vez: llama al proveedor por partes (cambios, retiradas,
altas) y cada parte que sale bien se quita de lo pendiente. Geosian quiere que lo
confirmado de una capa entre entero o no entre nada. La idea:

- Al empezar a confirmar (``beforeCommitChanges``), se le da al proveedor una foto
  entera de lo pendiente (``editBuffer()``).
- La **primera** llamada de escritura manda el lote completo. Si falla, devuelve
  ``False`` y QGIS lo conserva todo pendiente.
- Las siguientes no escriben nada: dan lo suyo por hecho y, en las altas, ponen el
  id que devolvió el servidor.

Estas pruebas no usan el proveedor de Geosian: usan uno mínimo, en memoria, para
fijar lo que hace QGIS (3.34 y 4) y de lo que depende el diseño.
"""

import pytest

qgis_core = pytest.importorskip("qgis.core")

from qgis.core import (
    QgsAbstractFeatureIterator,
    QgsAbstractFeatureSource,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFeatureIterator,
    QgsFeatureRequest,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProviderMetadata,
    QgsProviderRegistry,
    QgsRectangle,
    QgsVectorDataProvider,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant

CLAVE = "lote_pruebas"

# Lo que ve cada prueba: el «servidor» y el registro de llamadas del proveedor.
_estado = {}


class ServidorFalso:
    """Recibe lotes enteros. Si ``falla``, rechaza el lote sin aplicar nada."""

    def __init__(self):
        self.datos = {
            1: {"nombre": "Uno", "geom": (0.0, 0.0)},
            2: {"nombre": "Dos", "geom": (1.0, 1.0)},
            3: {"nombre": "Tres", "geom": (2.0, 2.0)},
            4: {"nombre": "Cuatro", "geom": (3.0, 3.0)},
        }
        self.retirados = set()
        self.lotes = []
        self.falla = False
        self._siguiente = 100

    def confirmar(self, lote):
        self.lotes.append(lote)
        if self.falla:
            raise RuntimeError("409: otro usuario cambió el elemento 2")
        creados = {}
        for ref, alta in lote["crear"].items():
            nuevo = self._siguiente
            self._siguiente += 1
            self.datos[nuevo] = dict(alta)
            creados[ref] = nuevo
        for fid, cambio in lote["cambiar"].items():
            self.datos[fid].update(cambio)
        for fid in lote["retirar"]:
            self.retirados.add(fid)
        return creados


def _fields():
    campos = QgsFields()
    campos.append(QgsField("nombre", QVariant.String))
    return campos


def _punto(xy):
    return QgsGeometry.fromPointXY(QgsPointXY(*xy))


class _Fuente(QgsAbstractFeatureSource):
    def __init__(self, provider):
        super().__init__()
        self.provider = provider

    def getFeatures(self, request=None):
        return QgsFeatureIterator(_Iterador(self, request or QgsFeatureRequest()))


class _Iterador(QgsAbstractFeatureIterator):
    def __init__(self, fuente, request):
        super().__init__(request)
        servidor = fuente.provider.servidor
        visibles = [f for f in sorted(servidor.datos) if f not in servidor.retirados]
        tipo = request.filterType()
        if tipo == QgsFeatureRequest.FilterFid:
            visibles = [f for f in visibles if f == request.filterFid()]
        elif tipo == QgsFeatureRequest.FilterFids:
            visibles = [f for f in visibles if f in request.filterFids()]
        self._ids = visibles
        self._datos = servidor.datos
        self._i = 0

    def fetchFeature(self, feature):
        if self._i >= len(self._ids):
            feature.setValid(False)
            return False
        fid = self._ids[self._i]
        self._i += 1
        dato = self._datos[fid]
        feature.setFields(_fields(), True)
        feature.setId(fid)
        feature.setAttributes([dato["nombre"]])
        feature.setGeometry(_punto(dato["geom"]))
        feature.setValid(True)
        return True

    def rewind(self):
        self._i = 0
        return True

    def close(self):
        return True


class ProveedorLote(QgsVectorDataProvider):
    """Proveedor mínimo con el mecanismo del lote."""

    def __init__(self, uri="", options=None, flags=None):
        super().__init__(uri)
        self.servidor = _estado["servidor"]
        self.llamadas = _estado["llamadas"]
        self._foto = None
        self._creados = None

    @classmethod
    def createProvider(cls, uri, options, flags=None):
        return ProveedorLote(uri, options, flags)

    # Lectura

    def featureSource(self):
        return _Fuente(self)

    def getFeatures(self, request=None):
        return QgsFeatureIterator(_Iterador(_Fuente(self), request or QgsFeatureRequest()))

    def fields(self):
        return _fields()

    def wkbType(self):
        return QgsWkbTypes.Point

    def featureCount(self):
        return len(set(self.servidor.datos) - self.servidor.retirados)

    def extent(self):
        return QgsRectangle(-10, -10, 10, 10)

    def crs(self):
        return QgsCoordinateReferenceSystem("EPSG:4326")

    def isValid(self):
        return True

    def name(self):
        return CLAVE

    def description(self):
        return CLAVE

    def capabilities(self):
        return (
            QgsVectorDataProvider.AddFeatures
            | QgsVectorDataProvider.DeleteFeatures
            | QgsVectorDataProvider.ChangeAttributeValues
            | QgsVectorDataProvider.ChangeGeometries
            | QgsVectorDataProvider.ChangeFeatures
            | QgsVectorDataProvider.SelectAtId
        )

    # El lote

    def preparar_lote(self, buffer):
        """Foto de lo pendiente, tomada en ``beforeCommitChanges``."""
        self.llamadas.append("foto")
        crear = {
            fid: {"nombre": f.attribute("nombre"), "geom": _xy(f.geometry())}
            for fid, f in buffer.addedFeatures().items()
        }
        cambiar = {}
        for fid, valores in buffer.changedAttributeValues().items():
            if 0 in valores:
                cambiar.setdefault(fid, {})["nombre"] = valores[0]
        for fid, geom in buffer.changedGeometries().items():
            cambiar.setdefault(fid, {})["geom"] = _xy(geom)
        retirar = sorted(buffer.deletedFeatureIds())
        self._foto = {"crear": crear, "cambiar": cambiar, "retirar": retirar}
        self._creados = None

    def olvidar_lote(self):
        self._foto = None
        self._creados = None

    def _enviar(self, quien):
        """La primera llamada manda el lote; las siguientes ya lo dan por hecho."""
        self.llamadas.append(quien)
        if self._creados is not None:
            return True
        if self._foto is None:
            # Sin foto no se escribe: mejor fallar que mandar medio lote.
            return False
        try:
            self._creados = self.servidor.confirmar(self._foto)
        except Exception as exc:
            self.pushError(str(exc))
            self._foto = None
            return False
        return True

    def changeAttributeValues(self, attr_map):
        return self._enviar("changeAttributeValues")

    def changeGeometryValues(self, geometry_map):
        return self._enviar("changeGeometryValues")

    def changeFeatures(self, attr_map, geometry_map):
        return self._enviar("changeFeatures")

    def deleteFeatures(self, ids):
        return self._enviar("deleteFeatures")

    def addFeatures(self, flist, flags=None):
        if not self._enviar("addFeatures"):
            return False, flist
        for f in flist:
            f.setId(self._creados[f.id()])
        return True, flist


def _xy(geom):
    p = geom.asPoint()
    return (p.x(), p.y())


class _Metadatos(QgsProviderMetadata):
    def __init__(self):
        super().__init__(CLAVE, CLAVE, ProveedorLote.createProvider)


@pytest.fixture(scope="module")
def registrado(app):
    registro = QgsProviderRegistry.instance()
    if CLAVE not in registro.providerList():
        assert registro.registerProvider(_Metadatos())


@pytest.fixture
def servidor(registrado):
    _estado["servidor"] = ServidorFalso()
    _estado["llamadas"] = []
    yield _estado["servidor"]
    _estado.clear()


@pytest.fixture
def capa(servidor):
    vectorial = QgsVectorLayer("lote", "Lote", CLAVE)
    assert vectorial.isValid()
    proveedor = vectorial.dataProvider()
    # Lo que haría el complemento al abrir una capa editable.
    vectorial.beforeCommitChanges.connect(
        lambda *_: proveedor.preparar_lote(vectorial.editBuffer())
    )
    vectorial.afterCommitChanges.connect(proveedor.olvidar_lote)
    vectorial.afterRollBack.connect(proveedor.olvidar_lote)
    return vectorial


def _editar_de_todo(capa):
    """Una alta, un cambio de atributo, uno de geometría, uno de las dos y una retirada."""
    assert capa.startEditing()
    nuevo = QgsFeature(capa.fields())
    nuevo.setAttributes(["Nuevo"])
    nuevo.setGeometry(_punto((5.0, 5.0)))
    assert capa.addFeature(nuevo)
    assert capa.changeAttributeValue(1, 0, "Uno bis")
    assert capa.changeGeometry(2, _punto((9.0, 9.0)))
    assert capa.changeAttributeValue(3, 0, "Tres bis")
    assert capa.changeGeometry(3, _punto((8.0, 8.0)))
    assert capa.deleteFeature(4)


def _pendiente(capa):
    buffer = capa.editBuffer()
    return {
        "altas": len(buffer.addedFeatures()),
        "atributos": sorted(buffer.changedAttributeValues()),
        "geometrias": sorted(buffer.changedGeometries()),
        "retiradas": sorted(buffer.deletedFeatureIds()),
    }


def test_la_foto_llega_antes_que_la_primera_escritura_y_va_entera(capa, servidor):
    _editar_de_todo(capa)

    assert capa.commitChanges(), capa.commitErrors()

    llamadas = capa.dataProvider().llamadas
    assert llamadas[0] == "foto"
    # Un solo lote al servidor, con todo dentro.
    assert len(servidor.lotes) == 1
    lote = servidor.lotes[0]
    assert len(lote["crear"]) == 1
    assert lote["cambiar"] == {
        1: {"nombre": "Uno bis"},
        2: {"geom": (9.0, 9.0)},
        3: {"nombre": "Tres bis", "geom": (8.0, 8.0)},
    }
    assert lote["retirar"] == [4]


def test_orden_de_las_llamadas_al_confirmar(capa, servidor):
    """Lo que hace QGIS hoy: cambios, retiradas y altas, en ese orden.

    El diseño no depende del orden (la primera llamada, sea cual sea, manda el
    lote), pero conviene saberlo: si cambia, esta prueba lo dice.
    """
    _editar_de_todo(capa)
    assert capa.commitChanges(), capa.commitErrors()

    assert capa.dataProvider().llamadas == [
        "foto",
        "changeFeatures",
        "deleteFeatures",
        "addFeatures",
    ]


def test_el_alta_se_queda_con_el_id_del_servidor(capa, servidor):
    _editar_de_todo(capa)
    assert capa.commitChanges(), capa.commitErrors()

    nombres = {f.id(): f["nombre"] for f in capa.getFeatures()}
    assert nombres[100] == "Nuevo"
    assert 4 not in nombres
    assert all(fid > 0 for fid in nombres)


def test_si_el_lote_falla_no_entra_nada_y_todo_sigue_pendiente(capa, servidor):
    _editar_de_todo(capa)
    antes = _pendiente(capa)
    servidor.falla = True

    assert not capa.commitChanges()

    assert len(servidor.lotes) == 1
    # Solo una llamada: QGIS para en la primera que falla.
    assert capa.dataProvider().llamadas == ["foto", "changeFeatures"]
    assert capa.isEditable()
    assert _pendiente(capa) == antes
    assert servidor.datos[1]["nombre"] == "Uno"
    assert servidor.retirados == set()
    assert any("409" in e for e in capa.commitErrors()), capa.commitErrors()


def test_tras_un_fallo_se_puede_volver_a_confirmar(capa, servidor):
    _editar_de_todo(capa)
    servidor.falla = True
    assert not capa.commitChanges()

    servidor.falla = False
    assert capa.commitChanges(), capa.commitErrors()

    assert len(servidor.lotes) == 2
    assert servidor.lotes[0] == servidor.lotes[1]
    assert servidor.datos[1]["nombre"] == "Uno bis"
    assert servidor.retirados == {4}


def test_solo_altas_la_primera_llamada_es_la_del_alta(capa, servidor):
    assert capa.startEditing()
    nuevo = QgsFeature(capa.fields())
    nuevo.setAttributes(["Solo"])
    nuevo.setGeometry(_punto((4.0, 4.0)))
    assert capa.addFeature(nuevo)

    assert capa.commitChanges(), capa.commitErrors()

    assert capa.dataProvider().llamadas == ["foto", "addFeatures"]
    assert servidor.datos[100]["nombre"] == "Solo"


def test_solo_atributos_y_solo_geometria_van_por_su_llamada(capa, servidor):
    assert capa.startEditing()
    assert capa.changeAttributeValue(1, 0, "Uno bis")
    assert capa.commitChanges(stopEditing=False), capa.commitErrors()
    assert capa.changeGeometry(2, _punto((7.0, 7.0)))
    assert capa.commitChanges(), capa.commitErrors()

    assert capa.dataProvider().llamadas == [
        "foto",
        "changeAttributeValues",
        "foto",
        "changeGeometryValues",
    ]
    assert [lote["cambiar"] for lote in servidor.lotes] == [
        {1: {"nombre": "Uno bis"}},
        {2: {"geom": (7.0, 7.0)}},
    ]


def test_editar_un_alta_antes_de_confirmar_no_es_un_cambio(capa, servidor):
    assert capa.startEditing()
    nuevo = QgsFeature(capa.fields())
    nuevo.setAttributes(["Borrador"])
    nuevo.setGeometry(_punto((4.0, 4.0)))
    assert capa.addFeature(nuevo)
    temporal = next(iter(capa.editBuffer().addedFeatures()))
    assert capa.changeAttributeValue(temporal, 0, "Definitivo")

    assert capa.commitChanges(), capa.commitErrors()

    assert servidor.lotes[0]["cambiar"] == {}
    assert next(iter(servidor.lotes[0]["crear"].values()))["nombre"] == "Definitivo"


def test_sin_foto_no_se_escribe(capa, servidor):
    """Si la señal no llegara (otro camino de confirmación), no se manda medio lote."""
    capa.beforeCommitChanges.disconnect()
    assert capa.startEditing()
    assert capa.changeAttributeValue(1, 0, "Uno bis")

    assert not capa.commitChanges()

    assert servidor.lotes == []
    assert capa.isEditable()


def test_descartar_olvida_la_foto(capa, servidor):
    assert capa.startEditing()
    assert capa.changeAttributeValue(1, 0, "Uno bis")
    assert capa.rollBack()

    assert capa.dataProvider()._foto is None
    assert servidor.lotes == []
