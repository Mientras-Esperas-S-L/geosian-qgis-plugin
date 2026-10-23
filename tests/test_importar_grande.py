"""Subir a Geosian una capa de QGIS demasiado grande para un lote: GeoPackage a trozos."""

import pytest

qgis_core = pytest.importorskip("qgis.core")

from qgis.core import QgsFeature, QgsGeometry, QgsVectorLayer, QgsWkbTypes
from qgis.PyQt.QtCore import QDateTime

from geosian.core import connections
from geosian.core import crear_capa as C
from geosian.core import importar_grande as I
from geosian.core.errors import ApiError, ConflictError, ForbiddenError, NetworkError
from tests.test_edicion_atributos import CONEXION, servidor  # noqa: F401


def origen_con(n=3, crs="EPSG:3857"):
    capa = QgsVectorLayer(
        f"PointZ?crs={crs}&field=Material:string&field=plazas:integer&field=ok:boolean&field=cuando:datetime",
        "origen", "memory",
    )
    elementos = []
    for i in range(n):
        f = QgsFeature(capa.fields())
        f.setGeometry(QgsGeometry.fromWkt(f"POINT Z({-410000 - i * 10} {4926000 + i * 10} 7)"))
        f["Material"] = f"madera {i}"
        f["plazas"] = i
        f["ok"] = i % 2 == 0
        f["cuando"] = QDateTime(2026, 3, 4, 10, 30, 0)
        elementos.append(f)
    capa.dataProvider().addFeatures(elementos)
    return capa


def leer(ruta):
    capa = QgsVectorLayer(f"{ruta}|layername=capa", "leida", "ogr")
    assert capa.isValid()
    return capa


class TestEmpaquetar:
    def test_en_4326_con_nombres_y_valores_de_geosian(self, app, tmp_path):
        origen = origen_con()
        campos, _, correspondencia = C.campos_de(origen)
        ruta = str(tmp_path / "capa.gpkg")

        escritos, sin_geometria = I.empaquetar(origen, campos, correspondencia, "Point", ruta)

        assert (escritos, sin_geometria) == (3, 0)
        leida = leer(ruta)
        assert leida.crs().authid() == "EPSG:4326"
        assert QgsWkbTypes.flatType(leida.wkbType()) == QgsWkbTypes.Point
        assert not QgsWkbTypes.hasZ(leida.wkbType())
        assert [f.name() for f in leida.fields()][1:] == ["Material", "plazas", "ok", "cuando"]
        primero = next(leida.getFeatures())
        assert primero["ok"] == "Sí" and primero["cuando"] == "2026-03-04T10:30:00"
        punto = primero.geometry().asPoint()
        assert -3.70 < punto.x() < -3.67 and 40.40 < punto.y() < 40.43

    def test_un_campo_fid_de_la_capa_se_empaqueta_aparte(self, app, tmp_path):
        # Con el nombre tal cual, el GeoPackage no se podía escribir («Wrong field type for fid»).
        origen = QgsVectorLayer("Point?crs=EPSG:4326&field=fid:string&field=a  b:string", "o", "memory")
        f = QgsFeature(origen.fields())
        f.setGeometry(QgsGeometry.fromWkt("POINT(-3.7 40.4)"))
        f.setAttributes(["A-1", "x"])
        origen.dataProvider().addFeatures([f])
        campos, _, correspondencia = C.campos_de(origen)
        ruta = str(tmp_path / "c.gpkg")

        assert I.empaquetar(origen, campos, correspondencia, "Point", ruta) == (1, 0)
        [leido] = leer(ruta).getFeatures()
        assert (leido["fid_qgis"], leido["a_b"]) == ("A-1", "x")

    def test_las_curvas_van_en_tramos_rectos(self, app, tmp_path):
        # El servidor no lee curvas (CAD): con ellas, la importación fallaba al final.
        origen = QgsVectorLayer("CurvePolygon?crs=EPSG:4326&field=n:integer", "o", "memory")
        f = QgsFeature(origen.fields())
        f.setGeometry(QgsGeometry.fromWkt(
            "CURVEPOLYGON(CIRCULARSTRING(-3.7 40.4, -3.69 40.41, -3.68 40.4, -3.69 40.39, -3.7 40.4))"
        ))
        origen.dataProvider().addFeatures([f])
        campos, _, correspondencia = C.campos_de(origen)
        ruta = str(tmp_path / "c.gpkg")

        assert I.empaquetar(origen, campos, correspondencia, "MultiPolygon", ruta) == (1, 0)
        [leido] = leer(ruta).getFeatures()
        assert leido.geometry().wkbType() == QgsWkbTypes.MultiPolygon

    def test_fuera_de_su_sistema_de_coordenadas_lo_dice(self, app, tmp_path):
        origen = QgsVectorLayer("Point?crs=EPSG:25830&field=n:integer", "o", "memory")
        f = QgsFeature(origen.fields())
        f.setGeometry(QgsGeometry.fromWkt("POINT(1e12 1e12)"))
        origen.dataProvider().addFeatures([f])
        campos, _, correspondencia = C.campos_de(origen)

        with pytest.raises(I.NoSePuede, match="no se pueden pasar a coordenadas geográficas"):
            I.empaquetar(origen, campos, correspondencia, "Point", str(tmp_path / "c.gpkg"))

    def test_sin_geometria_se_salta(self, app, tmp_path):
        origen = origen_con()
        f = QgsFeature(origen.fields())
        f["Material"] = "sin sitio"
        origen.dataProvider().addFeatures([f])
        campos, _, correspondencia = C.campos_de(origen)

        assert I.empaquetar(origen, campos, correspondencia, "Point", str(tmp_path / "c.gpkg")) == (3, 1)

    def test_sin_geometria_util_lo_dice(self, app, tmp_path):
        tabla = QgsVectorLayer("None?field=n:string", "tabla", "memory")

        with pytest.raises(I.NoSePuede, match="no tiene geometría"):
            I.empaquetar(tabla, [], {}, None, str(tmp_path / "c.gpkg"))

    def test_geometria_rota_no_sube_nada(self, app, tmp_path):
        origen = QgsVectorLayer("Polygon?crs=EPSG:4326&field=n:string", "o", "memory")
        f = QgsFeature(origen.fields())
        # Pajarita: se corta a sí misma.
        f.setGeometry(QgsGeometry.fromWkt("POLYGON((0 0, 1 1, 1 0, 0 1, 0 0))"))
        origen.dataProvider().addFeatures([f])
        campos, _, correspondencia = C.campos_de(origen)

        with pytest.raises(I.NoSePuede, match="geometría rota"):
            I.empaquetar(origen, campos, correspondencia, "MultiPolygon", str(tmp_path / "c.gpkg"))


def preparar(tmp_path, n=3):
    origen = origen_con(n)
    campos, _, correspondencia = C.campos_de(origen)
    ruta = str(tmp_path / "capa.gpkg")
    escritos, _ = I.empaquetar(origen, campos, correspondencia, "Point", ruta)
    datos = {"name": "Bancos", "geometry_type": "Point", "campos": campos, "elementos": escritos}
    return datos, ruta


class TestSubir:
    def test_a_trozos_confirma_y_espera(self, servidor, tmp_path):  # noqa: F811
        datos, ruta = preparar(tmp_path)
        cliente = connections.client_for(CONEXION)

        subida = I.subir(cliente, 4, datos, ruta)
        final = I.esperar(cliente, 4, subida["id"], cada=0)

        assert final["estado"] == "hecha"
        trozos = [r for r in servidor.rutas_pedidas() if "/trozos/" in r]
        assert len(trozos) == subida["trozos"] >= 2
        subidos = servidor.estado.elementos_de_capa[final["capa_id"]]
        assert sorted(e["properties"]["Material"] for e in subidos) == ["madera 0", "madera 1", "madera 2"]
        assert subidos[0]["geometry"]["type"] == "Point"

    def test_un_trozo_que_se_pierde_se_repite_y_no_se_empieza_de_cero(self, servidor, tmp_path):  # noqa: F811
        datos, ruta = preparar(tmp_path)
        servidor.estado.cortar_trozos = {1}

        subida = I.subir(connections.client_for(CONEXION), 4, datos, ruta, espera=0)

        trozos = [r.rsplit("/trozos/", 1)[1] for r in servidor.rutas_pedidas() if "/trozos/" in r]
        assert trozos.count("1/") == 2 and trozos.count("0/") == 1
        assert subida["estado"] == "importando"

    def test_sin_permiso_no_sube_nada(self, servidor, tmp_path):  # noqa: F811
        datos, ruta = preparar(tmp_path)
        servidor.estado.sin_layer_create = True

        with pytest.raises(ForbiddenError, match="No tienes permiso"):
            I.subir(connections.client_for(CONEXION), 4, datos, ruta)

        assert not [r for r in servidor.rutas_pedidas() if "/trozos/" in r]

    def test_un_nombre_repetido_se_dice_antes_de_subir_trozos(self, servidor, tmp_path):  # noqa: F811
        datos, ruta = preparar(tmp_path)
        servidor.estado.capas_extra.append({"id": 399, "name": datos["name"], "map": 4})

        with pytest.raises(ConflictError, match="Ya hay una capa"):
            I.subir(connections.client_for(CONEXION), 4, {**datos}, ruta, espera=0)

        # El nombre se mira al abrir (como el backend): no se llega a subir ni un trozo.
        assert not [r for r in servidor.rutas_pedidas() if "/trozos/" in r]

    def test_un_fallo_al_confirmar_cancela_la_subida(self, servidor, tmp_path, monkeypatch):  # noqa: F811
        datos, ruta = preparar(tmp_path)
        cliente = connections.client_for(CONEXION)

        def falla(*args):
            raise ApiError(400, "Faltan datos.")

        monkeypatch.setattr(cliente, "confirmar_importacion", falla)

        with pytest.raises(ApiError):
            I.subir(cliente, 4, datos, ruta, espera=0)

        [imp] = servidor.estado.importaciones.values()
        assert imp["estado"] == "cancelada"

    def test_si_la_confirmacion_llega_pero_no_su_respuesta_no_se_repite(self, servidor, tmp_path, monkeypatch):  # noqa: F811
        datos, ruta = preparar(tmp_path)
        cliente = connections.client_for(CONEXION)
        original = cliente.confirmar_importacion

        def llega_sin_respuesta(*args):
            original(*args)
            raise NetworkError("se cortó")

        monkeypatch.setattr(cliente, "confirmar_importacion", llega_sin_respuesta)

        estado = I.subir(cliente, 4, datos, ruta, espera=0)

        assert estado["estado"] in ("importando", "hecha")
        confirmadas = [r for r in servidor.rutas_pedidas() if r.endswith("/confirmar/")]
        assert len(confirmadas) == 1
        assert [c["name"] for c in servidor.estado.capas_extra].count(datos["name"]) == 1

    def test_un_502_se_repite_como_un_corte(self, servidor, tmp_path, monkeypatch):  # noqa: F811
        datos, ruta = preparar(tmp_path)
        cliente = connections.client_for(CONEXION)
        original, veces = cliente.importar_trozo, []

        def reiniciando(*args):
            veces.append(1)
            if len(veces) == 1:
                raise ApiError(502, "<html>Bad Gateway</html>")
            return original(*args)

        monkeypatch.setattr(cliente, "importar_trozo", reiniciando)

        assert I.subir(cliente, 4, datos, ruta, espera=0)["estado"] in ("importando", "hecha")
        assert len(veces) >= 2

    def test_cancelar_avisa_al_servidor(self, servidor, tmp_path):  # noqa: F811
        datos, ruta = preparar(tmp_path)
        enviados = []

        with pytest.raises(I.Cancelado):
            I.subir(connections.client_for(CONEXION), 4, datos, ruta,
                    avance=enviados.append, cancelado=lambda: len(enviados) >= 1)

        [imp] = servidor.estado.importaciones.values()
        assert imp["estado"] == "cancelada"


class _Cliente:
    """Un cliente que responde lo que se le diga, en orden, y apunta lo que se le pide."""

    def __init__(self, estados):
        self.estados = list(estados)
        self.pedido = []

    def importacion(self, map_id, id_subida):
        self.pedido.append("estado")
        siguiente = self.estados.pop(0) if len(self.estados) > 1 else self.estados[0]
        if isinstance(siguiente, Exception):
            raise siguiente
        return {"estado": siguiente, "faltan": [], "progreso": None}

    def cancelar_importacion(self, map_id, id_subida):
        self.pedido.append("cancelar")

    def confirmar_importacion(self, map_id, id_subida):
        self.pedido.append("confirmar")
        raise NetworkError("sin respuesta")


class TestCancelarYConfirmar:
    def test_cancelar_mientras_espera_a_la_red_avisa_al_servidor(self, app):
        cliente = _Cliente([NetworkError("sin red"), "cancelada"])
        veces = []

        with pytest.raises(I.Cancelado):
            I.esperar(cliente, 4, "s", cancelado=lambda: veces.append(1) or True, cada=0)

        assert "cancelar" in cliente.pedido

    def test_si_al_cancelar_ya_habia_terminado_la_capa_cuenta(self, app):
        cliente = _Cliente(["importando", "hecha"])

        estado = I.esperar(cliente, 4, "s", cancelado=lambda: True, cada=0)

        assert estado["estado"] == "hecha" and "cancelar" in cliente.pedido

    def test_sin_respuesta_al_confirmar_espera_antes_de_repetir(self, app, monkeypatch):
        # Puede seguir comprobando la huella: repetir enseguida la confirmaba dos veces.
        monkeypatch.setattr(I, "ESPERA", 0)
        cliente = _Cliente(["subiendo", "subiendo", "importando"])

        estado = I._confirmar(cliente, 4, "s", None, espera=0)

        assert estado["estado"] == "importando"
        assert cliente.pedido.count("confirmar") == 1


class _Barra:
    def __init__(self):
        self.avisos = []

    def __getattr__(self, nombre):
        return lambda titulo, texto: self.avisos.append((nombre, texto))


class _Dock:
    def __init__(self):
        self.barra = _Barra()
        self.añadidas = []
        self.iface = self

    def messageBar(self):
        return self.barra

    def añadir_capa(self, datos):
        self.añadidas.append(datos["capa"])
        return [object()]


class TestDialogo:
    def test_por_encima_del_maximo_va_por_la_tarea(self, app_gui, servidor, monkeypatch):  # noqa: F811
        from qgis.core import QgsProject

        from geosian.gui import crear_capa as G

        monkeypatch.setattr(C, "MAX_ELEMENTOS", 2)
        origen = origen_con(3)
        QgsProject.instance().addMapLayer(origen)
        try:
            d = G.CrearCapaDialog(CONEXION, {"id": 4, "name": "Ciudad de Ejemplo"})
            d.de_qgis.setChecked(True)
            d.capa_qgis.setLayer(origen)
            d.nombre.setText("Bancos")
            assert d.con_elementos.isEnabled() and "segundo plano" in d.con_elementos.text()

            d._crear()

            assert d.grande["name"] == "Bancos" and d.capa_creada is None
            assert not any(r.endswith("/layers/crear/") for r in servidor.rutas_pedidas())

            dock = _Dock()
            # Sin las esperas de 3 s entre consultas.
            monkeypatch.setattr(I, "esperar", _esperar)
            tarea = G.ImportarCapaGrande(dock, CONEXION, {"id": 4, "name": "Ciudad"}, origen, d.grande, d.correspondencia)
            ok = tarea.run()
            tarea.finished(ok)

            assert ok, tarea.error
            assert [c["name"] for c in dock.añadidas] == ["Bancos"]
            assert dock.barra.avisos[-1][0] == "pushSuccess" and "3 elementos" in dock.barra.avisos[-1][1]
        finally:
            QgsProject.instance().removeMapLayer(origen.id())

    def test_con_filtro_cuenta_los_que_deja_ver(self, app_gui, servidor, tmp_path, monkeypatch):  # noqa: F811
        from qgis.core import QgsProject

        from geosian.gui import crear_capa as G

        # Un GeoPackage filtrado sigue dando en featureCount() el total del fichero.
        origen = origen_con(3)
        campos, _, correspondencia = C.campos_de(origen)
        ruta = str(tmp_path / "tres.gpkg")
        I.empaquetar(origen, campos, correspondencia, "Point", ruta)
        capa = QgsVectorLayer(f"{ruta}|layername=capa", "tres", "ogr")
        capa.setSubsetString("plazas < 2")
        assert C.contar_elementos(capa) == 2
        monkeypatch.setattr(C, "MAX_ELEMENTOS", 2)
        QgsProject.instance().addMapLayer(capa)
        try:
            d = G.CrearCapaDialog(CONEXION, {"id": 4, "name": "Ciudad de Ejemplo"})
            d.de_qgis.setChecked(True)
            d.capa_qgis.setLayer(capa)
            d.nombre.setText("Dos bancos")

            d._crear()

            # Dos caben en un lote: la capa se crea aquí, sin importación grande.
            assert d.grande is None and d.capa_creada is not None
            assert "2 elementos" in d.con_elementos.text()
        finally:
            QgsProject.instance().removeMapLayer(capa.id())

    def test_si_falla_lo_dice_y_no_anade_nada(self, app_gui, servidor, monkeypatch):  # noqa: F811
        from geosian.gui import crear_capa as G

        servidor.estado.sin_layer_create = True
        origen = origen_con(3)
        campos, _, correspondencia = C.campos_de(origen)
        dock = _Dock()
        tarea = G.ImportarCapaGrande(
            dock, CONEXION, {"id": 4, "name": "Ciudad"}, origen,
            {"name": "Bancos", "geometry_type": "Point", "campos": campos}, correspondencia,
        )

        ok = tarea.run()
        tarea.finished(ok)

        assert not ok and dock.añadidas == []
        assert dock.barra.avisos[-1][0] == "pushWarning" and "No tienes permiso" in dock.barra.avisos[-1][1]


_esperar_original = I.esperar


def _esperar(cliente, map_id, id_subida, **kwargs):
    kwargs.pop("cada", None)
    return _esperar_original(cliente, map_id, id_subida, cada=0, **kwargs)
