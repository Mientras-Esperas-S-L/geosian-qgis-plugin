"""Crear capas en Geosian desde QGIS: a partir de otra capa o de una capa de QGIS."""

import pytest

qgis_core = pytest.importorskip("qgis.core")

from qgis.core import (
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorDataProvider,
    QgsVectorLayer,
)

from geosian.core import connections
from geosian.core import crear_capa as C
from geosian.core.errors import ForbiddenError
from geosian.provider.uri import build_uri
from tests.test_edicion_atributos import CONEXION, servidor  # noqa: F401


def memoria(definicion, nombre="origen"):
    capa = QgsVectorLayer(definicion, nombre, "memory")
    assert capa.isValid()
    return capa


class TestDeUnaCapaDeQgis:
    @pytest.mark.parametrize(
        "geometria, esperado",
        [
            ("Point", "Point"),
            ("MultiPoint", "MultiPoint"),
            ("LineString", "MultiLineString"),
            ("MultiLineString", "MultiLineString"),
            ("Polygon", "MultiPolygon"),
            ("PointZ", "Point"),
            ("None", None),
        ],
    )
    def test_tipo_de_geometria(self, app, geometria, esperado):
        assert C.tipo_de_geometria(memoria(f"{geometria}?crs=EPSG:4326")) == esperado

    def test_campos_tipos_y_nombres(self, app):
        capa = memoria(
            "Point?crs=EPSG:4326&field=Material:string&field=plazas:integer&field=largo:double"
            "&field=instalado:date&field=año:string&field=1er_turno:string&field=id:integer"
            "&field=object_id:string&field=material:string&field=revisado:boolean"
        )

        campos, fuera, correspondencia = C.campos_de(capa)

        assert [(c["name"], c["type"]) for c in campos] == [
            ("Material", "string"),
            ("plazas", "integer"),
            ("largo", "number"),
            ("instalado", "calendar"),
            ("ano", "string"),
            ("c_1er_turno", "string"),
            ("id_qgis", "integer"),
            ("object_id_qgis", "string"),
            ("material_2", "string"),
            ("revisado", "string"),
        ]
        # La fecha con hora va como texto: el calendario de la web perdería la hora.
        assert C.tipo_de_campo(memoria("Point?field=t:datetime").fields()[0]) == "string"
        assert campos[4]["title"] == "año"
        assert fuera == []
        assert correspondencia["año"] == "ano" and correspondencia["material"] == "material_2"

    def test_un_tipo_que_no_se_lleva(self, app):
        capa = memoria("Point?crs=EPSG:4326&field=nombre:string&field=datos:binary")

        campos, fuera, _ = C.campos_de(capa)

        assert [c["name"] for c in campos] == ["nombre"]
        assert len(fuera) == 1 and "datos" in fuera[0]


class TestApi:
    def test_crear_con_campos(self, servidor):  # noqa: F811
        cliente = connections.client_for(CONEXION)
        cliente.layers(4)

        capa = cliente.crear_capa(4, {"name": "Bancos", "geometry_type": "Point",
                                      "campos": [{"name": "material", "title": "Material", "type": "string"}]})

        assert capa["geometry_types"] == ["Point"]
        assert capa["permissions"]["can_create"] is True
        # El listado del mapa se vuelve a pedir: la capa nueva tiene que salir.
        assert capa["id"] in [c["id"] for c in cliente.layers(4)]

    def test_pide_las_capas_del_mapa_web(self, servidor):  # noqa: F811
        connections.client_for(CONEXION).layers(4)

        consulta = next(c for ruta, c in servidor.peticiones if ruta == "/api/v1/maps/4/layers/")
        assert consulta.get("solo_visibles") == ["true"]

    def test_sin_permiso_da_el_motivo(self, servidor):  # noqa: F811
        servidor.estado.sin_layer_create = True

        with pytest.raises(ForbiddenError, match="No tienes permiso para crear capas"):
            connections.client_for(CONEXION).crear_capa(4, {"name": "X", "plantilla": 11})


def crear_y_abrir(servidor, campos, tipo="Point"):  # noqa: F811
    capa = connections.client_for(CONEXION).crear_capa(4, {"name": "Bancos", "geometry_type": tipo, "campos": campos})
    nueva = QgsVectorLayer(build_uri(CONEXION, 4, capa["id"]), "Bancos", "geosian")
    assert nueva.isValid(), nueva.dataProvider().error()
    from geosian.gui import edicion

    assert edicion.enganchar(nueva)
    return capa, nueva


class TestCapaNueva:
    def test_vacia_se_abre_con_el_tipo_de_su_definicion(self, servidor):  # noqa: F811
        _, nueva = crear_y_abrir(servidor, [{"name": "material", "title": "Material", "type": "string"}], "MultiPolygon")

        assert nueva.wkbType() == qgis_core.QgsWkbTypes.MultiPolygon
        assert nueva.dataProvider().capabilities() & QgsVectorDataProvider.AddFeatures
        assert [f.name() for f in nueva.fields()][-1] == "material"

    def test_sube_los_elementos_de_la_capa_de_qgis(self, servidor):  # noqa: F811
        from geosian.gui.crear_capa import subir_elementos

        origen = memoria("Point?crs=EPSG:3857&field=Material:string&field=plazas:integer")
        elementos = []
        for i, (x, y) in enumerate([(-410000, 4926000), (-410100, 4926100)]):
            f = QgsFeature(origen.fields())
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
            f["Material"] = f"madera {i}"
            f["plazas"] = 3 + i
            elementos.append(f)
        origen.dataProvider().addFeatures(elementos)
        campos, _, correspondencia = C.campos_de(origen)
        capa, nueva = crear_y_abrir(servidor, campos)

        ok, mensaje = subir_elementos(origen, nueva, correspondencia)

        assert ok, mensaje
        subidos = servidor.estado.elementos_de_capa[capa["id"]]
        assert sorted(e["properties"]["Material"] for e in subidos) == ["madera 0", "madera 1"]
        assert sorted(e["properties"]["plazas"] for e in subidos) == [3, 4]
        lon, lat = subidos[0]["geometry"]["coordinates"]
        assert -3.70 < lon < -3.67 and 40.40 < lat < 40.43  # en 4326, no en metros
        assert nueva.featureCount() == 2
        # Un solo lote, todo o nada.
        assert len([r for r in servidor.rutas_pedidas() if r == "/api/v1/geodata/confirmar/"]) == 1


    def test_quita_z_y_m_y_convierte_valores(self, servidor):  # noqa: F811
        from qgis.PyQt.QtCore import QDateTime

        from geosian.gui.crear_capa import subir_elementos

        origen = memoria("PolygonZM?crs=EPSG:4326&field=ok:boolean&field=cuando:datetime")
        f = QgsFeature(origen.fields())
        f.setGeometry(QgsGeometry.fromWkt("POLYGON ZM((-3.70 40.41 5 1, -3.699 40.41 5 1, -3.699 40.411 5 1, -3.70 40.41 5 1))"))
        f["ok"] = True
        f["cuando"] = QDateTime(2026, 3, 4, 10, 30, 0)
        origen.dataProvider().addFeatures([f])
        campos, _, correspondencia = C.campos_de(origen)
        capa, nueva = crear_y_abrir(servidor, campos, "MultiPolygon")

        ok, mensaje = subir_elementos(origen, nueva, correspondencia)

        assert ok, mensaje
        [subido] = servidor.estado.elementos_de_capa[capa["id"]]
        assert subido["geometry"]["type"] == "MultiPolygon"
        assert all(len(p) == 2 for p in subido["geometry"]["coordinates"][0][0])
        assert subido["properties"]["ok"] == "Sí"
        assert subido["properties"]["cuando"] == "2026-03-04T10:30:00"

    def test_el_motivo_sin_el_envoltorio_de_qgis(self):
        from geosian.gui.crear_capa import _motivos

        errores = ["ERROR: 3 feature(s) not added.", "", "  Provider errors:", "    Geosian no ha guardado nada: el lote es grande"]

        assert _motivos(errores) == "Geosian no ha guardado nada: el lote es grande"

    def test_sin_campos_se_puede_crear(self, app_gui, servidor):  # noqa: F811
        from geosian.gui.crear_capa import CrearCapaDialog

        origen = memoria("Point?crs=EPSG:4326", "Solo puntos")
        QgsProject.instance().addMapLayer(origen)
        try:
            d = CrearCapaDialog(CONEXION, {"id": 4, "name": "Ciudad de Ejemplo"})
            d.de_qgis.setChecked(True)
            d.capa_qgis.setLayer(origen)
            d.nombre.setText("Solo puntos")

            d._crear()

            assert d.capa_creada is not None, d.estado.text()
            assert "solo geometría" in d.resumen.text()
        finally:
            QgsProject.instance().removeMapLayer(origen.id())


class TestDialogo:
    def dialogo(self):
        from geosian.gui.crear_capa import CrearCapaDialog

        return CrearCapaDialog(CONEXION, {"id": 4, "name": "Ciudad de Ejemplo"})

    def test_plantilla(self, app_gui, servidor):  # noqa: F811
        d = self.dialogo()
        d.nombre.setText("Arbolado 2027")
        assert d.capa_plantilla.currentData()["id"] == 11
        d.copiar_vistas.setChecked(True)

        d._crear()

        assert d.capa_creada["name"] == "Arbolado 2027"
        cuerpo = next(datos for ruta, datos in servidor.peticiones if ruta.endswith("/layers/crear/"))
        assert cuerpo == {"name": "Arbolado 2027", "plantilla": 11, "copiar_vistas": True}

    def test_de_una_capa_de_qgis(self, app_gui, servidor):  # noqa: F811
        origen = memoria("LineString?crs=EPSG:4326&field=tramo:string", "Tramos")
        QgsProject.instance().addMapLayer(origen)
        try:
            d = self.dialogo()
            d.de_qgis.setChecked(True)
            d.capa_qgis.setLayer(origen)
            d.nombre.setText("Tramos")

            d._crear()

            cuerpo = next(datos for ruta, datos in servidor.peticiones if ruta.endswith("/layers/crear/"))
            assert cuerpo == {"name": "Tramos", "geometry_type": "MultiLineString",
                              "campos": [{"name": "tramo", "title": "tramo", "type": "string"}]}
            assert "MultiLineString" in d.resumen.text()
        finally:
            QgsProject.instance().removeMapLayer(origen.id())

    def test_sin_permiso_lo_dice_y_no_cierra(self, app_gui, servidor):  # noqa: F811
        servidor.estado.sin_layer_create = True
        d = self.dialogo()
        d.nombre.setText("X")

        d._crear()

        assert d.capa_creada is None
        assert "No tienes permiso para crear capas" in d.estado.text()

    def test_sesion_caducada_lo_dice_y_como_volver(self, app_gui, servidor):  # noqa: F811
        connections.set_session(CONEXION, "token-caducado", "")
        d = self.dialogo()
        d.nombre.setText("X")

        d._crear()

        assert "sesión de Geosian ha caducado" in d.estado.text()
        assert "Volver a entrar" in d.estado.text()
        assert d.capa_creada is None

    def test_sin_red_lo_dice(self, app_gui):
        connections.save_connection("SinRed", "http://127.0.0.1:9", "x@ejemplo.com")
        connections.set_session("SinRed", "tok", "")
        try:
            from geosian.gui.crear_capa import CrearCapaDialog

            d = CrearCapaDialog("SinRed", {"id": 4, "name": "Ciudad de Ejemplo"})
            d.nombre.setText("X")
            d._crear()

            assert "Sin conexión con Geosian" in d.estado.text()
        finally:
            connections.remove_connection("SinRed")

    def test_sin_nombre_no_pide_nada(self, app_gui, servidor):  # noqa: F811
        d = self.dialogo()

        d._crear()

        assert "nombre" in d.estado.text()
        assert not any(r.endswith("/layers/crear/") for r in servidor.rutas_pedidas())
