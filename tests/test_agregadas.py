"""Vistas agregadas (hexágonos…) con las teselas que agrega el servidor."""

import json

import pytest

pytest.importorskip("qgis.core")

from qgis.core import QgsApplication, QgsAuthMethodConfig

from geosian.core import aggregated, connections
from geosian.gui import celdas


def test_las_vistas_agregadas_no_guardan_credenciales_de_teselas(app):
    """Las celdas y los contornos piden las teselas con el cliente y la sesión: ya no hace
    falta guardar el token en el gestor de autenticación de QGIS como cabecera aparte."""
    from qgis.core import QgsProject

    from tests.fake_server import FakeGeosian

    with FakeGeosian() as fake:
        antes = set(QgsApplication.authManager().configIds())
        try:
            _añadir_vista(fake, "SinCabecera", {"id": 9, "name": "Densidad"})
            _añadir_vista(fake, "SinCabecera", {"id": 11, "name": "Contornos"})
            nuevas = set(QgsApplication.authManager().configIds()) - antes
            nombres = set()
            for i in nuevas:
                config = QgsAuthMethodConfig()
                QgsApplication.authManager().loadAuthenticationConfig(i, config, False)
                nombres.add(config.name())
            assert not any("teselas" in n for n in nombres), nombres
        finally:
            QgsProject.instance().clear()
            connections.remove_connection("SinCabecera")


def test_la_uri_de_las_teselas_no_lleva_la_credencial():
    uri = aggregated.tile_layer_uri("https://api.ejemplo.org", 120, {"attr__especie": ["Tilo", "Olmo"]}, None)
    assert "authcfg" not in uri
    assert "agg%3Dhex" in uri and "layer_id%3D120" in uri
    assert "attr__especie%3DTilo" in uri and "attr__especie%3DOlmo" in uri


def test_color_por_numero_de_puntos_en_escala_logaritmica():
    """Como ``useMvtLayers.js``: t = min(1, ln(1+n)/ln(1+colorMax)), seis colores."""
    rampa = [(i, i, i, 200) for i in range(6)]
    assert aggregated.count_bucket(0, 100) == 0
    assert aggregated.count_bucket(1, 100) == 0
    assert aggregated.count_bucket(9, 100) == 2      # ln10/ln101 = 0,499 → 2,99 → 2
    assert aggregated.count_bucket(100, 100) == 5
    assert aggregated.count_bucket(5000, 100) == 5
    expresion = aggregated.count_color_expression(rampa, 100)
    assert '"count"' in expresion and "'5,5,5,200'" in expresion


def test_una_vista_de_hexagonos_entra_como_teselas_del_servidor(app):
    """Antes se pintaban los puntos con el color de la vista y un aviso."""
    from qgis.core import QgsMapLayerType, QgsProject

    from geosian.gui.browser_dock import ROL_DATOS, GeosianBrowserDock
    from tests.fake_server import FakeGeosian
    from tests.test_gui import IfaceFalso

    with FakeGeosian() as fake:
        try:
            connections.save_connection("Hex", fake.url, "a@b.c")
            connections.set_session("Hex", "tok-de-prueba", "jwt")
            panel = GeosianBrowserDock(IfaceFalso())
            raiz = panel.arbol.topLevelItem(0)
            panel._al_desplegar(raiz)
            mapa = raiz.child(0).child(0)
            panel._al_desplegar(mapa)
            datos = dict(mapa.child(0).data(0, ROL_DATOS))
            datos["vista"] = {"id": 9, "name": "Densidad"}
            [capa] = panel.añadir_capa(datos)

            # Polígonos enteros en una capa propia, no la capa de teselas de QGIS, que
            # recortaba cada celda al borde de su tesela (las costuras).
            assert capa.type() == QgsMapLayerType.VectorLayer
            assert celdas.es_de_celdas(capa)
            assert capa.name() == "Arbolado · Densidad"
            assert "tok-de-prueba" not in capa.source()
            assert abs(capa.opacity() - 0.7) < 1e-6
            # Un estilo por tramo de la rampa, con «Baja densidad» y «Alta densidad».
            # Etiquetas y filtros a listas: QGIS 3.34 se cae si se retienen las reglas de
            # una capa que luego se borra.
            reglas = capa.renderer().rootRule().children()
            etiquetas = [r.label() for r in reglas]
            filtros = [r.filterExpression() for r in reglas]
            del reglas
            assert etiquetas == ["Baja densidad", "", "", "", "", "Alta densidad"]
            assert all("ln(1 + 50)" in f for f in filtros)
            assert filtros[0].endswith("= 0")
            assert capa in QgsProject.instance().mapLayers().values()

            # Al verse en el lienzo se piden las teselas de ese zoom, con el filtro de la
            # vista, y sus celdas llegan enteras: sobresalen de la tesela.
            fake.peticiones.clear()
            x0, y0 = aggregated.to_mercator(-3.75, 40.38)
            x1, y1 = aggregated.to_mercator(-3.65, 40.43)
            celdas.actualizar(capa, (x0, y0, x1, y1), 12)
            assert _esperar(lambda: capa.featureCount() > 0)
            pedidas = [c for r, c in fake.peticiones if r.startswith("/api/v1/geodata/tiles/12/")]
            assert pedidas and all(c.get("agg") == ["hex"] and "geom" not in c for c in pedidas)
            assert all(c.get("attr__especie") == ["Tilia platyphyllos"] for c in pedidas)
            fuera = False
            for f in capa.getFeatures():
                centro = f.geometry().centroid().asPoint()
                lon, lat = _a_grados(centro.x(), centro.y())
                tx, ty = aggregated._tesela(lon, lat, 12)
                oeste, _, este, _ = aggregated.tile_bounds(12, tx, ty)
                caja = f.geometry().boundingBox()
                fuera = fuera or caja.xMinimum() < oeste or caja.xMaximum() > este
            assert fuera
        finally:
            QgsProject.instance().clear()
            connections.remove_connection("Hex")


def test_h3_va_por_los_hexagonos_del_servidor_como_la_web_en_capas_grandes():
    """Sobre una capa MVT la web pinta H3 con los mismos hexágonos del servidor."""
    from geosian.core import styles

    vista = styles.view_style({"visualization": "h3hexagon", "h3hexagon": {"resolution": 9},
                               "point": {"opacity": 0.85}}, "points")
    assert vista["kind"] == "hexagon"
    # Sin colorRamp, la de resolveColorRange de la web: inferno (no la que pone el editor
    # al crear la vista, que sí la guarda).
    assert vista["ramp"] == "inferno"
    assert styles.view_style({"visualization": "hexagon", "hexagon": {}}, "points")["ramp"] == "inferno"
    assert styles.view_style({"visualization": "hexagon"}, "points")["ramp"] == "inferno"
    assert vista["opacity"] == 0.85
    assert "h3hexagon" in aggregated.HEXAGONOS


def test_la_leyenda_de_las_agregadas_es_el_degradado_de_la_web(app, tmp_path):
    """Las capas de teselas no traen leyenda en QGIS: el degradado de la rampa con
    «Baja densidad» y «Alta densidad», y vuelve al reabrir el proyecto."""
    from qgis.core import (
        QgsColorRampLegendNode,
        QgsLayerTreeModel,
        QgsProject,
        QgsVectorTileLayer,
    )

    from geosian.gui import leyendas

    proyecto = QgsProject.instance()
    try:
        capa = QgsVectorTileLayer("type=xyz&url=https://ejemplo.org/{z}/{x}/{y}.mvt&zmax=14", "Hex")
        rampa = [(68, 1, 84, 200), (59, 82, 139, 200), (33, 145, 140, 200),
                 (94, 201, 98, 200), (180, 220, 60, 200), (253, 231, 37, 200)]
        leyendas.poner_leyenda_de_densidad(capa, rampa)
        proyecto.addMapLayer(capa)

        modelos = []  # el modelo dueño de los nodos tiene que seguir vivo

        def nodos():
            raiz = proyecto.layerTreeRoot()
            modelos.append(QgsLayerTreeModel(raiz))
            return modelos[-1].layerLegendNodes(raiz.findLayer(capa.id()))

        [nodo] = nodos()
        assert isinstance(nodo, QgsColorRampLegendNode)
        assert nodo.ramp().color1().getRgb()[:3] == (68, 1, 84)
        assert nodo.ramp().color2().getRgb()[:3] == (253, 231, 37)
        assert nodo.settings().minimumLabel() == "Baja densidad"
        assert nodo.settings().maximumLabel() == "Alta densidad"

        ruta = str(tmp_path / "p.qgz")
        assert proyecto.write(ruta)
        proyecto.clear()
        leyendas.vigilar_proyecto()
        assert proyecto.read(ruta)
        [capa] = proyecto.mapLayers().values()
        [nodo] = nodos()
        assert isinstance(nodo, QgsColorRampLegendNode)
    finally:
        leyendas.dejar_de_vigilar()
        proyecto.clear()


def _a_grados(x, y):
    import math

    return x / 20037508.342789244 * 180.0, math.degrees(2 * math.atan(math.exp(y / 6378137.0)) - math.pi / 2)


def test_las_agregadas_se_suscriben_y_se_repintan_con_el_tiempo_real(app):
    """Un cambio en la capa trae ``tile_version``: las teselas se piden con ella, como
    la web (``_v``), y la caché no sirve las viejas. La vista sustituye a sus puntos, así
    que la capa agregada tiene que suscribirse sola al mapa."""
    import time

    from qgis.core import QgsProject
    from qgis.PyQt.QtCore import QCoreApplication

    from geosian.gui import realtime_hub
    from geosian.gui.browser_dock import ROL_DATOS, GeosianBrowserDock
    from tests.fake_server import FakeGeosian
    from tests.fake_ws import FakeWebSocket
    from tests.test_gui import IfaceFalso

    def esperar(condicion, segundos=4):
        limite = time.monotonic() + segundos
        while time.monotonic() < limite:
            QCoreApplication.processEvents()
            if condicion():
                return True
            time.sleep(0.02)
        return False

    canal = FakeWebSocket()
    with FakeGeosian() as fake:
        try:
            realtime_hub.watch_project()
            connections.save_connection("HexVivo", fake.url, "a@b.c")
            connections.set_session("HexVivo", "tok-de-prueba", "jwt")
            connections.set_ws_url("HexVivo", canal.url)
            panel = GeosianBrowserDock(IfaceFalso())
            raiz = panel.arbol.topLevelItem(0)
            panel._al_desplegar(raiz)
            mapa = raiz.child(0).child(0)
            panel._al_desplegar(mapa)
            datos = dict(mapa.child(0).data(0, ROL_DATOS))
            datos["vista"] = {"id": 9, "name": "Densidad"}
            [capa] = panel.añadir_capa(datos)
            assert canal.conectado.wait(3)
            assert esperar(lambda: {"type": "subscribe_map", "map_id": 4} in canal.recibidos)

            x0, y0 = aggregated.to_mercator(-3.75, 40.38)
            x1, y1 = aggregated.to_mercator(-3.65, 40.43)
            celdas.actualizar(capa, (x0, y0, x1, y1), 12)
            assert esperar(lambda: capa.featureCount() > 0)

            def con_version(v):
                return [c for r, c in fake.peticiones if "/geodata/tiles/" in r and c.get("_v") == [v]]

            canal.enviar({"type": "layer_data_changed", "map_id": 4, "layer_id": 11,
                          "change_type": "update", "tile_version": 7})
            assert esperar(lambda: con_version("7"))
            assert esperar(lambda: capa.featureCount() > 0)
            assert len(capa.renderer().rootRule().children()) == 6  # el estilo se queda
            # Un aviso de otra capa no la toca.
            canal.enviar({"type": "layer_data_changed", "map_id": 4, "layer_id": 99,
                          "change_type": "update", "tile_version": 8})
            esperar(lambda: False, 1)
            assert not con_version("8")
        finally:
            realtime_hub.unwatch_project()
            realtime_hub.stop_all()
            QgsProject.instance().clear()
            connections.remove_connection("HexVivo")
            canal.cerrar()


def test_el_calor_usa_radio_intensidad_umbral_y_la_rampa_entera(app):
    """Como el ``HeatmapLayer`` de la web: debajo del umbral no se pinta; la intensidad
    satura antes; los seis colores de la rampa, no solo los extremos."""
    from geosian.core import styles, symbology

    config = {"visualization": "heatmap", "heatmap": {
        "radiusPixels": 40, "intensity": 2, "threshold": 0.1, "colorRamp": "viridis",
        "weightAttribute": "altura"}}
    resolver = {"altura": "altura"}.get
    calor, _avisos = symbology.view_renderer(config, "points", {}, resolver)
    assert calor.type() == "heatmapRenderer"
    # El radio, corregido: la mancha del núcleo cuártico de QGIS a media altura igual que
    # la de la gaussiana de deck.gl (σ = radio/6, weights-fs): 0,196·40 / 0,541 ≈ 14,5 px.
    assert abs(calor.radius() - 14.5) < 0.1
    # La leyenda, con los textos de la web (QGIS 3.34 no deja cambiarlos).
    if hasattr(calor, "legendSettings"):
        assert calor.legendSettings().minimumLabel() == "Baja densidad"
        assert calor.legendSettings().maximumLabel() == "Alta densidad"
    assert "altura" in calor.weightExpression()
    # El sombreador del HeatmapLayer (deck.gl 9, triangle-layer-fragment): con v el peso
    # entre el máximo, el color sale de una textura de 6 píxeles con filtro lineal en
    # f = min(v·intensidad, 1) (los centros de los píxeles en (i + 0,5)/6) y la opacidad es
    # min(v·intensidad/umbral, 1). Con intensidad 2 y umbral 0,1, a mano:
    rampa = calor.colorRamp()
    seis = [c[:3] for c in styles.ramp_colors("viridis", 6)]

    def color(v):
        return rampa.color(v).getRgb()

    assert color(0)[3] == 0                                   # en el cero, nada
    assert color(0.025)[:3] == seis[0]                        # f = 0,05 < 0,5/6: el primero
    assert abs(color(0.025)[3] - 128) <= 1                    # a medio camino del umbral (0,05)
    assert color(0.05)[3] == 255                              # desde el umbral, opaco
    medio = [round((a + b) / 2) for a, b in zip(seis[2], seis[3])]
    assert all(abs(x - y) <= 1 for x, y in zip(color(0.25)[:3], medio))   # f = 0,5: entre 3.º y 4.º
    assert color(5.5 / 12)[:3] == seis[5]                     # satura en el centro del último
    assert color(1)[:3] == seis[5]


def _esperar(condicion, segundos=10):
    import time

    from qgis.PyQt.QtCore import QCoreApplication

    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        QCoreApplication.processEvents()
        if condicion():
            return True
        time.sleep(0.02)
    return False


def _añadir_vista(fake, nombre, vista):
    from geosian.gui.browser_dock import ROL_DATOS, GeosianBrowserDock
    from tests.test_gui import IfaceFalso

    connections.save_connection(nombre, fake.url, "a@b.c")
    connections.set_session(nombre, "tok-de-prueba", "jwt")
    panel = GeosianBrowserDock(IfaceFalso())
    raiz = panel.arbol.topLevelItem(0)
    panel._al_desplegar(raiz)
    mapa = raiz.child(0).child(0)
    panel._al_desplegar(mapa)
    datos = dict(mapa.child(0).data(0, ROL_DATOS))
    datos["vista"] = vista
    return panel.añadir_capa(datos)


@pytest.mark.parametrize("grande", [False, True])
def test_el_calor_de_una_capa_grande_va_con_las_celdas_del_servidor(app, monkeypatch, grande):
    """Una capa grande solo se pinta de cerca; de lejos, sin esto, el calor no salía. La
    web pide las celdas agregadas (``cells=96``) y en móvil las pinta coloreadas."""
    from qgis.core import QgsMapLayerType, QgsProject

    from geosian.provider import provider as modulo
    from tests.fake_server import FakeGeosian

    if grande:
        monkeypatch.setattr(modulo, "LARGE_LAYER", 2)
    with FakeGeosian() as fake:
        try:
            [capa] = _añadir_vista(fake, "Calor", {"id": 10, "name": "Calor"})
            if grande:
                assert capa.type() == QgsMapLayerType.VectorLayer and celdas.es_de_celdas(capa)
                info = json.loads(capa.customProperty(aggregated.PROPIEDAD))
                assert info["extra"] == {"cells": 96}
                assert len(capa.renderer().rootRule().children()) == 6
            else:
                # La pequeña, con el calor de QGIS sobre sus puntos.
                assert capa.type() == QgsMapLayerType.VectorLayer
                assert capa.renderer().type() == "heatmapRenderer"
        finally:
            QgsProject.instance().clear()
            connections.remove_connection("Calor")


def test_los_contornos_son_isolineas_por_umbral_con_su_color_y_grosor(app):
    """Antes, puntos con un aviso. Ahora una capa de líneas: una por umbral de la vista,
    calculada con las celdas del servidor, con su color, su grosor y su leyenda."""
    from qgis.core import QgsProject, QgsWkbTypes

    from tests.fake_server import FakeGeosian

    with FakeGeosian() as fake:
        try:
            [capa] = _añadir_vista(fake, "Contornos", {"id": 11, "name": "Contornos"})
            assert capa.name() == "Arbolado · Contornos"
            # Se calcula en segundo plano: la capa entra al momento, vacía, y la
            # ventana no se congela mientras se piden las teselas (8 s en Cáceres).
            assert capa.featureCount() == 0
            # Y sin bajar los puntos de la capa: la extensión sale de sus metadatos.
            assert not [r for r, _ in fake.peticiones if r == "/api/v1/geodata/paginated/"]
            assert _esperar(lambda: capa.featureCount() == 2)
            assert QgsWkbTypes.geometryType(capa.wkbType()) == QgsWkbTypes.GeometryType.LineGeometry
            umbrales = sorted(f["umbral"] for f in capa.getFeatures())
            assert umbrales == [1, 5]  # el grupo de diez pasa del 5; el resto, del 1
            assert all(not f.geometry().isEmpty() for f in capa.getFeatures())
            pedidas = [c for r, c in fake.peticiones if r.startswith("/api/v1/geodata/tiles/")]
            assert pedidas and all(c.get("geom") == ["centroid"] for c in pedidas)
            assert all(c.get("cells") == ["96"] for c in pedidas)
            categorias = capa.renderer().categories()
            assert [c.label() for c in categorias] == ["≥ 1", "≥ 5"]
            rojo = categorias[1].symbol()
            assert rojo.color().getRgb() == (240, 59, 32, 200) and rojo.width() == 3
            assert abs(capa.opacity() - 0.8) < 1e-6
        finally:
            QgsProject.instance().clear()
            connections.remove_connection("Contornos")


MVT = {"mode": "mvt", "auto_threshold": 5000}


@pytest.mark.parametrize("vista, tile_config, opacidad", [
    ({"id": 10, "name": "Calor"}, None, 0.9),      # calor: 0,9 por omisión
    ({"id": 10, "name": "Calor"}, MVT, 0.9),       # también por teselas (maps.jsx, aggData)
    ({"id": 8, "name": "Iconos"}, None, 0.9),      # iconos en GeoJSON, también
    ({"id": 9, "name": "Densidad"}, None, 0.7),    # hexágonos en GeoJSON, la suya (createViewHexagonLayer)
    ({"id": 9, "name": "Densidad"}, MVT, 1.0),     # por teselas, la web no la aplica
    ({"id": 7, "name": "Tilos"}, None, 1.0),       # una vista normal: la transparencia va en el color
])
def test_la_opacidad_de_la_vista_como_la_web(app, vista, tile_config, opacidad):
    """``point.opacity`` (0,9 si no dice) es la opacidad de las visualizaciones avanzadas
    en la web, salvo en su camino por teselas para hexágonos e iconos (``useMvtLayers``
    no la pasa); en las normales no cuenta."""
    from qgis.core import QgsProject

    from tests.fake_server import FakeGeosian

    with FakeGeosian() as fake:
        fake.poner_tile_config(tile_config)
        try:
            [capa] = _añadir_vista(fake, "Opacidad", vista)
            assert abs(capa.opacity() - opacidad) < 1e-6
        finally:
            QgsProject.instance().clear()
            connections.remove_connection("Opacidad")


def test_una_vista_que_colorea_por_un_campo_de_los_partes(app):
    """``additional_info.<tipo>.<campo>``: la web pide ``include_ai_attr`` y colorea por el
    valor del parte. Antes la capa no tenía ese campo y todo salía con el color de «Otros»."""
    from qgis.core import QgsProject, QgsRenderContext

    from tests.fake_server import FakeGeosian

    with FakeGeosian() as fake:
        try:
            [capa] = _añadir_vista(fake, "PorPartes", {"id": 12, "name": "Por labor"})
            campo = "additional_info.parte_poda.labor"
            assert capa.fields().indexOf(campo) >= 0
            assert capa.attributeAlias(capa.fields().indexOf(campo)) == "Parte de poda · Labor"
            fake.peticiones.clear()
            valores = {f["id"]: f[campo] for f in capa.getFeatures()}
            assert valores[1001] == "Poda" and valores[1002] == "Aclareo"
            # Una lista, como la escribe String() en la web: si no, no casa con la categoría.
            assert valores[1003] == "Poda"
            assert any(c.get("include_ai_attr") == ["parte_poda.labor"]
                       for r, c in fake.peticiones if r == "/api/v1/geodata/paginated/")
            # El estilo lo encuentra: cada elemento con el color de su categoría.
            contexto = QgsRenderContext()
            renderizador = capa.renderer().clone()
            renderizador.startRender(contexto, capa.fields())
            colores = {f["id"]: renderizador.symbolsForFeature(f, contexto)[0].color().name()
                       for f in capa.getFeatures()}
            renderizador.stopRender(contexto)
            assert colores[1001] == colores[1003] == "#ff0000" and colores[1002] == "#0000ff"
        finally:
            QgsProject.instance().clear()
            connections.remove_connection("PorPartes")


def test_graduado_y_peso_del_calor_por_un_campo_de_los_partes(app):
    """El valor de un parte llega como texto (``include_ai_attr``); graduar o pesar el
    calor por él tiene que pedirlo y leerlo como número, igual que un campo de la capa."""
    from qgis.core import (
        QgsExpression,
        QgsExpressionContext,
        QgsExpressionContextUtils,
        QgsFeature,
        QgsRenderContext,
        QgsVectorLayer,
    )

    from geosian.core import symbology, views

    campo = "additional_info.parte_poda.altura"
    for clave in ("heatmap", "contour"):
        assert views.ai_attribute({clave: {"weightAttribute": campo}}) == ("parte_poda", "altura")
    assert views.ai_attribute({"color": {"mode": "graduated", "attribute": campo}}) == (
        "parte_poda", "altura")
    assert views.ai_attribute({"color": {"attribute": "altura"}}) is None

    capa = QgsVectorLayer(f'Point?crs=EPSG:4326&field=id:integer&field={campo}:string', "p", "memory")
    elementos = []
    for fid, valor in ((1, "3"), (2, "12")):
        f = QgsFeature(capa.fields())
        f.setAttributes([fid, valor])
        elementos.append(f)
    capa.dataProvider().addFeatures(elementos)
    resolver = symbology.field_resolver(capa.fields(), {})

    graduado, avisos = symbology.view_renderer(
        {"color": {"mode": "graduated", "attribute": campo, "breaks": [0, 10, 20],
                   "colors": [[255, 0, 0], [0, 0, 255]]}}, "points", {}, resolver)
    assert not avisos
    contexto = QgsRenderContext()
    contexto.setExpressionContext(
        QgsExpressionContext(QgsExpressionContextUtils.globalProjectLayerScopes(capa)))
    graduado.startRender(contexto, capa.fields())
    colores = {}
    for f in capa.getFeatures():
        contexto.expressionContext().setFeature(f)
        colores[f["id"]] = graduado.symbolsForFeature(f, contexto)[0].color().name()
    graduado.stopRender(contexto)
    assert colores == {1: "#ff0000", 2: "#0000ff"}

    calor, _ = symbology.view_renderer(
        {"visualization": "heatmap", "heatmap": {"weightAttribute": campo}}, "points", {}, resolver)
    expresion = QgsExpression(calor.weightExpression())
    ctx = QgsExpressionContext(QgsExpressionContextUtils.globalProjectLayerScopes(capa))
    pesos = []
    for f in capa.getFeatures():
        ctx.setFeature(f)
        pesos.append(expresion.evaluate(ctx))
    assert pesos == [3.0, 12.0]
