"""El filtro de la capa («Filtrar…» de QGIS) traducido a la API.

La web manda sus filtros al servidor como ``attr__campo=valor`` (y ``__gte``,
``__lte`` para los rangos), y aquí se hace lo mismo con la parte del filtro de
QGIS que se puede expresar así. Lo demás lo evalúa QGIS sobre lo que llega.

La traducción solo puede **ensanchar**, nunca dejar fuera algo que el filtro
acepta: el servidor recorta lo que puede y luego se evalúa siempre la expresión
entera. Por eso solo se traduce lo que cuelga de ANDs (un OR o un NOT no se
traducen), ``>`` se pide como ``__gte`` y la igualdad con números no se manda
(el servidor compara como texto y ``12`` no es ``12.0``).
"""

from qgis.core import (
    QgsExpression,
    QgsExpressionNode,
    QgsExpressionNodeBinaryOperator,
)

_OP = QgsExpressionNodeBinaryOperator.BinaryOperator


def parse(texto):
    """``QgsExpression`` del filtro, o ``None`` si está mal escrito."""
    expresion = QgsExpression(texto)
    if expresion.hasParserError() or expresion.rootNode() is None:
        return None
    return expresion


def server_params(expresion, attr_map):
    """Parámetros ``attr__`` para la parte del filtro que entiende la API.

    Args:
        attr_map: nombre del campo en QGIS → atributo del esquema. Solo se
            traducen los campos del esquema, con su nombre en la API.
    """
    params = {}
    for nodo in _conjunciones(expresion.rootNode()):
        _traducir(nodo, attr_map, params)
    return {k: v for k, v in params.items() if v is not None}


def _conjunciones(nodo):
    if (
        nodo.nodeType() == QgsExpressionNode.NodeType.ntBinaryOperator
        and nodo.op() == _OP.boAnd
    ):
        yield from _conjunciones(nodo.opLeft())
        yield from _conjunciones(nodo.opRight())
    else:
        yield nodo


def _campo(nodo, attr_map):
    if nodo.nodeType() != QgsExpressionNode.NodeType.ntColumnRef:
        return None
    attr = attr_map.get(nodo.name())
    return attr.get("name") if attr else None


def _literal(nodo):
    if nodo.nodeType() != QgsExpressionNode.NodeType.ntLiteral:
        return None
    valor = nodo.value()
    return None if valor is None or (hasattr(valor, "isNull") and valor.isNull()) else valor


def _traducir(nodo, attr_map, params):
    tipo = nodo.nodeType()

    if tipo == QgsExpressionNode.NodeType.ntInOperator and not nodo.isNotIn():
        campo = _campo(nodo.node(), attr_map)
        valores = [_literal(n) for n in nodo.list().list()]
        if campo and valores and all(isinstance(v, str) for v in valores):
            _poner(params, f"attr__{campo}", valores)
        return

    if tipo != QgsExpressionNode.NodeType.ntBinaryOperator:
        return
    op = nodo.op()
    izquierda, derecha = nodo.opLeft(), nodo.opRight()
    campo, valor = _campo(izquierda, attr_map), _literal(derecha)
    if campo is None:
        # «5 < "altura"» es lo mismo dado la vuelta.
        campo, valor = _campo(derecha, attr_map), _literal(izquierda)
        op = {_OP.boGT: _OP.boLT, _OP.boLT: _OP.boGT, _OP.boGE: _OP.boLE, _OP.boLE: _OP.boGE}.get(op, op)
    if campo is None or valor is None:
        return

    if op == _OP.boEQ and isinstance(valor, str):
        _poner(params, f"attr__{campo}", [valor])
    elif op in (_OP.boGE, _OP.boGT) and _es_numero(valor):
        _poner(params, f"attr__{campo}__gte", str(valor))
    elif op in (_OP.boLE, _OP.boLT) and _es_numero(valor):
        _poner(params, f"attr__{campo}__lte", str(valor))


def _poner(params, clave, valor):
    # Dos condiciones sobre la misma clave: la API no las sabe combinar con AND.
    # No se manda ninguna y que filtre QGIS.
    if clave in params:
        params[clave] = None
    else:
        params[clave] = valor


def _es_numero(valor):
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)
