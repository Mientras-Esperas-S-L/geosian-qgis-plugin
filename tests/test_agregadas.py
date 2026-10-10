"""Vistas agregadas (hexágonos…) con las teselas que agrega el servidor."""

import pytest

pytest.importorskip("qgis.core")

from qgis.core import QgsApplication, QgsAuthMethodConfig

from geosian.core import aggregated, connections


def _cabecera(authcfg):
    config = QgsAuthMethodConfig()
    QgsApplication.authManager().loadAuthenticationConfig(authcfg, config, True)
    return config.method(), config.configMap()


def test_la_credencial_de_las_teselas_va_en_el_gestor_y_no_en_la_uri(app):
    connections.save_connection("Teselas", "https://api.ejemplo.org", "a@b.c")
    try:
        connections.set_session("Teselas", "tok-secreto", "jwt")
        authcfg = connections.tile_authcfg("Teselas")
        assert authcfg
        assert _cabecera(authcfg) == ("APIHeader", {"Authorization": "Token tok-secreto"})

        uri = aggregated.tile_layer_uri(
            "https://api.ejemplo.org", 120, {"attr__especie": ["Tilo", "Olmo"]}, authcfg
        )
        assert "tok-secreto" not in uri
        assert f"authcfg={authcfg}" in uri
        assert "agg%3Dhex" in uri and "layer_id%3D120" in uri
        assert "attr__especie%3DTilo" in uri and "attr__especie%3DOlmo" in uri
        assert "{z}/{x}/{y}.mvt" in uri

        # Al volver a entrar, la misma configuración con la sesión nueva.
        connections.set_session("Teselas", "tok-nuevo", "jwt")
        assert connections.tile_authcfg("Teselas") == authcfg
        assert _cabecera(authcfg)[1] == {"Authorization": "Token tok-nuevo"}
    finally:
        connections.remove_connection("Teselas")
    assert not QgsApplication.authManager().configIds().count(authcfg)


def test_sin_sesion_no_hay_credencial_de_teselas(app):
    connections.save_connection("SinSesion", "https://api.ejemplo.org", "a@b.c")
    try:
        assert connections.tile_authcfg("SinSesion") is None
    finally:
        connections.remove_connection("SinSesion")


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

            assert capa.type() == QgsMapLayerType.VectorTileLayer
            assert capa.name() == "Arbolado · Densidad"
            fuente = capa.source()
            assert "tok-de-prueba" not in fuente and "authcfg=" in fuente
            assert "agg%3Dhex" in fuente
            # El filtro de la vista viaja a las teselas, como en la web.
            assert "attr__especie%3DTilia" in fuente
            assert abs(capa.opacity() - 0.7) < 1e-6
            # Un estilo por tramo de la rampa: la leyenda sale como el degradado de la
            # web, con «Baja densidad» y «Alta densidad» en los extremos.
            estilos = capa.renderer().styles()
            assert len(estilos) == 6
            assert {e.layerName() for e in estilos} == {"agg"}
            assert [e.styleName() for e in estilos] == [
                "Baja densidad", "", "", "", "", "Alta densidad",
            ]
            assert all("ln(1 + 50)" in e.filterExpression() for e in estilos)
            assert estilos[0].filterExpression().endswith("= 0")
            assert capa in QgsProject.instance().mapLayers().values()
        finally:
            QgsProject.instance().clear()
            connections.remove_connection("Hex")


def test_h3_va_por_los_hexagonos_del_servidor_como_la_web_en_capas_grandes():
    """Sobre una capa MVT la web pinta H3 con los mismos hexágonos del servidor."""
    from geosian.core import styles

    vista = styles.view_style({"visualization": "h3hexagon", "h3hexagon": {"resolution": 9},
                               "point": {"opacity": 0.85}}, "points")
    assert vista["kind"] == "hexagon"
    assert vista["ramp"] == "plasma"  # la de la web cuando la vista no dice otra
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

            canal.enviar({"type": "layer_data_changed", "map_id": 4, "layer_id": 11,
                          "change_type": "update", "tile_version": 7})
            assert esperar(lambda: "_v%3D7" in capa.source())
            assert len(capa.renderer().styles()) == 6  # el estilo se queda
            # Un aviso de otra capa no la toca.
            canal.enviar({"type": "layer_data_changed", "map_id": 4, "layer_id": 99,
                          "change_type": "update", "tile_version": 8})
            esperar(lambda: False, 1)
            assert "_v%3D7" in capa.source()
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
    assert calor.radius() == 40
    # La leyenda, con los textos de la web (QGIS 3.34 no deja cambiarlos).
    if hasattr(calor, "legendSettings"):
        assert calor.legendSettings().minimumLabel() == "Baja densidad"
        assert calor.legendSettings().maximumLabel() == "Alta densidad"
    assert "altura" in calor.weightExpression()
    rampa = calor.colorRamp()
    assert rampa.color1().alpha() == 0                       # nada de color en el cero
    posiciones = [round(p.offset, 3) for p in rampa.stops()]
    assert posiciones[0] == 0.1                              # el umbral
    assert max(posiciones) == 0.5                            # intensidad 2: satura en la mitad
    seis = styles.ramp_colors("viridis", 6)
    assert {p.color.getRgb()[:3] for p in rampa.stops()} | {rampa.color2().getRgb()[:3]} >= {
        c[:3] for c in seis}


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
                assert capa.type() == QgsMapLayerType.VectorTileLayer
                assert "cells%3D96" in capa.source() and "agg%3Dhex" in capa.source()
                assert len(capa.renderer().styles()) == 6
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


@pytest.mark.parametrize("vista, opacidad", [
    ({"id": 10, "name": "Calor"}, 0.9),     # calor en capa pequeña: 0,9 por omisión
    ({"id": 8, "name": "Iconos"}, 0.9),     # iconos, también
    ({"id": 7, "name": "Tilos"}, 1.0),      # una vista normal: la transparencia va en el color
])
def test_la_opacidad_de_la_vista_como_la_web(app, vista, opacidad):
    """``point.opacity`` (0,9 si no dice) es la opacidad de las visualizaciones avanzadas
    en la web; en las normales no cuenta."""
    from qgis.core import QgsProject

    from tests.fake_server import FakeGeosian

    with FakeGeosian() as fake:
        try:
            [capa] = _añadir_vista(fake, "Opacidad", vista)
            assert abs(capa.opacity() - opacidad) < 1e-6
        finally:
            QgsProject.instance().clear()
            connections.remove_connection("Opacidad")
