"""Las expresiones de ``visible_if`` evaluadas por QGIS, no solo leídas como texto.

``test_schema.py`` mira la forma de la expresión. Aquí se comprueba que QGIS la
entiende y da el resultado de la web: una expresión que no compila deja la
pestaña o el campo ocultos sin avisar, que es lo que pasaba con ``is_array``,
una función que QGIS no tiene.
"""

import pytest

qgis_core = pytest.importorskip("qgis.core")

from qgis.core import (
    QgsExpression,
    QgsExpressionContext,
    QgsFeature,
    QgsField,
    QgsFields,
)
from qgis.PyQt.QtCore import QMetaType

from geosian.core import schema as S


def _evaluar(condicion, valor, app):
    campos = QgsFields()
    tipo = QMetaType.Type.QVariantList if isinstance(valor, list) else QMetaType.Type.QString
    campos.append(QgsField("tipo", tipo))
    elemento = QgsFeature(campos)
    elemento["tipo"] = valor

    contexto = QgsExpressionContext()
    contexto.setFields(campos)
    contexto.setFeature(elemento)

    expresion = QgsExpression(S.visible_if_to_expression(condicion))
    assert not expresion.hasParserError(), expresion.parserErrorString()
    resultado = expresion.evaluate(contexto)
    assert not expresion.hasEvalError(), expresion.evalErrorString()
    return bool(resultado)


@pytest.mark.parametrize(
    "condicion, valor, visible",
    [
        ({"operator": "equals", "value": "palmera"}, "palmera", True),
        ({"operator": "equals", "value": "palmera"}, "conifera", False),
        ({"operator": "equals", "value": "palmera"}, None, False),
        ({"operator": "equals", "value": "palmera"}, ["conifera", "palmera"], True),
        ({"operator": "equals", "value": "palmera"}, ["conifera"], False),
        ({"operator": "not_equals", "value": "palmera"}, "conifera", True),
        ({"operator": "not_equals", "value": "palmera"}, "palmera", False),
        ({"operator": "not_equals", "value": "palmera"}, ["conifera"], True),
        ({"operator": "not_equals", "value": "palmera"}, ["palmera"], False),
        ({"operator": "contains", "value": "palm"}, "palmera", True),
        ({"operator": "contains", "value": "palmera"}, ["palmera"], True),
        ({"operator": "contains_any", "values": ["a", "palmera"]}, "palmera", True),
        ({"operator": "contains_any", "values": ["a", "palmera"]}, ["palmera"], True),
        ({"operator": "contains_any", "values": ["a", "b"]}, ["palmera"], False),
        ({"operator": "contains_all", "values": ["a", "palmera"]}, ["a", "palmera"], True),
        ({"operator": "contains_all", "values": ["a", "palmera"]}, ["palmera"], False),
    ],
)
def test_visible_if_en_qgis(app, condicion, valor, visible):
    assert _evaluar({"field": "tipo", **condicion}, valor, app) is visible
