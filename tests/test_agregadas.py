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
