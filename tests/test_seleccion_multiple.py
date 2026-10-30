"""Una selección múltiple (un campo que guarda una lista) en los estilos y la edición.

En QGIS 4 ``to_string`` de una lista da NULL, la clasificación por categorías no casa
listas y el editor de listas deja escribir cualquier cosa. Con QGIS de verdad y el
servidor falso, cuyo «operacion» es una selección múltiple.
"""

import pytest

qgis_core = pytest.importorskip("qgis.core")

from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsExpression,
    QgsExpressionContext,
    QgsExpressionContextUtils,
    QgsFieldConstraints,
    QgsRenderContext,
    QgsSymbol,
    QgsVectorLayerUtils,
    QgsWkbTypes,
)

from qgis.PyQt.QtGui import QColor

from geosian.core import lad, symbology
from tests.test_edicion_atributos import (  # noqa: F401
    abrir,
    editar,
    elemento,
    servidor,
)


@pytest.fixture
def capa(servidor):  # noqa: F811
    # Los datos guardan a veces un texto suelto donde el esquema dice lista.
    servidor.estado.elementos[2]["properties"]["operacion"] = "Tala"
    return abrir(servidor)


def _evaluar(capa, expresion):
    expr = QgsExpression(expresion)
    contexto = QgsExpressionContext(QgsExpressionContextUtils.globalProjectLayerScopes(capa))
    resultado = {}
    for f in capa.getFeatures():
        contexto.setFeature(f)
        resultado[f.id()] = expr.evaluate(contexto)
        assert not expr.hasEvalError(), expr.evalErrorString()
    return resultado


def test_el_estilo_de_la_capa_casa_una_lista_como_la_web(capa):
    # La web busca el color con String(valor): ["Tala"] es "Tala" y
    # ["Instalación anclaje", "Tala"] es "Instalación anclaje,Tala".
    esquema = dict(capa.dataProvider().schema)
    esquema["styles"] = {"colors": [
        {"attribute": "operacion", "priority": 0, "allowed_values": {"Tala": "#ff0000", "Poda": "#00ff00"}},
        {"attribute": "especie", "priority": 1, "allowed_values": {"Platanus x hispanica": "#0000ff"}},
    ]}
    proveedor = capa.dataProvider()
    resolver = symbology.field_resolver(proveedor.fields(), proveedor.attr_map)
    renderizador, avisos = symbology.base_renderer(esquema, "points", resolver)
    assert avisos == []

    reglas = {r.label(): r.filterExpression() for r in renderizador.rootRule().children()}
    assert _evaluar(capa, reglas["Tala"]) == {1001: False, 1002: False, 1003: True}
    assert _evaluar(capa, reglas["Poda"]) == {1001: True, 1002: False, 1003: False}
    # Lo marcado como «Poda» ya no cae en el color de la especie.
    assert _evaluar(capa, reglas["Platanus x hispanica"]) == {1001: False, 1002: False, 1003: False}


def test_una_lista_vacia_cuenta_como_vacia(servidor):  # noqa: F811
    from geosian.core import styles

    servidor.estado.elementos[0]["properties"]["operacion"] = []
    capa = abrir(servidor)
    vacio = styles.filter_group_expression({"rules": [{"field": "operacion", "operator": "is_empty"}]})
    assert _evaluar(capa, vacio) == {1001: True, 1002: False, 1003: True}


def test_el_campo_de_texto_se_clasifica_por_categorias(capa):
    lad.add_text_fields(capa, capa.dataProvider().schema)
    lad.add_text_fields(capa, capa.dataProvider().schema)  # rehacer la ficha no lo duplica

    nombres = [f.name() for f in capa.fields()]
    assert nombres.count("operacion_texto") == 1
    idx = capa.fields().indexOf("operacion_texto")
    assert capa.fields().at(idx).alias() == "Operaciones (texto)"
    assert {f.id(): f["operacion_texto"] for f in capa.getFeatures()} == {
        1001: "Poda",
        1002: "Instalación anclaje, Tala",
        1003: "Tala",
    }

    valores = capa.uniqueValues(idx)
    simbolo = QgsSymbol.defaultSymbol(QgsWkbTypes.PointGeometry)
    categorias = QgsCategorizedSymbolRenderer.createCategories(list(valores), simbolo, capa, "operacion_texto")
    color = {}
    for i, categoria in enumerate(categorias):
        propio = categoria.symbol().clone()
        propio.setColor(QColor.fromHsv(i * 60, 255, 255))
        categoria.setSymbol(propio)
        color[categoria.value()] = propio.color().name()
    renderizador = QgsCategorizedSymbolRenderer("operacion_texto", categorias)
    contexto = QgsRenderContext()
    contexto.setExpressionContext(QgsExpressionContext(QgsExpressionContextUtils.globalProjectLayerScopes(capa)))
    renderizador.startRender(contexto, capa.fields())
    try:
        for f in capa.getFeatures():
            contexto.expressionContext().setFeature(f)
            pintado = renderizador.originalSymbolForFeature(f, contexto)
            assert pintado is not None
            assert pintado.color().name() == color[f["operacion_texto"]], f"el elemento {f.id()} cae en otra categoría"
    finally:
        renderizador.stopRender(contexto)


def test_el_campo_de_texto_no_se_manda_a_geosian(capa, servidor):  # noqa: F811
    lad.add_text_fields(capa, capa.dataProvider().schema)
    editar(capa, 1001, operacion=["Poda", "Tala"])

    assert capa.commitChanges(), capa.commitErrors()
    guardado = elemento(servidor, 1001)
    assert guardado["operacion"] == ["Poda", "Tala"]
    assert "operacion_texto" not in guardado


def test_avisa_de_un_valor_fuera_de_la_lista(capa):
    lad.apply_editor_config(capa, capa.dataProvider().schema)
    idx = capa.fields().indexOf("operacion")
    assert capa.fields().at(idx).constraints().constraints() & QgsFieldConstraints.ConstraintExpression

    def cumple(valor):
        f = capa.getFeature(1001)
        f.setAttribute(idx, valor)
        return QgsVectorLayerUtils.validateAttribute(
            capa, f, idx, QgsFieldConstraints.ConstraintStrengthSoft
        )[0]

    assert cumple(["Poda", "Tala"])
    assert cumple(None)
    assert cumple([])
    assert not cumple(["Poda", "Riego a manta"])
