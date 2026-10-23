"""Lo que no debe colarse por el camino QGIS → GreenCityControl (revisión del 23/10/2026)."""

import json

import pytest

qgis_core = pytest.importorskip("qgis.core")

from geosian.core import aggregated, connections, schema
from geosian.core.errors import GeosianError
from tests.test_agregadas import _esperar


def test_un_proyecto_no_puede_mandar_el_token_a_otro_servidor(app):
    """Las capas de hexágonos guardan la dirección en el proyecto; antes se usaba esa, con
    el token de la conexión. Un .qgz con otra dirección se llevaba la credencial."""
    from qgis.core import QgsProject

    from geosian.gui import celdas
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
            info = json.loads(capa.customProperty(aggregated.PROPIEDAD))
            capa.setCustomProperty(aggregated.PROPIEDAD, json.dumps({**info, "base_url": "https://atacante.invalid"}))
            fake.peticiones.clear()

            x0, y0 = aggregated.to_mercator(-3.75, 40.38)
            x1, y1 = aggregated.to_mercator(-3.65, 40.43)
            celdas.actualizar(capa, (x0, y0, x1, y1), 12)

            # Las teselas se piden a la conexión, no a la dirección del proyecto.
            assert _esperar(lambda: capa.featureCount() > 0)
            assert [r for r, _ in fake.peticiones if r.startswith("/api/v1/geodata/tiles/12/")]
        finally:
            QgsProject.instance().clear()
            connections.remove_connection("Hex")


def test_el_cliente_no_manda_el_token_a_teselas_de_otro_servidor():
    from geosian.core.client import GeosianClient

    cliente = GeosianClient("https://app.ejemplo.org", token="secreto")

    assert cliente.es_suya("https://app.ejemplo.org:443/api/v1/geodata/tiles/1/2/3.mvt")
    assert not cliente.es_suya("https://app.ejemplo.org.atacante.invalid/api/v1/x")
    assert not cliente.es_suya("http://app.ejemplo.org/api/v1/x")
    with pytest.raises(GeosianError, match="otro servidor"):
        cliente.tiles(["https://atacante.invalid/api/v1/geodata/tiles/1/2/3.mvt"])


def test_un_valor_del_servidor_no_se_sale_de_su_cadena_en_una_expresion(app):
    from qgis.core import QgsExpression, QgsExpressionContext

    carga = "\\' || @qgis_os_name || '"
    expresion = QgsExpression(schema._quote_value(carga))

    assert not expresion.hasParserError(), expresion.parserErrorString()
    assert expresion.evaluate(QgsExpressionContext()) == carga
    campo = QgsExpression(schema._quote_field("a\\") + " IS NULL")
    assert not campo.hasParserError()


def test_un_adjunto_no_se_guarda_fuera_de_su_carpeta():
    from geosian.gui.media_widget import _nombre_seguro

    assert _nombre_seguro("../../etc", "../.bashrc") == "etc-bashrc"
    assert _nombre_seguro("7", "..\\..\\informe.pdf") == "7-informe.pdf"
    assert "/" not in _nombre_seguro("a/b", "c/d") and "\\" not in _nombre_seguro("a\\b", "c\\d")


def test_la_carpeta_de_adjuntos_es_solo_de_quien_usa_qgis():
    import os
    import stat
    import sys

    from geosian.gui.media_widget import _carpeta_temporal

    carpeta = _carpeta_temporal()

    assert os.path.isdir(carpeta) and carpeta == _carpeta_temporal()
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(carpeta).st_mode) == 0o700


@pytest.mark.parametrize(
    "url, vale",
    [
        ("https://app.greencitycontrol.com", True),
        ("http://localhost:8000", True),
        ("http://127.0.0.1:8000", True),
        ("http://app.greencitycontrol.com", False),
        ("ftp://app.greencitycontrol.com", False),
        ("app.greencitycontrol.com", False),
    ],
)
def test_sin_https_no_se_conecta_salvo_en_el_propio_equipo(url, vale):
    from geosian.gui.connection_dialog import url_insegura

    assert (url_insegura(url) is None) is vale


def test_una_redireccion_a_otro_servidor_no_lleva_el_token():
    import io
    import urllib.request

    from geosian.core.http import _SinTokenFuera

    peticion = urllib.request.Request("https://app.ejemplo.org/api/v1/x", headers={"Authorization": "Token s"})
    manejador = _SinTokenFuera()

    fuera = manejador.redirect_request(peticion, io.BytesIO(), 302, "Found", {}, "https://atacante.invalid/x")
    dentro = manejador.redirect_request(peticion, io.BytesIO(), 302, "Found", {}, "https://app.ejemplo.org/api/v1/y")

    assert not fuera.has_header("Authorization")
    assert dentro.has_header("Authorization")


def test_un_aviso_no_pinta_html_del_servidor():
    from geosian.gui.avisos import seguro

    assert seguro('<a href="https://atacante.invalid">Pulsa</a> & sigue') == (
        '&lt;a href="https://atacante.invalid"&gt;Pulsa&lt;/a&gt; &amp; sigue'
    )
