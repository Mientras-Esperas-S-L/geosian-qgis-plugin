"""Iconos de react-icons a SVG. No necesita QGIS."""

from geosian.core import icons
from geosian.core.http import Response, Transport
from geosian.core.icon_store import IconStore

# Recorte con la forma real de react-icons@5.5.0/fa/index.mjs.
MODULO = """// THIS FILE IS AUTO GENERATED
import { GenIcon } from '../lib/index.mjs';
export function FaTrain (props) {
  return GenIcon({"tag":"svg","attr":{"viewBox":"0 0 448 512"},"child":[{"tag":"path","attr":{"d":"M0 0h1v1z"},"child":[]}]})(props);
};
export function FaTree (props) {
  return GenIcon({"tag":"svg","attr":{"viewBox":"0 0 384 512"},"child":[{"tag":"path","attr":{"d":"M1 2L3 4z"},"child":[]}]})(props);
};
export function LuTrees (props) {
  return GenIcon({"tag":"svg","attr":{"viewBox":"0 0 24 24","fill":"none","stroke":"currentColor","strokeWidth":"2"},"child":[{"tag":"path","attr":{"d":"M5 5"},"child":[]}]})(props);
};
"""


def test_saca_el_icono_pedido_y_no_otro():
    arbol = icons.extract_tree(MODULO, "FaTree")
    assert arbol["attr"]["viewBox"] == "0 0 384 512"
    assert arbol["child"][0]["attr"]["d"] == "M1 2L3 4z"
    assert icons.extract_tree(MODULO, "FaTre") is None
    assert icons.extract_tree(MODULO, "x) {}; alert(1") is None


def test_svg_con_el_color_como_parametro_de_qgis():
    svg = icons.tree_to_svg(icons.extract_tree(MODULO, "FaTree"))
    assert svg.startswith("<svg ")
    assert 'fill="param(fill) #000000"' in svg
    assert 'd="M1 2L3 4z"' in svg


def test_iconos_de_trazo_usan_el_color_en_el_trazo():
    svg = icons.tree_to_svg(icons.extract_tree(MODULO, "LuTrees"))
    assert 'fill="none"' in svg
    assert 'stroke="param(fill) #000000"' in svg
    assert 'stroke-width="2"' in svg


def test_librerias_desconocidas_no_se_piden():
    assert icons.library_url("zz") is None
    assert icons.library_url("fa").endswith("react-icons@5.5.0/fa/index.mjs")


class TransporteContado(Transport):
    def __init__(self):
        self.pedidas = []

    def request(self, method, url, headers=None, body=None, timeout=30):
        self.pedidas.append(url)
        return Response(200, MODULO.encode("utf-8"))


def test_la_libreria_se_baja_una_vez_y_el_icono_queda_en_disco(tmp_path):
    transporte = TransporteContado()
    tienda = IconStore(carpeta=str(tmp_path), transport=transporte)
    ruta = tienda.path("fa", "FaTree")
    with open(ruta) as fichero:
        assert fichero.read().startswith("<svg ")
    assert tienda.path("fa", "FaTrain")
    assert len(transporte.pedidas) == 1

    # Otra sesión: sale del disco sin red.
    otra = IconStore(carpeta=str(tmp_path), transport=TransporteContado())
    assert otra.path("fa", "FaTree") == ruta
    assert otra._transport.pedidas == []
    assert otra.path("fa", "NoExiste") is None
